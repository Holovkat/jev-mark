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
}

struct OllamaModel: Identifiable, Equatable, Sendable {
    let id: String
    let name: String
    let blobPath: String
}

/// Contrastive Language Model: a Qwen3-8B last-token embedding server (llama.cpp) plus
/// `clm-serve`, which scores candidates with the CLM projection heads.
enum CLMRuntime {
    static let backendID = "clm:v0.1-8b"
    static let displayName = "CLM v0.1 8B"
    static let encoderOllamaModel = "qwen3:8b-q8_0"
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
        case .remote(let config): "TypeSafe · \(config.name)"
        }
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
    @Published private(set) var apiConfigs: [TypesafeAPIProfile] = []
    @Published private(set) var isLoadingProviders = false
    @Published private(set) var isStarting = false
    @Published var selectedBackendID = "local:granite4.2:latest"
    @Published var launchAtLogin = false

    private var process: Process?
    private var clmProcesses: [Process] = []
    private var gatewayProcess: Process?
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

    var selectedBackendName: String {
        if let selectedBackend { return selectedBackend.name }
        if selectedBackendID.hasPrefix("remote:") {
            return "TypeSafe · " + String(selectedBackendID.dropFirst("remote:".count))
        }
        if selectedBackendID == BackendDescriptor.appleBackendID {
            return "Apple · Foundation Models"
        }
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
        persistGatewaySelection()
        appleProviderServer.start()
        startGateway()
        refreshProviders()
        Task { await refresh() }
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
            let discovered = OllamaDiscovery.models()
            let remote = await GatewayProviderDiscovery.profiles()
            await MainActor.run {
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

    func refreshModels() { refreshProviders() }

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
                    ? "Selected TypeSafe profile is missing or incomplete"
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
                request.httpBody = try JSONSerialization.data(withJSONObject: [
                    "instructions": "Choose connected when the selected JEV provider can process a bounded decision.",
                    "schema": [
                        "connectivity": [
                            "type": "enum",
                            "choices": ["connected", "unavailable"],
                            "description": "Whether the selected JEV provider processed this request."
                        ]
                    ],
                    "contexts": ["JEV Menu Bar connectivity check."]
                ])
                let (data, response) = try await URLSession.shared.data(for: request)
                guard let status = (response as? HTTPURLResponse)?.statusCode,
                      (200..<300).contains(status) else {
                    throw TypesafeAPIError.requestFailed((response as? HTTPURLResponse)?.statusCode ?? 0)
                }
                guard let body = try JSONSerialization.jsonObject(with: data) as? [String: Any],
                      let results = body["results"] as? [[String: Any]],
                      let decision = results.first?["decision"] as? [String: Any],
                      decision["connectivity"] as? String == "connected" else {
                    throw TypesafeAPIError.invalidResponse
                }
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

struct ContentView: View {
    @ObservedObject var controller: ServiceController

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(spacing: 10) {
                Circle().fill(controller.state.color).frame(width: 10, height: 10)
                VStack(alignment: .leading, spacing: 2) {
                    Text("JEV Decision Service")
                        .font(.headline)
                    Text(controller.state.label).font(.caption).foregroundStyle(.secondary)
                }
                Spacer()
                Link("8096", destination: controller.serviceURL)
                    .font(.caption.monospaced())
            }
            Text("Routes to \(controller.selectedBackendName)")
                .font(.caption2).foregroundStyle(.secondary)
            Divider()
            HStack(spacing: 8) {
                if controller.isProviderTestSelected {
                    if controller.isStarting {
                        Button("Testing selected provider…") { }
                            .disabled(true)
                    } else {
                        Button("Test selected provider") { controller.testSelectedProvider() }
                    }
                } else {
                    if controller.isStarting {
                        Button("Warming up…") { }
                            .disabled(true)
                    } else if controller.state == .running {
                        Button("Stop") { controller.stop() }
                        Button("Restart") { controller.restart() }
                    } else {
                        Button("Start") { controller.start() }
                    }
                }
            }
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
                Image(systemName: "cpu").foregroundStyle(.secondary)
                if controller.isLoadingProviders {
                    ProgressView().controlSize(.small)
                    Text("Loading local models and API configs…").font(.caption).foregroundStyle(.secondary)
                } else if controller.backends.isEmpty {
                    Text("No compatible providers found")
                        .font(.caption).foregroundStyle(.secondary)
                } else {
                    Picker("Backend", selection: Binding(
                        get: { controller.selectedBackendID },
                        set: { controller.selectBackend($0) }
                    )) {
                        if !controller.models.isEmpty {
                            Section("Local Ollama") {
                                ForEach(controller.models) { model in
                                    Text(model.name).tag("local:\(model.id)")
                                }
                            }
                        }
                        Section("On-device Apple") {
                            Text("Foundation Models").tag(BackendDescriptor.appleBackendID)
                        }
                        Section("Contrastive (CLM)") {
                            Text(CLMRuntime.displayName).tag(CLMRuntime.backendID)
                        }
                        if !controller.apiConfigs.isEmpty {
                            Section("TypeSafe API") {
                                ForEach(controller.apiConfigs) { config in
                                    Text(config.name).tag("remote:\(config.id)")
                                }
                            }
                        }
                    }
                    .labelsHidden()
                    .font(.caption)
                }
                Spacer()
                Button("Gateway log") { NSWorkspace.shared.open(controller.gatewayLogURL) }.buttonStyle(.link)
                Button("Model log") { NSWorkspace.shared.open(controller.logURL) }.buttonStyle(.link)
            }
            Text("Callers always use the local JEV endpoint; provider selection stays behind this service.")
                .font(.caption2).foregroundStyle(.secondary)
            HStack(spacing: 10) {
                Button("Refresh providers") { controller.refreshProviders() }
                    .buttonStyle(.link).font(.caption2).disabled(controller.isLoadingProviders)
                Button("Open .secure") { NSWorkspace.shared.open(controller.secureDirectoryURL) }
                    .buttonStyle(.link).font(.caption2)
            }
            Toggle("Start at login", isOn: Binding(get: { controller.launchAtLogin }, set: { _ in controller.toggleLoginItem() }))
                .font(.caption)
            if let checked = controller.lastChecked {
                Text("Last health check \(checked.formatted(date: .omitted, time: .shortened))")
                    .font(.caption2).foregroundStyle(.secondary)
            }
            Divider()
            Button("Quit JEV Menu Bar") { NSApplication.shared.terminate(nil) }
                .buttonStyle(.plain).foregroundStyle(.secondary).font(.caption)
        }
        .padding(16)
        .frame(width: 320)
        .task { await controller.refresh() }
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
