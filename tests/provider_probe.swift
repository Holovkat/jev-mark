import Foundation

@main
struct ProviderProbeChecks {
    static func main() throws {
        for value in GatewayProviderProbe.choices {
            let body: [String: Any] = ["complete": true, "results": [["decision": ["probe": value]]]]
            try GatewayProviderProbe.validate(JSONSerialization.data(withJSONObject: body))
        }
        let invalid: [[String: Any]] = [
            ["complete": false, "results": [["decision": ["probe": "red"]]]],
            ["results": []], ["results": [["decision": [:]]]],
            ["results": [["decision": ["probe": "unexpected"]]]],
            ["results": [["decision": ["probe": true]]]]
        ]
        for body in invalid {
            do {
                try GatewayProviderProbe.validate(JSONSerialization.data(withJSONObject: body))
                fatalError("Invalid provider response was accepted")
            } catch TypesafeAPIError.invalidResponse { }
        }
        do {
            try GatewayProviderProbe.validate(Data("not JSON".utf8))
            fatalError("Invalid JSON was accepted")
        } catch TypesafeAPIError.invalidResponse { }
        let payload = GatewayProviderProbe.payload
        precondition((payload["contexts"] as? [String]) == ["Reference colour: red."])
        print("Provider probe checks passed: both valid decisions accepted; partial, missing, malformed and out-of-schema answers rejected")
    }
}
