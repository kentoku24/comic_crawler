import Foundation
import UserNotifications

@MainActor
final class ApprovalStore: ObservableObject {
    @Published private(set) var requests: [ApprovalAssessmentPayload]
    @Published var draftCommand: String
    @Published var draftWorkingDirectory: String
    @Published var draftSource: String
    @Published var draftJustification: String
    @Published var endpointURL: String
    @Published var errorMessage: String?
    @Published var isSubmitting: Bool

    init(
        requests: [ApprovalAssessmentPayload],
        draftCommand: String = "",
        draftWorkingDirectory: String = "",
        draftSource: String = "codex-cli",
        draftJustification: String = "",
        endpointURL: String = "http://127.0.0.1:8000/api/codex/approval-assess/",
        errorMessage: String? = nil,
        isSubmitting: Bool = false
    ) {
        self.requests = requests
        self.draftCommand = draftCommand
        self.draftWorkingDirectory = draftWorkingDirectory
        self.draftSource = draftSource
        self.draftJustification = draftJustification
        self.endpointURL = endpointURL
        self.errorMessage = errorMessage
        self.isSubmitting = isSubmitting
    }

    var latestRequest: ApprovalAssessmentPayload? {
        requests.first
    }

    var menuBarSymbolName: String {
        guard let latestRequest else { return "shield" }
        switch latestRequest.riskLevel {
        case .low:
            return "checkmark.shield"
        case .medium:
            return "exclamationmark.shield"
        case .high:
            return "xmark.shield"
        }
    }

    func submitDraft() async {
        errorMessage = nil
        let trimmedCommand = draftCommand.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedCommand.isEmpty else {
            errorMessage = "command が空だ"
            return
        }
        guard let url = URL(string: endpointURL) else {
            errorMessage = "endpoint URL が不正だ"
            return
        }

        isSubmitting = true
        defer { isSubmitting = false }

        let requestBody = ApprovalRequestEnvelope(
            command: trimmedCommand,
            workingDirectory: draftWorkingDirectory.nilIfBlank,
            source: draftSource.nilIfBlank,
            justification: draftJustification.nilIfBlank
        )

        do {
            let payload = try await ApprovalAPIClient().assess(endpoint: url, request: requestBody)
            requests.insert(payload, at: 0)
            await notifyIfNeeded(for: payload)
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func loadSample(_ sample: SampleApproval) {
        draftCommand = sample.command
        draftWorkingDirectory = sample.workingDirectory ?? ""
        draftSource = sample.source ?? "codex-cli"
        draftJustification = sample.justification ?? ""
    }

    static func preview() -> ApprovalStore {
        ApprovalStore(
            requests: SampleApproval.samples.map { $0.previewPayload },
            draftCommand: SampleApproval.samples.first?.command ?? "",
            draftWorkingDirectory: SampleApproval.samples.first?.workingDirectory ?? "",
            draftSource: SampleApproval.samples.first?.source ?? "codex-cli",
            draftJustification: SampleApproval.samples.first?.justification ?? ""
        )
    }

    private func notifyIfNeeded(for payload: ApprovalAssessmentPayload) async {
        guard payload.requiresHumanAttention else { return }
        let center = UNUserNotificationCenter.current()
        try? await center.requestAuthorization(options: [.alert, .badge, .sound])

        let content = UNMutableNotificationContent()
        content.title = "Codex approval request"
        content.body = payload.summary
        content.sound = .default

        let request = UNNotificationRequest(
            identifier: payload.id.uuidString,
            content: content,
            trigger: nil
        )
        try? await center.add(request)
    }
}

private extension String {
    var nilIfBlank: String? {
        let trimmed = trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? nil : trimmed
    }
}
