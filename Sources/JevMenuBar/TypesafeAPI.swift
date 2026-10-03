import Foundation

struct TypesafeAPIProfile: Decodable, Identifiable, Equatable, Hashable, Sendable {
    let id: String
    let name: String
}

private struct GatewayProviderResponse: Decodable {
    let providers: [TypesafeAPIProfile]
}

enum GatewayProviderDiscovery {
    static func profiles() async -> [TypesafeAPIProfile] {
        let url = URL(string: "http://127.0.0.1:8096/providers")!
        for _ in 0..<20 {
            do {
                var request = URLRequest(url: url)
                request.timeoutInterval = 1
                let (data, response) = try await URLSession.shared.data(for: request)
                guard (response as? HTTPURLResponse)?.statusCode == 200 else {
                    try? await Task.sleep(for: .milliseconds(150))
                    continue
                }
                return try JSONDecoder().decode(GatewayProviderResponse.self, from: data).providers
            } catch {
                try? await Task.sleep(for: .milliseconds(150))
            }
        }
        return []
    }
}

enum TypesafeAPIError: LocalizedError {
    case invalidResponse
    case requestFailed(Int)

    var errorDescription: String? {
        switch self {
        case .invalidResponse: "The JEV gateway returned an unreadable response"
        case .requestFailed(let status): "The JEV gateway returned HTTP " + String(status)
        }
    }
}

/// Updates only loopback Ollama profiles while preserving every other config value.
enum OllamaSystemOneStore {
    private static func load(_ directory: URL) throws -> (Any, [[String: Any]]) {
        let file = directory.appendingPathComponent("typesafe.json")
        guard FileManager.default.fileExists(atPath: file.path) else { return (["configs": []], []) }
        let root = try JSONSerialization.jsonObject(with: Data(contentsOf: file))
        if let object = root as? [String: Any], let rows = object["configs"] as? [[String: Any]] {
            return (object, rows)
        }
        if let rows = root as? [[String: Any]] { return (rows, rows) }
        throw StoreError.invalidConfig
    }

    private static func isOllama(_ row: [String: Any], model: String? = nil) -> Bool {
        let endpoint = ["base_url", "baseURL", "endpoint", "url"].compactMap { row[$0] as? String }.first
        guard let endpoint, let url = URL(string: endpoint),
              ["http", "https"].contains(url.scheme?.lowercased() ?? ""),
              ["127.0.0.1", "localhost", "::1", "[::1]"].contains(url.host?.lowercased() ?? ""),
              (url.port ?? (url.scheme?.lowercased() == "https" ? 443 : 80)) == 11434 else { return false }
        let path = url.path.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        guard ["", "v1", "v1/systemone"].contains(path) else { return false }
        return model == nil || row["model"] as? String == model
    }

    static func checkedModels(in directory: URL) throws -> Set<String> {
        let (_, rows) = try load(directory)
        return Set(rows.filter { isOllama($0) }.compactMap { $0["model"] as? String })
    }

    /// Returns IDs removed by the edit, including legacy profile IDs such as nimble.
    static func set(_ model: String, enabled: Bool, in directory: URL) throws -> Set<String> {
        let (root, loadedRows) = try load(directory)
        var rows = loadedRows
        // Gateway IDs otherwise depend on row position. Pin fallback IDs before removing rows.
        for index in rows.indices {
            let value = rows[index]["id"]
            if value == nil || value is NSNull || (value as? String) == ""
                || (value as? NSNumber)?.doubleValue == 0 {
                rows[index]["id"] = "typesafe.json-\(index + 1)"
            }
        }
        let matching = rows.enumerated().filter { isOllama($0.element, model: model) }
        let removed = Set(matching.map { index, row in
            String(describing: row["id"] ?? "typesafe.json-\(index + 1)")
                .trimmingCharacters(in: .whitespacesAndNewlines)
        })
        if enabled && !matching.isEmpty { return [] }
        rows.removeAll { isOllama($0, model: model) }
        if enabled {
            let id = "ollama-systemone-" + model.utf8.map { String(format: "%02x", $0) }.joined()
            guard !rows.contains(where: { String(describing: $0["id"] ?? "").trimmingCharacters(in: .whitespacesAndNewlines) == id }) else { throw StoreError.idCollision }
            rows.append(["id": id, "name": "Ollama · " + model,
                         "base_url": "http://127.0.0.1:11434/v1/systemone",
                         "api_key": "ollama", "model": model])
        }
        try save(root: root, rows: rows, in: directory)
        return enabled ? [] : removed
    }

    static func questionBatchSizes(in directory: URL) throws -> [String: Int] {
        let (_, rows) = try load(directory)
        var sizes: [String: Int] = [:]
        for row in rows where isOllama(row) {
            guard let model = row["model"] as? String, sizes[model] == nil else { continue }
            sizes[model] = min(64, max(1, (row["workbench_question_batch_size"] as? NSNumber)?.intValue ?? 64))
        }
        return sizes
    }

    static func setQuestionBatchSize(_ size: Int, for model: String, in directory: URL) throws {
        let (root, loadedRows) = try load(directory)
        var rows = loadedRows
        let indices = rows.indices.filter { isOllama(rows[$0], model: model) }
        guard !indices.isEmpty else { throw StoreError.invalidConfig }
        for index in indices { rows[index]["workbench_question_batch_size"] = min(64, max(1, size)) }
        try save(root: root, rows: rows, in: directory)
    }

    private static func save(root originalRoot: Any, rows: [[String: Any]], in directory: URL) throws {
        var root = originalRoot
        if var object = root as? [String: Any] { object["configs"] = rows; root = object }
        else { root = rows }
        let manager = FileManager.default
        try manager.createDirectory(at: directory, withIntermediateDirectories: true,
                                    attributes: [.posixPermissions: 0o700])
        try manager.setAttributes([.posixPermissions: 0o700], ofItemAtPath: directory.path)
        let data = try JSONSerialization.data(withJSONObject: root, options: [.prettyPrinted, .sortedKeys])
        let temporary = directory.appendingPathComponent(".typesafe-" + UUID().uuidString + ".tmp")
        defer { try? manager.removeItem(at: temporary) }
        guard manager.createFile(atPath: temporary.path, contents: nil, attributes: [.posixPermissions: 0o600]) else {
            throw StoreError.writeFailed
        }
        try data.write(to: temporary)
        let destination = directory.appendingPathComponent("typesafe.json")
        guard rename(temporary.path, destination.path) == 0 else { throw StoreError.writeFailed }
    }

    enum StoreError: LocalizedError {
        case invalidConfig, idCollision, writeFailed
        var errorDescription: String? {
            switch self {
            case .invalidConfig: "typesafe.json must contain a configs array or a profile array."
            case .idCollision: "A different provider already uses this model's profile ID."
            case .writeFailed: "Could not save typesafe.json."
            }
        }
    }
}
