import Foundation

enum ApprovalRiskLevel: String, Codable {
    case low
    case medium
    case high
}

enum ApprovalRecommendation: String, Codable {
    case likelyAllow = "likely_allow"
    case inspectBeforeAllow = "inspect_before_allow"
    case denyOrInspect = "deny_or_inspect"
}

struct ApprovalAssessmentPayload: Codable, Identifiable {
    let id: UUID
    let summary: String
    let recommendation: ApprovalRecommendation
    let riskLevel: ApprovalRiskLevel
    let requiresHumanAttention: Bool
    let categories: [String]
    let reasons: [String]
    let allowReasons: [String]
    let denyReasons: [String]
    let command: String
    let workingDirectory: String?
    let source: String?
    let createdAt: Date

    init(
        id: UUID = UUID(),
        summary: String,
        recommendation: ApprovalRecommendation,
        riskLevel: ApprovalRiskLevel,
        requiresHumanAttention: Bool,
        categories: [String],
        reasons: [String],
        allowReasons: [String],
        denyReasons: [String],
        command: String,
        workingDirectory: String? = nil,
        source: String? = nil,
        createdAt: Date = .now
    ) {
        self.id = id
        self.summary = summary
        self.recommendation = recommendation
        self.riskLevel = riskLevel
        self.requiresHumanAttention = requiresHumanAttention
        self.categories = categories
        self.reasons = reasons
        self.allowReasons = allowReasons
        self.denyReasons = denyReasons
        self.command = command
        self.workingDirectory = workingDirectory
        self.source = source
        self.createdAt = createdAt
    }
}

struct ApprovalRequestEnvelope: Codable {
    let command: String
    let workingDirectory: String?
    let source: String?
    let justification: String?
}

struct ApprovalAssessmentResponse: Codable {
    let ok: Bool
    let assessment: ApprovalAssessmentDTO
}

struct ApprovalAssessmentDTO: Codable {
    let summary: String
    let recommendation: ApprovalRecommendation
    let riskLevel: ApprovalRiskLevel
    let requiresHumanAttention: Bool
    let categories: [String]
    let reasons: [String]
    let allowReasons: [String]
    let denyReasons: [String]
    let command: String
    let workingDirectory: String?
    let source: String?

    enum CodingKeys: String, CodingKey {
        case summary
        case recommendation
        case riskLevel = "risk_level"
        case requiresHumanAttention = "requires_human_attention"
        case categories
        case reasons
        case allowReasons = "allow_reasons"
        case denyReasons = "deny_reasons"
        case command
        case workingDirectory = "working_directory"
        case source
    }

    func toPayload() -> ApprovalAssessmentPayload {
        ApprovalAssessmentPayload(
            summary: summary,
            recommendation: recommendation,
            riskLevel: riskLevel,
            requiresHumanAttention: requiresHumanAttention,
            categories: categories,
            reasons: reasons,
            allowReasons: allowReasons,
            denyReasons: denyReasons,
            command: command,
            workingDirectory: workingDirectory,
            source: source
        )
    }
}
