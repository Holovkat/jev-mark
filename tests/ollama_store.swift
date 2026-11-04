import Foundation

@main
struct OllamaStoreChecks {
    static func check(_ condition: Bool, _ message: String = "") { precondition(condition, message) }

    static func main() throws {
        let manager = FileManager.default
        let directory = manager.temporaryDirectory.appendingPathComponent("jev-ollama-store-" + UUID().uuidString)
        defer { try? manager.removeItem(at: directory) }
        try manager.createDirectory(at: directory, withIntermediateDirectories: true)
        let foreign: [String: Any] = ["id": "hosted", "model": "d1:3b", "base_url": "https://example.invalid/v1/systemone", "api_key": "fixture-key"]
        let initial: [String: Any] = ["metadata": ["keep": true], "configs": [foreign]]
        let file = directory.appendingPathComponent("typesafe.json")
        try JSONSerialization.data(withJSONObject: initial).write(to: file)
        _ = try OllamaSystemOneStore.set("d1:3b", enabled: true, imageInput: true, in: directory)
        check(try OllamaSystemOneStore.imageEnabledModels(in: directory) == ["d1:3b"])
        _ = try OllamaSystemOneStore.set("d1:3b", enabled: true, in: directory)
        check(try OllamaSystemOneStore.imageEnabledModels(in: directory) == ["d1:3b"], "Existing image choice must survive refresh/rechecking")
        try OllamaSystemOneStore.setQuestionBatchSize(16, for: "d1:3b", in: directory)
        try OllamaSystemOneStore.setImageInput(false, for: "d1:3b", in: directory)
        check(try OllamaSystemOneStore.imageEnabledModels(in: directory).isEmpty)
        check(try OllamaSystemOneStore.questionBatchSizes(in: directory)["d1:3b"] == 16)
        try OllamaSystemOneStore.setQuestionBatchSize(512, for: "d1:3b", in: directory)
        check(try OllamaSystemOneStore.questionBatchSizes(in: directory)["d1:3b"] == 512)
        try OllamaSystemOneStore.setQuestionBatchSize(999, for: "d1:3b", in: directory)
        check(try OllamaSystemOneStore.questionBatchSizes(in: directory)["d1:3b"] == 512)
        try OllamaSystemOneStore.setQuestionBatchSize(0, for: "d1:3b", in: directory)
        check(try OllamaSystemOneStore.questionBatchSizes(in: directory)["d1:3b"] == 1)
        try OllamaSystemOneStore.setImageInput(true, for: "d1:3b", in: directory)
        let root = try JSONSerialization.jsonObject(with: Data(contentsOf: file)) as! [String: Any]
        let rows = root["configs"] as! [[String: Any]]
        check((root["metadata"] as! [String: Bool])["keep"] == true)
        check(NSDictionary(dictionary: rows.first { $0["id"] as? String == "hosted" }!) == NSDictionary(dictionary: foreign))
        let before = try Data(contentsOf: file)
        do {
            try OllamaSystemOneStore.setImageInput(true, for: "missing-model", in: directory)
            fatalError("Missing profile should be rejected")
        } catch OllamaSystemOneStore.StoreError.invalidConfig { }
        check(try Data(contentsOf: file) == before)
        let removed = try OllamaSystemOneStore.set("d1:3b", enabled: false, in: directory)
        check(removed.count == 1)
        check(try OllamaSystemOneStore.checkedModels(in: directory).isEmpty)
        _ = try OllamaSystemOneStore.set("d1:3b", enabled: true, in: directory)
        _ = try OllamaSystemOneStore.set("clef-flash:9b", enabled: true, in: directory)
        try OllamaSystemOneStore.pruneUnavailableModels(available: ["d1:3b"], in: directory)
        check(try OllamaSystemOneStore.checkedModels(in: directory) == ["d1:3b"], "Prune must drop selections whose model is no longer downloaded")
        let prunedRows = (try JSONSerialization.jsonObject(with: Data(contentsOf: file)) as! [String: Any])["configs"] as! [[String: Any]]
        check(prunedRows.contains { $0["id"] as? String == "hosted" }, "Prune must keep unrelated profiles")
        try OllamaSystemOneStore.pruneUnavailableModels(available: ["d1:3b"], in: directory)
        check(try OllamaSystemOneStore.checkedModels(in: directory) == ["d1:3b"], "Prune with nothing to remove must not rewrite selections")
        let permissions = try manager.attributesOfItem(atPath: file.path)[.posixPermissions] as! NSNumber
        check(permissions.intValue == 0o600)
        print("Ollama store checks passed: image toggle, recheck, batch persistence, unrelated profiles, failed write isolation, removal and permissions")
    }
}
