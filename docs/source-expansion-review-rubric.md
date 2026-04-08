# Source Expansion Review Rubric

This rubric defines how to review source expansion work in this repository.

## Purpose

- Use one bar for source-expansion issues and a separate bar for source-expansion PRs.
- Keep public-surface, parser, fixture, and regression expectations explicit.
- Prefer bounded adapter changes over speculative framework work.

## Issue review

Issue review answers one question: is this ready to implement?

Approve only when the issue clearly states:

- accepted input URLs
- canonical seed URL
- work_id and latest_key expectations
- public source of truth
- constraints and non-goals
- fixture, canary, and regression evidence plan
- a scope that fits in one implementation lane

Reject the issue when it drifts into:

- login-required surfaces
- private APIs or app-only endpoints
- viewer image scraping
- browser automation without explicit approval
- unrelated crawler infrastructure or UX redesign

## PR review

PR review answers one question: is this ready to merge?

Approve only when the PR demonstrates:

- the issue promise was implemented as written
- the architecture fits the existing adapter family
- the parser contract is clear and fails loudly on missing signals
- fixture, canary, and regression evidence is present
- no unexplained scope creep remains

## Standard sections

### Source issue

- Summary
- Goal
- Public source of truth
- Accepted input URLs
- Canonical seed URL
- `work_id` / `latest_key` expectation
- Scope
- Constraints
- Non-goals
- Test / evidence plan
- Success criteria
- Next action

### Source PR

- Issue
- Change summary
- Architecture note
- Public parsing contract used
- Verification
- Residual risk

## Review bar

- Issue review checks implementation readiness.
- PR review checks merge readiness.
- Keep the two bars separate so reviewers do not re-litigate the same work twice.
