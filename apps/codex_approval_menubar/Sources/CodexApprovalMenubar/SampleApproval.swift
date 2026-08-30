import Foundation

struct SampleApproval: Identifiable {
    let id = UUID()
    let title: String
    let command: String
    let workingDirectory: String?
    let source: String?
    let justification: String?
    let previewPayload: ApprovalAssessmentPayload

    static let samples: [SampleApproval] = [
        SampleApproval(
            title: "Read-only diff",
            command: "git diff -- README.md",
            workingDirectory: "/Users/ken/project",
            source: "codex-cli",
            justification: "Inspect current changes before editing",
            previewPayload: ApprovalAssessmentPayload(
                summary: "risk=low; categories=read_only; command=git diff -- README.md",
                recommendation: .likelyAllow,
                riskLevel: .low,
                requiresHumanAttention: false,
                categories: ["read_only"],
                reasons: ["read-only っぽい操作を含む: `git diff`"],
                allowReasons: ["内容確認や調査目的の読み取り操作に見える"],
                denyReasons: [],
                command: "git diff -- README.md",
                workingDirectory: "/Users/ken/project",
                source: "codex-cli"
            )
        ),
        SampleApproval(
            title: "Push branch",
            command: "git push origin feature/approval-helper",
            workingDirectory: "/Users/ken/project",
            source: "codex-cli",
            justification: "Publish the completed branch for review",
            previewPayload: ApprovalAssessmentPayload(
                summary: "risk=medium; categories=write, network; command=git push origin feature/approval-helper",
                recommendation: .inspectBeforeAllow,
                riskLevel: .medium,
                requiresHumanAttention: true,
                categories: ["write", "network"],
                reasons: [
                    "ファイル変更または外部状態変更の可能性がある: `git push`",
                    "ネットワーク通信を伴う可能性がある: `git push`",
                ],
                allowReasons: ["Codex 側の説明: Publish the completed branch for review"],
                denyReasons: [
                    "ファイル・git・infra の状態を変更する可能性がある",
                    "外部送信やリモート変更が起きうる",
                ],
                command: "git push origin feature/approval-helper",
                workingDirectory: "/Users/ken/project",
                source: "codex-cli"
            )
        ),
        SampleApproval(
            title: "High-risk cleanup",
            command: "sudo rm -rf /tmp/build-cache",
            workingDirectory: "/Users/ken/project",
            source: "codex-cli",
            justification: "Reset build cache to recover from a broken state",
            previewPayload: ApprovalAssessmentPayload(
                summary: "risk=high; categories=write, privilege, destructive; command=sudo rm -rf /tmp/build-cache",
                recommendation: .denyOrInspect,
                riskLevel: .high,
                requiresHumanAttention: true,
                categories: ["write", "privilege", "destructive"],
                reasons: [
                    "ファイル変更または外部状態変更の可能性がある: `rm`",
                    "昇格権限を要求する可能性がある: `sudo`",
                    "破壊的な操作の兆候がある: `rm -rf`",
                ],
                allowReasons: [],
                denyReasons: [
                    "ファイル・git・infra の状態を変更する可能性がある",
                    "権限昇格は影響範囲が大きい",
                    "復旧が面倒、または不可逆の可能性がある",
                ],
                command: "sudo rm -rf /tmp/build-cache",
                workingDirectory: "/Users/ken/project",
                source: "codex-cli"
            )
        ),
    ]
}
