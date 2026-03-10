# AGENTS.md instructions for /Users/kentoku.matsunami/Documents/GitHub/de-group

Use worktree by default.

When questions involve OpenAI APIs, SDKs, Codex, or other OpenAI products, use the OpenAI developer documentation MCP server as the source of truth and avoid web search unless the MCP server cannot answer.

## Skills

This repository has Codex project-local skills under `./.agents/skills`. Treat the skills listed below as available skills for sessions opened in this workspace. Runtime configuration and agent role definitions live under `./.codex/`, with `./.codex/config.toml` as the source of truth.

### Available skills

- gh-issue-resolver: GitHub Issue を起点に、accepted scope と制約を抽出し、`maker` 実装、PR 更新、`$gh-pr-reviewer` による review gate、`$merger` による final gate までを標準ループで進める。Use when: Issue URL/番号だけで作業を開始したいとき、Issue に既存の `$gh-issue-reviewer` または legacy `$spacex-chief-engineer` review があるとき。 (file: ./.agents/skills/gh-issue-resolver/SKILL.md)
- gh-issue-reviewer: GitHub Issue の implementation readiness を判定し、accepted scope, constraints, non-goals, blocking concerns を整理して `APPROVE` / `NG` を返す。Use when: 実装開始前に Issue の scope と制約を固めたいとき、`$gh-issue-resolver` の入口条件を満たす issue review を残したいとき、旧 `spacex-chief-engineer` が担っていた issue review を明示的に使いたいとき。 (file: ./.agents/skills/gh-issue-reviewer/SKILL.md)
- merger: `gh-pr-reviewer` の承認コメント、review thread 解決状況、GitHub 上の merge-ready 性を確認して `APPROVE` / `NG` を返す final gate。`merge:true` が明示されたときだけ、自身の `APPROVE` 後に PR を merge する。Use when: `gh-pr-reviewer` 承認後に「今この PR をマージしてよいか」を判定したいとき、または self-merge まで委譲したいとき。 (file: ./.agents/skills/merger/SKILL.md)
- gh-pr-reviewer: PR 差分を PR Reviewer 観点でレビューし、Description / Issue / 過去指摘と実装の整合、repo fit、検証根拠を確認したうえで `APPROVE` / `NG` を判定する。Use when: PR URL/番号を渡して merge-ready かを判定したいとき。 (file: ./.agents/skills/gh-pr-reviewer/SKILL.md)

### Available agent roles

- `gh-pr-reviewer`: `./.codex/agents/gh-pr-reviewer.toml`
- `explorer`: `./.codex/agents/explorer.toml`
- `maker`: `./.codex/agents/maker.toml`

### How to use skills

- Trigger rules: If the user names one of the skills above with `$skill-name` or plain text, or the task clearly matches its description, you must use that skill for that turn.
- Progressive disclosure: Open the referenced `SKILL.md` and read only enough to follow the workflow. Load referenced files only when needed.
- Relative paths: Resolve paths referenced from a project-local skill relative to that skill's directory first.
- Local dependencies: Prefer project-local skill dependencies under `./.agents/skills` and agent settings from `./.codex/config.toml` before falling back to user-level defaults.
- Missing or blocked: If a named project-local skill cannot be read, say so briefly and continue with the best fallback.
- Runtime note: `gh-issue-resolver` in this workspace stops at `$merger` approval by default. PR merge は `merge:true` を明示した場合にだけ実行する。
