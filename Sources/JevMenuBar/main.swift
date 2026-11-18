import AppKit
import Foundation
import SwiftUI

enum ServiceState: Equatable {
    case stopped
    case starting
    case running
    case configured
    case unhealthy(String)
    case failed(String)

    var label: String {
        switch self {
        case .stopped: "Stopped"
        case .starting: "Starting"
        case .running: "Running"
        case .configured: "Configured"
    case .unhealthy(let message): message
        case .failed(let message): message
        }
    }

    var color: Color {
        switch self {
        case .running: .green
        case .configured: .blue
        case .starting: .orange
        case .unhealthy, .failed: .red
        case .stopped: .secondary
        }
    }

    /// Detail message for error states; shown under the backend line in orange.
    var errorMessage: String? {
        switch self {
        case .unhealthy(let message), .failed(let message): message
        case .stopped, .starting, .running, .configured: nil
        }
    }
}

struct OllamaModel: Identifiable, Equatable, Sendable {
    let id: String
    let name: String
    let blobPath: String
}

/// A hosted (non-Ollama) profile from typesafe.json, shown with an editable
/// rate card in the Models panel.
struct ServiceModelRow: Identifiable, Equatable, Sendable {
    let id: String
    let name: String
    let model: String
}

/// Contrastive Language Model: a Qwen3-8B last-token embedding server (llama.cpp) plus
/// `clm-serve`, which scores candidates with the CLM projection heads.
enum CLMRuntime {
    static let backendID = "clm:v0.1-8b"
    static let displayName = "CLM v0.1 8B"
    static let encoderOllamaModel = "qwen3:8b-fp16"
    static let encoderPort = 8099
    static let serverPort = 8700
    static let headPath = "/Volumes/Extreme SSD/3 Resources/LLLM/Ollama/clm/CLM_v0.1-8B.pt"
}

enum BackendDescriptor: Identifiable, Equatable, Sendable {
    static let appleBackendID = "apple:foundation-models"

    case local(OllamaModel)
    case apple
    case clm
    case remote(TypesafeAPIProfile)

    var id: String {
        switch self {
        case .local(let model): "local:\(model.id)"
        case .apple: Self.appleBackendID
        case .clm: CLMRuntime.backendID
        case .remote(let config): "remote:\(config.id)"
        }
    }

    var name: String {
        switch self {
        case .local(let model): "Ollama · \(model.name)"
        case .apple: "Apple · Foundation Models"
        case .clm: "CLM · \(CLMRuntime.displayName)"
        case .remote(let config): "System One · \(config.name)"
        }
    }

    /// Short backend family label shown in accent color in the popover header.
    var typeName: String {
        switch self {
        case .local: "Ollama"
        case .apple: "Apple"
        case .clm: "CLM"
        case .remote: "System One"
        }
    }

    /// Provider label shown next to the family label; remote profiles carry one,
    /// the other backends are their own provider.
    var providerName: String? {
        switch self {
        case .local, .apple, .clm: nil
        case .remote(let config): Self.splitProviderModel(config.name).provider
        }
    }

    /// The model itself, with any provider prefix removed.
    var modelName: String {
        switch self {
        case .local(let model): model.name
        case .apple: "Foundation Models"
        case .clm: CLMRuntime.displayName
        case .remote(let config): Self.splitProviderModel(config.name).model
        }
    }

    /// Splits a profile name like "TypeSafe primary — jev-latest" into provider
    /// and model. Without a recognized separator the whole name is the model.
    static func splitProviderModel(_ name: String) -> (provider: String?, model: String) {
        for separator in [" — ", " – ", " - "] {
            if let range = name.range(of: separator) {
                let provider = String(name[..<range.lowerBound]).trimmingCharacters(in: .whitespaces)
                let model = String(name[range.upperBound...]).trimmingCharacters(in: .whitespaces)
                if !provider.isEmpty, !model.isEmpty { return (provider, model) }
            }
        }
        return (nil, name)
    }

    var needsConnectionTest: Bool {
        switch self {
        case .local, .clm: false
        case .apple, .remote: true
        }
    }
}

@MainActor
final class ServiceController: NSObject, ObservableObject {
    private static let selectedModelKey = "selectedOllamaModel"
    private static let selectedBackendKey = "selectedBackend"

    @Published private(set) var state: ServiceState = .stopped
    @Published private(set) var lastChecked: Date?
    @Published private(set) var models: [OllamaModel] = []
    @Published private(set) var downloadedOllamaModels: [String] = []
    @Published private(set) var questionBatchSizes: [String: Int] = [:]
    @Published private(set) var systemOneModels: Set<String> = []
    @Published private(set) var visionDecisionModels: Set<String> = []
    @Published private(set) var imageEnabledModels: Set<String> = []
    @Published private(set) var providerConfigurationError: String?
    @Published private(set) var apiConfigs: [TypesafeAPIProfile] = []
    @Published private(set) var rateCard: [String: ModelRate] = [:]
    @Published private(set) var serviceModels: [ServiceModelRow] = []
    @Published private(set) var isLoadingProviders = false
    @Published private(set) var isStarting = false
    @Published private(set) var usage: UsageSnapshot?
    @Published var selectedBackendID = "local:granite4.2:latest"
    @Published var launchAtLogin = false

    private var process: Process?
    private var clmProcesses: [Process] = []
    private var gatewayProcess: Process?
    private var overlays: [PopoverAnchor: NSPopover] = [:]
    private var anchorViews: [PopoverAnchor: NSView] = [:]
    private var runningModelID: String?
    private let appleProviderServer = AppleFoundationModelsServer()
    private let root = URL(fileURLWithPath: "/Volumes/Seagate/workspace/jev-mark")
    private let gatewayPort = 8096
    private let localPort = 8097

    var backends: [BackendDescriptor] {
        models.map(BackendDescriptor.local) + [.apple, .clm] + apiConfigs.map(BackendDescriptor.remote)
    }

    var isCLMSelected: Bool { selectedBackendID == CLMRuntime.backendID }
    private var isCLMRunning: Bool { clmProcesses.contains(where: { $0.isRunning }) }

    private var selectedBackend: BackendDescriptor? {
        backends.first(where: { $0.id == selectedBackendID })
    }

    private var selectedModel: OllamaModel? {
        guard case .local(let model) = selectedBackend else { return nil }
        return model
    }

    var isProviderTestSelected: Bool {
        selectedBackend?.needsConnectionTest == true
            || selectedBackendID == BackendDescriptor.appleBackendID
            || selectedBackendID.hasPrefix("remote:")
    }

    /// Backend family for the header line (nil when nothing usable is selected).
    var selectedBackendTypeName: String? {
        if let selectedBackend { return selectedBackend.typeName }
        if selectedBackendID.hasPrefix("remote:") { return "System One" }
        if selectedBackendID == BackendDescriptor.appleBackendID { return "Apple" }
        return nil
    }

    /// Provider label for the header line (nil for local backends or no selection).
    var selectedBackendProvider: String? {
        selectedBackend?.providerName
    }

    /// Model name for the header line.
    var selectedBackendModelName: String {
        if let selectedBackend { return selectedBackend.modelName }
        if selectedBackendID.hasPrefix("remote:") {
            return String(selectedBackendID.dropFirst("remote:".count))
        }
        if selectedBackendID == BackendDescriptor.appleBackendID { return "Foundation Models" }
        return "No backend selected"
    }

    var logURL: URL {
        root.appendingPathComponent(isCLMSelected ? "logs/clm-serve.log" : "logs/jev-server.log")
    }
    private var clmEncoderLogURL: URL { root.appendingPathComponent("logs/clm-encoder.log") }
    private var clmServeLogURL: URL { root.appendingPathComponent("logs/clm-serve.log") }
    var gatewayLogURL: URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Logs/JEV Menu Bar/jev-gateway.log")
    }
    var secureDirectoryURL: URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/JEV Menu Bar/.secure", isDirectory: true)
    }
    var serviceURL: URL { URL(string: "http://127.0.0.1:\(gatewayPort)")! }
    private var healthURL: URL { serviceURL.appendingPathComponent("health") }
    private var settingsURL: URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/JEV Menu Bar/settings.json")
    }

    override init() {
        let defaults = UserDefaults.standard
        selectedBackendID = defaults.string(forKey: Self.selectedBackendKey)
            ?? defaults.string(forKey: Self.selectedModelKey).map { "local:\($0)" }
            ?? "local:granite4.2:latest"
        super.init()
        NotificationCenter.default.addObserver(
            self,
            selector: #selector(applicationWillTerminate),
            name: NSApplication.willTerminateNotification,
            object: nil
        )
        launchAtLogin = LoginItem.isEnabled
        rateCard = RateCardStore.load()
        persistGatewaySelection()
        appleProviderServer.start()
        startGateway()
        refreshProviders()
        Task { await refresh() }
        Task { await trackUsage() }
    }

    /// Refreshes the 12-hour usage pulse periodically so it stays current without
    /// waiting for the popover to open. The read is a cheap indexed SQLite query.
    private func trackUsage() async {
        while !Task.isCancelled {
            await loadUsage()
            try? await Task.sleep(for: .seconds(120))
        }
    }

    private func loadUsage() async {
        let rates = rateCard
        let snapshot = await Task.detached(priority: .utility) { UsageHistory.snapshot(now: Date(), rates: rates) }.value
        usage = snapshot
    }

    /// Persists an edited token rate for a service model; the rate card backs
    /// the cache-savings cost figure on the usage chart.
    func setRate(_ model: String, inputPerMTok: Double, outputPerMTok: Double) {
        var rates = rateCard
        rates[model] = ModelRate(inputPerMTok: max(0, inputPerMTok), outputPerMTok: max(0, outputPerMTok))
        do {
            try RateCardStore.save(rates)
            rateCard = rates
            providerConfigurationError = nil
        } catch {
            providerConfigurationError = "Could not save model rates. Check rates.json and its permissions."
        }
    }

    func selectBackend(_ id: String) {
        selectedBackendID = id
        UserDefaults.standard.set(id, forKey: Self.selectedBackendKey)
        if id.hasPrefix("local:") {
            UserDefaults.standard.set(String(id.dropFirst("local:".count)), forKey: Self.selectedModelKey)
        }
        persistGatewaySelection()
        // Only one heavyweight model stays in memory: leaving CLM stops its servers,
        // and choosing CLM or Apple stops the local llama.cpp model.
        if id != CLMRuntime.backendID, isCLMRunning {
            stopCLM()
        }
        if id == BackendDescriptor.appleBackendID || id == CLMRuntime.backendID, process?.isRunning == true {
            stopLocalModel()
            Task { await refresh() }
        } else if let selectedModel, process?.isRunning == true, selectedModel.id != runningModelID {
            restart()
        } else {
            Task { await refresh() }
        }
    }

    func refreshProviders() {
        isLoadingProviders = true
        Task.detached {
            let downloaded = await OllamaDiscovery.downloadedModels()
            let visionModels = await OllamaDiscovery.visionDecisionModels(downloaded)
            let discovered = OllamaDiscovery.models()
            let remote = await GatewayProviderDiscovery.profiles()
            await MainActor.run {
                self.downloadedOllamaModels = downloaded
                self.visionDecisionModels = visionModels
                do {
                    // Drop selections for models no longer present in Ollama, then
                    // re-read state so the dialog and backend list stay in sync.
                    try OllamaSystemOneStore.pruneUnavailableModels(available: Set(downloaded), in: self.secureDirectoryURL)
                    self.systemOneModels = try OllamaSystemOneStore.checkedModels(in: self.secureDirectoryURL)
                    self.questionBatchSizes = try OllamaSystemOneStore.questionBatchSizes(in: self.secureDirectoryURL)
                    self.imageEnabledModels = try OllamaSystemOneStore.imageEnabledModels(in: self.secureDirectoryURL)
                    self.serviceModels = (try? OllamaSystemOneStore.serviceModelRows(in: self.secureDirectoryURL)) ?? []
                    self.providerConfigurationError = nil
                } catch {
                    self.providerConfigurationError = "Could not read System One model settings. Check typesafe.json."
                }
                self.models = discovered
                self.apiConfigs = remote
                if self.selectedBackend == nil && !self.selectedBackendID.hasPrefix("remote:") {
                    if let first = discovered.first {
                        self.selectBackend("local:\(first.id)")
                    } else if let first = remote.first {
                        self.selectBackend("remote:\(first.id)")
                    }
                }
                self.isLoadingProviders = false
            }
        }
    }

    /// Reloads only the gateway profile list, without flipping `isLoadingProviders`
    /// or running the Ollama CLI discovery — used by Ollama panel toggles.
    func refreshProviderProfiles() {
        Task.detached {
            let remote = await GatewayProviderDiscovery.profiles()
            await MainActor.run {
                self.apiConfigs = remote
                self.serviceModels = (try? OllamaSystemOneStore.serviceModelRows(in: self.secureDirectoryURL)) ?? []
            }
        }
    }

    func setSystemOneModel(_ model: String, enabled: Bool) {
        do {
            let removed = try OllamaSystemOneStore.set(model, enabled: enabled, imageInput: visionDecisionModels.contains(model), in: secureDirectoryURL)
            systemOneModels = try OllamaSystemOneStore.checkedModels(in: secureDirectoryURL)
            questionBatchSizes = try OllamaSystemOneStore.questionBatchSizes(in: secureDirectoryURL)
            providerConfigurationError = nil
            if removed.contains(String(selectedBackendID.dropFirst("remote:".count))) && selectedBackendID.hasPrefix("remote:") {
                selectBackend(models.first.map { "local:" + $0.id } ?? BackendDescriptor.appleBackendID)
            }
            // Toggles sync the gateway profile list without the heavy Ollama CLI
            // discovery pass, so panel controls stay enabled while it runs.
            refreshProviderProfiles()
        } catch {
            providerConfigurationError = "Could not save System One model settings. Check typesafe.json and its permissions."
        }
    }

    func setImageInput(_ enabled: Bool, for model: String) {
        guard !enabled || visionDecisionModels.contains(model) else { return }
        do {
            try OllamaSystemOneStore.setImageInput(enabled, for: model, in: secureDirectoryURL)
            imageEnabledModels = try OllamaSystemOneStore.imageEnabledModels(in: secureDirectoryURL)
            providerConfigurationError = nil
        } catch {
            providerConfigurationError = "Could not save image input settings. Check typesafe.json and its permissions."
        }
    }

    func setQuestionBatchSize(_ size: Int, for model: String) {
        do {
            try OllamaSystemOneStore.setQuestionBatchSize(size, for: model, in: secureDirectoryURL)
            questionBatchSizes = try OllamaSystemOneStore.questionBatchSizes(in: secureDirectoryURL)
            providerConfigurationError = nil
        } catch {
            providerConfigurationError = "Could not save questions per batch. Check typesafe.json and its permissions."
        }
    }

    func refreshModels() { refreshProviders() }

    /// Toggles the anchored overlay popover for a trigger (ollama, logs, backend).
    func toggleOverlay(_ slot: PopoverAnchor) {
        let popover = overlayPopover(for: slot)
        if popover.isShown {
            popover.performClose(nil)
            return
        }
        guard let anchor = anchorViews[slot], anchor.window != nil else { return }
        switch slot {
        case .ollama:
            popover.contentViewController = NSHostingController(rootView: OllamaModelsPanel(controller: self))
        case .logs:
            popover.contentViewController = NSHostingController(rootView: LogsPanel(controller: self))
        case .backend:
            popover.contentViewController = NSHostingController(rootView: BackendListPanel(controller: self))
        }
        popover.behavior = .transient
        popover.show(relativeTo: anchor.bounds, of: anchor, preferredEdge: .minY)
        NSApplication.shared.activate(ignoringOtherApps: true)
    }

    func closeOverlay(_ slot: PopoverAnchor) {
        overlayPopover(for: slot).performClose(nil)
    }

    private func overlayPopover(for slot: PopoverAnchor) -> NSPopover {
        if let popover = overlays[slot] { return popover }
        let popover = NSPopover()
        overlays[slot] = popover
        return popover
    }

    func setAnchor(_ view: NSView, for slot: PopoverAnchor) {
        anchorViews[slot] = view
    }

    func start() {
        guard !isStarting, process?.isRunning != true else {
            Task { await refresh() }
            return
        }
        if isProviderTestSelected {
            testSelectedProvider()
            return
        }
        startGateway()
        if isCLMSelected {
            startCLM()
            return
        }
        guard FileManager.default.fileExists(atPath: root.appendingPathComponent("build/bin/llama-server").path) else {
            state = .failed("Build not found")
            return
        }
        guard let model = selectedModel, FileManager.default.fileExists(atPath: model.blobPath) else {
            state = .failed("Selected Ollama model not found")
            return
        }

        do {
            isStarting = true
            state = .starting
            try FileManager.default.createDirectory(at: logURL.deletingLastPathComponent(), withIntermediateDirectories: true)
            FileManager.default.createFile(atPath: logURL.path, contents: nil)
            let output = try FileHandle(forWritingTo: logURL)
            let task = Process()
            task.executableURL = root.appendingPathComponent("build/bin/llama-server")
            task.arguments = [
                "-m", model.blobPath, "-ngl", "99", "-c", "8192",
                "-b", "512", "-ub", "512", "--decision-seqs", "12",
                "--port", String(localPort), "--host", "127.0.0.1"
            ]
            task.standardOutput = output
            task.standardError = output
            task.terminationHandler = { [weak self] _ in
                Task { @MainActor in
                    guard let self, self.state != .stopped else { return }
                    self.isStarting = false
                    self.state = .failed("Process exited — see log")
                    self.process = nil
                    self.runningModelID = nil
                }
            }
            try task.run()
            process = task
            runningModelID = model.id
            Task { await waitForHealth() }
        } catch {
            isStarting = false
            state = .failed(error.localizedDescription)
        }
    }

    func stop() {
        if isProviderTestSelected {
            state = .configured
            lastChecked = Date()
            return
        }
        if isCLMSelected {
            stopCLM()
            return
        }
        stopLocalModel()
    }

    private func startCLM() {
        guard !isCLMRunning else {
            Task { await refresh() }
            return
        }
        let llamaServer = root.appendingPathComponent("build/bin/llama-server")
        let clmServe = root.appendingPathComponent(".venv-clm/bin/clm-serve")
        guard FileManager.default.isExecutableFile(atPath: llamaServer.path) else {
            state = .failed("Build not found")
            return
        }
        guard FileManager.default.isExecutableFile(atPath: clmServe.path) else {
            state = .failed("CLM runtime not installed (.venv-clm)")
            return
        }
        guard FileManager.default.fileExists(atPath: CLMRuntime.headPath) else {
            state = .failed("CLM head file not found")
            return
        }
        guard let encoderBlob = OllamaDiscovery.blob(for: CLMRuntime.encoderOllamaModel) else {
            state = .failed("Ollama model \(CLMRuntime.encoderOllamaModel) not found")
            return
        }
        do {
            isStarting = true
            state = .starting
            let encoder = try launch(llamaServer, arguments: [
                "-m", encoderBlob, "--alias", "qwen3-8b", "--embeddings", "--pooling", "last",
                "-ngl", "99", "-c", "32768", "-np", "4", "-b", "8192", "-ub", "8192",
                "--port", String(CLMRuntime.encoderPort), "--host", "127.0.0.1"
            ], log: clmEncoderLogURL)
            let server = try launch(clmServe, arguments: [
                "--host", "127.0.0.1", "--port", String(CLMRuntime.serverPort),
                "--emb-url", "http://127.0.0.1:\(CLMRuntime.encoderPort)/v1/embeddings",
                "--emb-model", "qwen3-8b", "--max-tokens", "8192",
                "--ckpt", CLMRuntime.headPath, "--no-download", "--no-ui"
            ], log: clmServeLogURL)
            clmProcesses = [encoder, server]
            Task { await waitForHealth(attempts: 120) }
        } catch {
            stopCLM()
            state = .failed(error.localizedDescription)
        }
    }

    private func launch(_ executable: URL, arguments: [String], log: URL) throws -> Process {
        try FileManager.default.createDirectory(at: log.deletingLastPathComponent(), withIntermediateDirectories: true)
        FileManager.default.createFile(atPath: log.path, contents: nil)
        let output = try FileHandle(forWritingTo: log)
        let task = Process()
        task.executableURL = executable
        task.arguments = arguments
        task.standardOutput = output
        task.standardError = output
        task.terminationHandler = { [weak self] exited in
            Task { @MainActor in
                guard let self, self.clmProcesses.contains(where: { $0 === exited }) else { return }
                self.stopCLM()
                self.state = .failed("CLM process exited — see model log")
            }
        }
        try task.run()
        return task
    }

    private func stopCLM() {
        let running = clmProcesses
        clmProcesses = []
        running.forEach { $0.terminate() }
        isStarting = false
        state = .stopped
    }

    private func stopLocalModel() {
        process?.terminate()
        process = nil
        runningModelID = nil
        isStarting = false
        state = .stopped
    }

    func restart() {
        if isProviderTestSelected {
            testSelectedProvider()
            return
        }
        stop()
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { [weak self] in self?.start() }
    }

    func refresh() async {
        do {
            var request = URLRequest(url: healthURL)
            request.timeoutInterval = 1.5
            let (data, response) = try await URLSession.shared.data(for: request)
            guard (response as? HTTPURLResponse)?.statusCode == 200 else {
                if !isStarting { state = .unhealthy("JEV gateway health check failed") }
                lastChecked = Date()
                return
            }
            let health = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
            guard health?["service"] as? String == "jev-gateway" else {
                if !isStarting { state = .unhealthy("Port 8096 is occupied by a different service") }
                lastChecked = Date()
                return
            }
            switch health?["backend_status"] as? String {
            case "running":
                isStarting = false
                state = .running
            case "configured":
                isStarting = false
                state = .configured
            case "misconfigured":
                isStarting = false
                state = .unhealthy(selectedBackendID.hasPrefix("remote:")
                    ? "Selected System One profile is missing or incomplete"
                    : "Selected JEV backend is not configured")
            case "unavailable":
                isStarting = false
                state = .unhealthy(health?["message"] as? String ?? "Selected provider is unavailable")
            default:
                if !isStarting { state = .stopped }
            }
        } catch {
            if !isStarting {
                isStarting = false
                state = .unhealthy("JEV gateway unavailable — see gateway log")
            }
        }
        lastChecked = Date()
    }

    func testSelectedProvider() {
        guard isProviderTestSelected, !isStarting else { return }
        isStarting = true
        state = .starting
        Task {
            do {
                var request = URLRequest(url: serviceURL.appendingPathComponent("v1/decision"))
                request.httpMethod = "POST"
                request.timeoutInterval = 60
                request.setValue("application/json", forHTTPHeaderField: "Content-Type")
                request.setValue("menubar", forHTTPHeaderField: "X-JEV-Client")
                request.setValue("provider-connectivity", forHTTPHeaderField: "X-JEV-Purpose")
                request.httpBody = try JSONSerialization.data(withJSONObject: GatewayProviderProbe.payload)
                let (data, response) = try await URLSession.shared.data(for: request)
                guard let status = (response as? HTTPURLResponse)?.statusCode,
                      (200..<300).contains(status) else {
                    throw TypesafeAPIError.requestFailed((response as? HTTPURLResponse)?.statusCode ?? 0)
                }
                try GatewayProviderProbe.validate(data)
                isStarting = false
                state = .configured
            } catch {
                isStarting = false
                state = .unhealthy("Selected provider test failed — \(error.localizedDescription)")
            }
            lastChecked = Date()
        }
    }

    private func persistGatewaySelection() {
        do {
            try FileManager.default.createDirectory(
                at: settingsURL.deletingLastPathComponent(),
                withIntermediateDirectories: true
            )
            let data = try JSONSerialization.data(withJSONObject: ["selected_backend": selectedBackendID])
            try data.write(to: settingsURL, options: .atomic)
            try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: settingsURL.path)
        } catch {
            state = .failed("Could not save selected JEV backend")
        }
    }

    private func startGateway() {
        guard gatewayProcess?.isRunning != true else { return }
        let bundleScript = Bundle.main.resourceURL?.appendingPathComponent("jev_gateway.py")
        let workspaceScript = root.appendingPathComponent("scripts/jev_gateway.py")
        let script = [bundleScript, workspaceScript].compactMap { $0 }
            .first(where: { FileManager.default.isReadableFile(atPath: $0.path) })
        let python = [
            "/usr/bin/python3",
            "/opt/homebrew/bin/python3",
            "/usr/local/bin/python3"
        ].first(where: { FileManager.default.isExecutableFile(atPath: $0) })
        NSLog("JEV gateway startup resolved script=%@ interpreter=%@", script?.path ?? "(missing)", python ?? "(missing)")
        guard let script, let python else {
            NSLog("JEV gateway startup stopped: script or Python interpreter was not found")
            state = .failed("JEV gateway runtime not found")
            return
        }
        do {
            try FileManager.default.createDirectory(at: gatewayLogURL.deletingLastPathComponent(), withIntermediateDirectories: true)
            if !FileManager.default.fileExists(atPath: gatewayLogURL.path) {
                FileManager.default.createFile(atPath: gatewayLogURL.path, contents: nil)
            }
            let output = try FileHandle(forWritingTo: gatewayLogURL)
            try output.seekToEnd()
            let task = Process()
            task.executableURL = URL(fileURLWithPath: python)
            task.arguments = [script.path]
            var environment = ProcessInfo.processInfo.environment
            environment["JEV_PROJECT_ROOT"] = root.path
            environment["JEV_SETTINGS_PATH"] = settingsURL.path
            environment["TYPESAFE_SECURE_DIR"] = secureDirectoryURL.path
            environment["JEV_GATEWAY_HOST"] = "0.0.0.0"
            environment["JEV_GATEWAY_PORT"] = String(gatewayPort)
            environment["JEV_LOCAL_PORT"] = String(localPort)
            environment["JEV_GATEWAY_LOG"] = gatewayLogURL.path
            task.environment = environment
            task.standardOutput = output
            task.standardError = output
            task.terminationHandler = { [weak self] process in
                NSLog("JEV gateway process exited with status %d", process.terminationStatus)
                Task { @MainActor in
                    guard let self, self.gatewayProcess != nil else { return }
                    self.gatewayProcess = nil
                    if !self.isStarting {
                        self.state = .unhealthy("JEV gateway stopped — see gateway log")
                    }
                }
            }
            try task.run()
            gatewayProcess = task
            NSLog("JEV gateway process started with PID %d", task.processIdentifier)
            Task { await waitForGateway() }
        } catch {
            NSLog("JEV gateway process launch failed: %@", error.localizedDescription)
            state = .failed("Could not start JEV gateway — \(error.localizedDescription)")
        }
    }

    private func waitForGateway() async {
        for _ in 0..<20 {
            try? await Task.sleep(for: .milliseconds(250))
            await refresh()
            if gatewayProcess?.isRunning != true || state != .unhealthy("JEV gateway unavailable — see gateway log") {
                return
            }
        }
    }

    @objc private func applicationWillTerminate() {
        process?.terminate()
        clmProcesses.forEach { $0.terminate() }
        gatewayProcess?.terminate()
        appleProviderServer.stop()
    }

    func toggleLoginItem() {
        do {
            try LoginItem.setEnabled(!launchAtLogin)
            launchAtLogin = LoginItem.isEnabled
        } catch {
            state = .failed("Login item: \(error.localizedDescription)")
        }
    }

    private func waitForHealth(attempts: Int = 30) async {
        for _ in 0..<attempts {
            try? await Task.sleep(for: .milliseconds(500))
            await refresh()
            if state == .running { return }
        }
        if isStarting {
            isStarting = false
            state = .unhealthy("Started, health check timed out")
        }
    }
}

enum OllamaDiscovery {
    private struct Tags: Decodable {
        struct Model: Decodable { let name: String }
        let models: [Model]
    }

    static func downloadedModels() async -> [String] {
        do {
            var request = URLRequest(url: URL(string: "http://127.0.0.1:11434/api/tags")!)
            request.timeoutInterval = 3
            let (data, response) = try await URLSession.shared.data(for: request)
            guard (response as? HTTPURLResponse)?.statusCode == 200 else { return listNames() }
            return Array(Set(try JSONDecoder().decode(Tags.self, from: data).models.map(\.name))).sorted()
        } catch { return listNames() }
    }

    static func visionDecisionModels(_ models: [String]) async -> Set<String> {
        struct Show: Decodable { let capabilities: [String]? }
        var result: Set<String> = []
        for model in models {
            do {
                var request = URLRequest(url: URL(string: "http://127.0.0.1:11434/api/show")!)
                request.httpMethod = "POST"
                request.setValue("application/json", forHTTPHeaderField: "Content-Type")
                request.httpBody = try JSONEncoder().encode(["model": model])
                request.timeoutInterval = 3
                let (data, response) = try await URLSession.shared.data(for: request)
                guard (response as? HTTPURLResponse)?.statusCode == 200 else { continue }
                let capabilities = try JSONDecoder().decode(Show.self, from: data).capabilities ?? []
                if capabilities.contains("decision") && capabilities.contains("vision") { result.insert(model) }
            } catch { continue }
        }
        return result
    }

    private static func listNames() -> [String] {
        guard let output = run(["list"]) else { return [] }
        return output.split(separator: "\n").dropFirst().compactMap {
            $0.split(whereSeparator: { $0 == " " || $0 == "\t" }).first.map(String.init)
        }.sorted()
    }

    static func models() -> [OllamaModel] {
        guard let output = run(["list"]) else { return [] }
        return output.split(separator: "\n").dropFirst().compactMap { line in
            let fields = line.split(whereSeparator: { $0 == " " || $0 == "\t" })
            guard let name = fields.first, let blob = firstBlob(for: String(name)) else { return nil }
            return OllamaModel(id: String(name), name: String(name), blobPath: blob)
        }
    }

    static func blob(for name: String) -> String? { firstBlob(for: name) }

    private static func firstBlob(for name: String) -> String? {
        guard let output = run(["show", name, "--modelfile"]) else { return nil }
        for line in output.split(separator: "\n") {
            let text = line.trimmingCharacters(in: .whitespacesAndNewlines)
            guard text.hasPrefix("FROM ") else { continue }
            let path = String(text.dropFirst(5))
            if FileManager.default.fileExists(atPath: path) { return path }
        }
        return nil
    }

    private static func run(_ arguments: [String]) -> String? {
        let task = Process()
        let pipe = Pipe()
        guard let executable = ["/usr/local/bin/ollama", "/opt/homebrew/bin/ollama", "/usr/bin/ollama"]
            .first(where: { FileManager.default.isExecutableFile(atPath: $0) }) else { return nil }
        task.executableURL = URL(fileURLWithPath: executable)
        task.arguments = arguments
        task.standardOutput = pipe
        task.standardError = FileHandle.nullDevice
        do {
            try task.run()
            task.waitUntilExit()
            guard task.terminationStatus == 0 else { return nil }
            return String(data: pipe.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8)
        } catch {
            return nil
        }
    }
}

enum LoginItem {
    static let label = "com.codex.jev.menubar"
    static var plistURL: URL { FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/LaunchAgents/\(label).plist") }
    static var isEnabled: Bool { FileManager.default.fileExists(atPath: plistURL.path) }

    static func setEnabled(_ enabled: Bool) throws {
        if enabled {
            let executable = Bundle.main.executablePath ?? ""
            let plist: [String: Any] = [
                "Label": label,
                "ProgramArguments": [executable],
                "RunAtLoad": true,
                "KeepAlive": false,
                "ProcessType": "Interactive"
            ]
            let directory = plistURL.deletingLastPathComponent()
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
            (plist as NSDictionary).write(to: plistURL, atomically: true)
            try launchctl(["bootstrap", "gui/\(getuid())", plistURL.path])
        } else {
            try? launchctl(["bootout", "gui/\(getuid())", plistURL.path])
            try? FileManager.default.removeItem(at: plistURL)
        }
    }

    private static func launchctl(_ arguments: [String]) throws {
        let task = Process()
        task.executableURL = URL(fileURLWithPath: "/bin/launchctl")
        task.arguments = arguments
        try task.run()
        task.waitUntilExit()
        if task.terminationStatus != 0 { throw NSError(domain: "launchctl", code: Int(task.terminationStatus)) }
    }
}

/// Which anchored overlay popover a trigger controls.
enum PopoverAnchor {
    case ollama
    case logs
    case backend
}

/// Invisible view anchoring an overlay popover to its trigger label.
struct PopoverAnchorView: NSViewRepresentable {
    let controller: ServiceController
    let slot: PopoverAnchor

    func makeNSView(context: Context) -> NSView {
        let view = NSView()
        controller.setAnchor(view, for: slot)
        return view
    }

    func updateNSView(_ nsView: NSView, context: Context) {
        controller.setAnchor(nsView, for: slot)
    }
}

struct ContentView: View {
    @ObservedObject var controller: ServiceController

    /// One explicit font for the backend line: regular weight, monospaced, no bold anywhere.
    fileprivate static let headerLineFont = Font.system(size: 11, weight: .regular, design: .monospaced)

    /// Inline backend selector: model text plus an accent chevron. Clicking pops
    /// up a native menu at the cursor with sections and a selection checkmark.
    private var backendMenu: some View {
        Button {
            controller.toggleOverlay(.backend)
        } label: {
            HStack(alignment: .firstTextBaseline, spacing: 3) {
                Text(controller.selectedBackendModelName)
                    .font(Self.headerLineFont)
                    .multilineTextAlignment(.leading)
                Image(systemName: "chevron.down")
                    .font(.system(size: 8, weight: .regular))
                    .foregroundColor(.accentColor)
            }
            .background(PopoverAnchorView(controller: controller, slot: .backend))
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .fixedSize(horizontal: false, vertical: true)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(alignment: .top, spacing: 10) {
                Circle().fill(controller.state.color)
                    .frame(width: 10, height: 10)
                    .padding(.top, 3)
                VStack(alignment: .leading, spacing: 2) {
                    Text("JEV Decision Service")
                        .font(.headline)
                        .padding(.bottom, 4)
                    if controller.state.errorMessage == nil, controller.state != .configured {
                        Text(controller.state.label).font(.caption).foregroundStyle(.secondary)
                    }
                    HStack(alignment: .firstTextBaseline, spacing: 4) {
                        Text(controller.selectedBackendTypeName ?? "")
                            .font(Self.headerLineFont).foregroundStyle(.secondary)
                        if let provider = controller.selectedBackendProvider {
                            Text("•").font(Self.headerLineFont).foregroundStyle(.secondary)
                            Text(provider).font(Self.headerLineFont).foregroundStyle(.secondary)
                        }
                        Spacer(minLength: 8)
                        if controller.state == .configured {
                            Button("Test") { controller.testSelectedProvider() }
                                .buttonStyle(.plain).font(Self.headerLineFont)
                                .foregroundColor(.accentColor)
                        }
                    }
                    HStack(alignment: .firstTextBaseline, spacing: 4) {
                        if controller.isLoadingProviders {
                            ProgressView().controlSize(.small)
                            Text("Loading local models and API configs…")
                                .font(.caption).foregroundStyle(.secondary)
                        } else if controller.backends.isEmpty {
                            Text("No compatible providers found")
                                .font(.caption).foregroundStyle(.secondary)
                        } else {
                            backendMenu
                        }
                        Spacer(minLength: 8)
                        Button(String(controller.serviceURL.port ?? 8096)) {
                            NSWorkspace.shared.open(controller.serviceURL)
                        }
                        .buttonStyle(.plain).font(Self.headerLineFont)
                        .foregroundColor(.accentColor)
                    }
                    if let message = controller.state.errorMessage {
                        Text(message)
                            .font(.caption)
                            .foregroundStyle(.orange)
                            .multilineTextAlignment(.leading)
                    }
                }
            }
            Divider()
            if let checked = controller.lastChecked {
                Text("Last health check \(checked.formatted(date: .omitted, time: .shortened))")
                    .font(.caption2).foregroundStyle(.secondary)
            }
            UsagePulseView(snapshot: controller.usage)
            Divider()
            if controller.isStarting {
                HStack(spacing: 8) {
                    ProgressView().controlSize(.small)
                    Text(controller.isProviderTestSelected
                        ? "Sending a decision through the JEV gateway…"
                        : "Loading model into memory — this can take a few seconds.")
                        .font(.caption).foregroundStyle(.orange)
                }
            }
            HStack {
                Button {
                    controller.toggleOverlay(.ollama)
                } label: {
                    HStack(spacing: 3) {
                        Text("Models")
                            .font(.caption2)
                            .foregroundColor(.primary)
                        Image(systemName: "chevron.down")
                            .font(.system(size: 7, weight: .regular))
                            .foregroundColor(.accentColor)
                    }
                    .background(PopoverAnchorView(controller: controller, slot: .ollama))
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
            }
            if let error = controller.providerConfigurationError {
                Text(error).font(.caption2).foregroundStyle(.red)
            }
            HStack {
                Toggle("Start at login", isOn: Binding(get: { controller.launchAtLogin }, set: { _ in controller.toggleLoginItem() }))
                    .font(.caption)
                Spacer(minLength: 8)
                Button {
                    controller.toggleOverlay(.logs)
                } label: {
                    HStack(spacing: 3) {
                        Text("Logs")
                            .font(.caption2)
                            .foregroundColor(.primary)
                        Image(systemName: "chevron.down")
                            .font(.system(size: 7, weight: .regular))
                            .foregroundColor(.accentColor)
                    }
                    .background(PopoverAnchorView(controller: controller, slot: .logs))
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                Spacer(minLength: 8)
                if !controller.isStarting {
                    // Remote backends report "configured" once the gateway is serving;
                    // local models report "running" once the model is loaded. Both are up.
                    if controller.state == .running || controller.state == .configured {
                        Button("Shut Down Services") { NSApplication.shared.terminate(nil) }
                            .buttonStyle(.link).font(.caption2)
                    } else {
                        Button("Start Services") { controller.start() }
                            .buttonStyle(.link).font(.caption2)
                    }
                }
            }
        }
        .padding(16)
        .frame(width: 320)
        .task { await controller.refresh() }
    }
}

/// Overlay list for the Logs trigger: auths directory, gateway and model logs.
struct LogsPanel: View {
    @ObservedObject var controller: ServiceController

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            logLink("Auths", url: controller.secureDirectoryURL)
            logLink("Gateway log", url: controller.gatewayLogURL)
            logLink("Model log", url: controller.logURL)
        }
        .padding(10)
        .frame(width: 190, alignment: .leading)
    }

    private func logLink(_ title: String, url: URL) -> some View {
        Button {
            controller.closeOverlay(.logs)
            NSWorkspace.shared.open(url)
        } label: {
            Text(title)
                .font(.caption2)
                .foregroundColor(.primary)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.vertical, 4)
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }
}

/// Overlay list for the backend selector: sectioned model list with a checkmark
/// on the current selection, matching the old dropdown's contents.
struct BackendListPanel: View {
    @ObservedObject var controller: ServiceController

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 2) {
                if !controller.models.isEmpty {
                    sectionHeader("Local Ollama")
                    ForEach(controller.models) { model in
                        row("local:\(model.id)", label: model.name)
                    }
                }
                sectionHeader("On-device Apple")
                row(BackendDescriptor.appleBackendID, label: "Foundation Models")
                sectionHeader("Contrastive (CLM)")
                row(CLMRuntime.backendID, label: CLMRuntime.displayName)
                if !controller.apiConfigs.isEmpty {
                    sectionHeader("System One API")
                    ForEach(controller.apiConfigs) { config in
                        row("remote:\(config.id)", label: config.name)
                    }
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(8)
        }
        .frame(width: 280, height: 300)
    }

    private func sectionHeader(_ title: String) -> some View {
        Text(title)
            .font(.caption2).foregroundStyle(.secondary)
            .padding(.top, 4)
            .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func row(_ id: String, label: String) -> some View {
        Button {
            controller.selectBackend(id)
            controller.closeOverlay(.backend)
        } label: {
            HStack(spacing: 6) {
                Image(systemName: "checkmark")
                    .font(.system(size: 9, weight: .semibold))
                    .foregroundColor(.accentColor)
                    .opacity(controller.selectedBackendID == id ? 1 : 0)
                    .frame(width: 10)
                Text(label)
                    .font(.caption)
                    .foregroundColor(.primary)
                    .lineLimit(1)
                Spacer(minLength: 0)
            }
            .padding(.vertical, 3)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }
}

/// Configuration dialog for decision models: Ollama rows carry model selection,
/// image input and batch size; hosted service-model rows carry the editable
/// token rate card that backs the cache-savings figures on the usage chart.
struct OllamaModelsPanel: View {
    @ObservedObject var controller: ServiceController

    private static let batchColumnWidth: CGFloat = 72
    private static let imageColumnWidth: CGFloat = 64
    private static let rateColumnWidth: CGFloat = 76

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            if controller.downloadedOllamaModels.isEmpty && controller.serviceModels.isEmpty {
                Text("No decision models found. Start Ollama or add a System One profile, then refresh.")
                    .font(.caption).foregroundStyle(.secondary)
            } else {
                ScrollView {
                    VStack(alignment: .leading, spacing: 8) {
                        if !controller.downloadedOllamaModels.isEmpty {
                            sectionHeader("Ollama", trailing: "Free")
                            HStack {
                                Text("Model").font(.caption2).foregroundStyle(.secondary)
                                Spacer()
                                Text("Batch").font(.caption2).foregroundStyle(.secondary)
                                    .frame(width: Self.batchColumnWidth)
                                Text("Image Input").font(.caption2).foregroundStyle(.secondary)
                                    .frame(width: Self.imageColumnWidth)
                            }
                            ForEach(controller.downloadedOllamaModels, id: \.self) { model in
                                HStack(spacing: 8) {
                                    Toggle(model, isOn: Binding(
                                        get: { controller.systemOneModels.contains(model) },
                                        set: { controller.setSystemOneModel(model, enabled: $0) }
                                    ))
                                    .toggleStyle(.checkbox)
                                    .disabled(controller.isLoadingProviders)
                                    Spacer(minLength: 8)
                                    Group {
                                        if controller.systemOneModels.contains(model) {
                                            let questionBatchSize = Binding(
                                                get: { controller.questionBatchSizes[model] ?? 64 },
                                                set: { controller.setQuestionBatchSize($0, for: model) }
                                            )
                                            HStack(spacing: 2) {
                                                TextField("Questions", value: questionBatchSize, format: .number)
                                                    .textFieldStyle(.roundedBorder)
                                                    .frame(width: 44)
                                                    .multilineTextAlignment(.center)
                                                    .disabled(controller.isLoadingProviders)
                                                Stepper("", value: questionBatchSize,
                                                        in: 1...OllamaSystemOneStore.maximumQuestionBatchSize)
                                                    .labelsHidden()
                                                    .disabled(controller.isLoadingProviders)
                                            }
                                        } else {
                                            Text("\(controller.questionBatchSizes[model] ?? 64)")
                                                .font(.caption).foregroundStyle(.secondary)
                                        }
                                    }
                                    .frame(width: Self.batchColumnWidth)
                                    // The border lives in a ZStack (not a conditional Group) so it
                                    // renders for every row; the tick appears only for selected
                                    // models that Ollama reports as image-capable.
                                    ZStack {
                                        RoundedRectangle(cornerRadius: 3.5)
                                            .stroke(Color.secondary.opacity(0.45), lineWidth: 1)
                                        if controller.systemOneModels.contains(model),
                                           controller.visionDecisionModels.contains(model) {
                                            Image(systemName: "checkmark")
                                                .font(.system(size: 8, weight: .semibold))
                                                .foregroundColor(.primary)
                                        }
                                    }
                                    .frame(width: 16, height: 16)
                                    .frame(width: Self.imageColumnWidth)
                                }
                            }
                        }
                        if !controller.serviceModels.isEmpty {
                            sectionHeader("Service models", trailing: nil)
                            HStack {
                                Text("Model").font(.caption2).foregroundStyle(.secondary)
                                Spacer()
                                Text("In $/M").font(.caption2).foregroundStyle(.secondary)
                                    .frame(width: Self.rateColumnWidth)
                                Text("Out $/M").font(.caption2).foregroundStyle(.secondary)
                                    .frame(width: Self.rateColumnWidth)
                            }
                            ForEach(controller.serviceModels) { entry in
                                HStack(spacing: 8) {
                                    VStack(alignment: .leading, spacing: 1) {
                                        Text(entry.model).font(.caption)
                                        Text(entry.name).font(.caption2).foregroundStyle(.secondary)
                                    }
                                    Spacer(minLength: 8)
                                    rateField(model: entry.model, keyPath: \.inputPerMTok, placeholder: "In")
                                    rateField(model: entry.model, keyPath: \.outputPerMTok, placeholder: "Out")
                                }
                            }
                        }
                    }.frame(maxWidth: .infinity, alignment: .leading)
                }
            }
            if let error = controller.providerConfigurationError {
                Text(error).font(.caption2).foregroundStyle(.red)
            }
            HStack {
                Button("Refresh") { controller.refreshProviders() }
                    .buttonStyle(.link).font(.caption2)
                    .disabled(controller.isLoadingProviders)
                Spacer()
                Text("Batch range: 1 - 512   |   Ollama default: 64")
                    .font(.caption2)
                    .foregroundColor(.accentColor)
            }
        }
        .padding(14)
        .frame(width: 560, height: 480)
    }

    private func sectionHeader(_ title: String, trailing: String?) -> some View {
        HStack {
            Text(title).font(.caption2.weight(.semibold)).foregroundColor(.accentColor)
            Spacer()
            if let trailing {
                Text(trailing).font(.caption2).foregroundStyle(.secondary)
            }
        }
    }

    private func rateField(model: String, keyPath: WritableKeyPath<ModelRate, Double>,
                           placeholder: String) -> some View {
        let rate = Binding(
            get: { controller.rateCard[model]?[keyPath: keyPath] ?? 0 },
            set: {
                var updated = controller.rateCard[model] ?? ModelRate(inputPerMTok: 0, outputPerMTok: 0)
                updated[keyPath: keyPath] = max(0, $0)
                controller.setRate(model, inputPerMTok: updated.inputPerMTok, outputPerMTok: updated.outputPerMTok)
            }
        )
        return TextField(placeholder, value: rate, format: .number)
            .textFieldStyle(.roundedBorder)
            .frame(width: Self.rateColumnWidth)
            .multilineTextAlignment(.center)
            .font(.caption)
    }
}

@main
struct JevMenuBarApp: App {
    @StateObject private var controller = ServiceController()

    var body: some Scene {
        MenuBarExtra {
            ContentView(controller: controller)
        } label: {
            Image(systemName: "square.grid.2x2")
                .symbolRenderingMode(.hierarchical)
        }
        .menuBarExtraStyle(.window)
    }
}
