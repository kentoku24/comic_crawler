import Foundation

struct ApprovalAPIClient {
    func assess(endpoint: URL, request: ApprovalRequestEnvelope) async throws -> ApprovalAssessmentPayload {
        var urlRequest = URLRequest(url: endpoint)
        urlRequest.httpMethod = "POST"
        urlRequest.setValue("application/json", forHTTPHeaderField: "Content-Type")
        urlRequest.httpBody = try JSONEncoder().encode(request)

        let (data, response) = try await URLSession.shared.data(for: urlRequest)
        guard let http = response as? HTTPURLResponse else {
            throw ApprovalClientError.invalidResponse
        }
        guard (200..<300).contains(http.statusCode) else {
            throw ApprovalClientError.httpStatus(http.statusCode, String(data: data, encoding: .utf8) ?? "")
        }

        let decoded = try JSONDecoder.approvalDecoder.decode(ApprovalAssessmentResponse.self, from: data)
        return decoded.assessment.toPayload()
    }
}

enum ApprovalClientError: LocalizedError {
    case invalidResponse
    case httpStatus(Int, String)

    var errorDescription: String? {
        switch self {
        case .invalidResponse:
            return "approval API から不正な応答が返った"
        case let .httpStatus(code, body):
            return "approval API error: HTTP \(code) \(body)"
        }
    }
}

private extension JSONDecoder {
    static var approvalDecoder: JSONDecoder {
        let decoder = JSONDecoder()
        return decoder
    }
}
