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
