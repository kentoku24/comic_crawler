# AGENTS.md instructions for /Users/kentoku.matsunami/Documents/GitHub/comic_crawler

When questions involve OpenAI APIs, SDKs, Codex, or other OpenAI products, use the OpenAI developer documentation MCP server as the source of truth and avoid web search unless the MCP server cannot answer.

## Skills

This repository has Codex project-local skills under `./.agents/skills`. Treat the skills listed below as available skills for sessions opened in this workspace. They complement user-level skills in `$HOME/.agents/skills`. Runtime configuration and agent role definitions live under `./.codex/`.

### Available skills

- gh-issue-maker-chief-engineer-loop: GitHub Issue を起点に、accepted scope と制約を抽出し、`maker` 実装、PR 更新、`$spacex-chief-reviewer` による gate、`$merger` による merge gate までを標準ループで進める。Use when: Issue URL/番号だけで作業を開始したいとき、Issue に既存の Chief Engineer レビューがあるとき。 (file: ./.agents/skills/gh-issue-maker-chief-engineer-loop/SKILL.md)
- gh-pr-spacex-chief-engineer-review: GitHub の指定 PR を Chief Engineer 観点でレビューし、Description と実装の整合、過去指摘の解消状況まで確認する。Use when: PR URL/番号を渡してマージ前レビューをしたいとき。 (file: ./.agents/skills/gh-pr-spacex-chief-engineer-review/SKILL.md)
- merger: comic_crawler 用の最終 merge gate。`$spacex-chief-reviewer` の `APPROVE` コメントと全 review thread resolved を確認し、満たすときだけ merge する。Use when: comic_crawler の PR を条件付きで自動マージしたいとき。 (file: ./.agents/skills/merger/SKILL.md)
- spacex-chief-reviewer: comic_crawler 専用の reviewer gate。repo の規模と既存構造に対して変更が merge-ready かを `APPROVE` / `NG` で判定する。Use when: comic_crawler の PR を repo 固有の観点でレビューしたいとき。 (file: ./.agents/skills/spacex-chief-reviewer/SKILL.md)

### How to use skills

- Trigger rules: If the user names one of the skills above with `$skill-name` or plain text, or the task clearly matches its description, you must use that skill for that turn.
- Progressive disclosure: Open the referenced `SKILL.md` and read only enough to follow the workflow. Load referenced files only when needed.
- Relative paths: Resolve paths referenced from a project-local skill relative to that skill's directory first.
- Local dependencies: If a project-local skill references another project-local skill by name, prefer the repo-local version before any global skill with a similar role.
- Missing or blocked: If a named project-local skill cannot be read, say so briefly and continue with the best fallback.
