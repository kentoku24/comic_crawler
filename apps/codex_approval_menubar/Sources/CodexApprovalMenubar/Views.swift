import SwiftUI

struct ApprovalMenuView: View {
    @ObservedObject var store: ApprovalStore

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("Codex Approval Helper")
                .font(.headline)

            TextField("Assessment API endpoint", text: $store.endpointURL)
                .textFieldStyle(.roundedBorder)

            VStack(alignment: .leading, spacing: 8) {
                Text("Command")
                    .font(.subheadline.weight(.semibold))
                TextEditor(text: $store.draftCommand)
                    .font(.system(.body, design: .monospaced))
                    .frame(minHeight: 88)
                    .overlay(RoundedRectangle(cornerRadius: 8).stroke(Color.secondary.opacity(0.35)))
            }

            TextField("Working directory", text: $store.draftWorkingDirectory)
                .textFieldStyle(.roundedBorder)
            TextField("Source", text: $store.draftSource)
                .textFieldStyle(.roundedBorder)
            TextField("Justification", text: $store.draftJustification)
                .textFieldStyle(.roundedBorder)

            HStack(spacing: 8) {
                Button {
                    Task { await store.submitDraft() }
                } label: {
                    if store.isSubmitting {
                        ProgressView()
                            .controlSize(.small)
                    } else {
                        Text("Assess")
                    }
                }
                .keyboardShortcut(.defaultAction)
                .disabled(store.isSubmitting)

                Menu("Samples") {
                    ForEach(SampleApproval.samples) { sample in
                        Button(sample.title) {
                            store.loadSample(sample)
                        }
                    }
                }

                Spacer()
            }

            if let errorMessage = store.errorMessage {
                Text(errorMessage)
                    .font(.footnote)
                    .foregroundStyle(.red)
            }

            Divider()

            if let latest = store.latestRequest {
                LatestApprovalSummaryView(request: latest)
            } else {
                Text("まだ承認要求はない")
                    .foregroundStyle(.secondary)
            }

            Divider()

            Text("Recent requests")
                .font(.subheadline.weight(.semibold))
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 8) {
                    ForEach(store.requests) { request in
                        ApprovalRowView(request: request)
                    }
                }
            }
            .frame(minHeight: 180)
        }
        .padding(16)
        .frame(width: 460)
    }
}

struct LatestApprovalSummaryView: View {
    let request: ApprovalAssessmentPayload

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Label(request.riskLevel.rawValue.uppercased(), systemImage: symbol)
                .font(.subheadline.weight(.semibold))
            Text(request.summary)
                .font(.footnote)
                .foregroundStyle(.secondary)
                .textSelection(.enabled)
            Text(request.command)
                .font(.system(.footnote, design: .monospaced))
                .textSelection(.enabled)
            Text(recommendationText)
                .font(.footnote)
        }
    }

    private var symbol: String {
        switch request.riskLevel {
        case .low:
            return "checkmark.shield"
        case .medium:
            return "exclamationmark.shield"
        case .high:
            return "xmark.shield"
        }
    }

    private var recommendationText: String {
        switch request.recommendation {
        case .likelyAllow:
            return "推奨: 許可寄り"
        case .inspectBeforeAllow:
            return "推奨: 許可前に確認"
        case .denyOrInspect:
            return "推奨: そのまま許可しない"
        }
    }
}

struct ApprovalRowView: View {
    let request: ApprovalAssessmentPayload

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Text(request.riskLevel.rawValue.uppercased())
                    .font(.caption.weight(.semibold))
                Text(request.createdAt.formatted(date: .omitted, time: .shortened))
                    .font(.caption)
                    .foregroundStyle(.secondary)
                Spacer()
            }
            Text(request.command)
                .font(.system(.caption, design: .monospaced))
                .lineLimit(2)
            Text(request.categories.joined(separator: ", "))
                .font(.caption2)
                .foregroundStyle(.secondary)
        }
        .padding(8)
        .background(Color.secondary.opacity(0.08))
        .clipShape(RoundedRectangle(cornerRadius: 8))
    }
}

struct ApprovalDetailView: View {
    let request: ApprovalAssessmentPayload?

    var body: some View {
        Group {
            if let request {
                ScrollView {
                    VStack(alignment: .leading, spacing: 16) {
                        Text(request.command)
                            .font(.system(.headline, design: .monospaced))
                            .textSelection(.enabled)

                        detailBlock(title: "Summary", lines: [request.summary])
                        detailBlock(title: "Reasons", lines: request.reasons)
                        detailBlock(title: "Allow reasons", lines: request.allowReasons)
                        detailBlock(title: "Deny reasons", lines: request.denyReasons)

                        if let workingDirectory = request.workingDirectory {
                            detailBlock(title: "Working directory", lines: [workingDirectory])
                        }
                        if let source = request.source {
                            detailBlock(title: "Source", lines: [source])
                        }
                    }
                    .padding(20)
                }
            } else {
                ContentUnavailableView("No approval yet", systemImage: "shield")
            }
        }
    }

    @ViewBuilder
    private func detailBlock(title: String, lines: [String]) -> some View {
        if !lines.isEmpty {
            VStack(alignment: .leading, spacing: 6) {
                Text(title)
                    .font(.headline)
                ForEach(lines, id: \.self) { line in
                    Text("• \(line)")
                        .textSelection(.enabled)
                }
            }
        }
    }
}
