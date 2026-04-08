# Source Expansion Review Rubric

This rubric defines how to review source expansion work in this repository.

## Purpose

- Use one bar for source-expansion issues and a separate bar for source-expansion PRs.
- Keep public-surface, parser, fixture, and regression expectations explicit.
- Prefer bounded adapter changes over speculative framework work.

## Issue review rubric

Issue review answers one question: is this ready to implement?

### Scope clarity

The issue must make the implementation lane concrete enough to execute without follow-up clarification.

- accepted input URLs are explicit
- canonical `seed_url` storage shape is explicit
- `work_id` and `latest_key` expectations are explicit
- the issue is bounded to one host or one reusable adapter-family task

### Public-surface legitimacy

The issue must name the public source of truth the adapter will rely on.

- acceptable examples: canonical series page, episode page, title page, RSS or Atom feed, public HTML signals
- explicitly out of scope: login-required surfaces, private APIs, app-only endpoints, viewer image scraping, browser automation without explicit approval

### Adapter-family fit

The issue should say whether the work is:

- a new host added to an existing adapter family
- a reusable adapter-family extraction or refactor
- a bespoke adapter with a clear reason reuse does not fit

When multiple hosts share the same public contract shape, reviewers should prefer reusable family work over host-by-host patching.

### Failure-model clarity

The issue should describe failure behavior before implementation begins.

- unsupported URL types should fail clearly
- missing or drifted public signals should fail loudly
- the plan should avoid silent false positives and false negatives
- the change should avoid widening risk to unrelated sources

### Testability before implementation

The issue must carry an evidence plan, not only an implementation idea.

- fixture bundle plan
- normalize test plan
- `fetch_latest` contract test plan
- source drift canary plan, or an explicit defer reason
- focused regression verification scope

### Non-goal discipline

Reject the issue when it quietly expands into unrelated work.

- every URL type on the host instead of accepted inputs only
- login, paywall, or app features
- unrelated Discord UX or crawler infrastructure work
- host-specific implementation plus extra architecture work that the issue never asked for

### Issue approval bar

Approve only when the issue clearly states:

- accepted input URLs
- canonical `seed_url`
- `work_id` and `latest_key` expectations
- public source of truth
- constraints and non-goals
- fixture, canary, and regression evidence plan
- a scope that fits in one implementation lane

## PR review rubric

PR review answers one question: is this ready to merge?

### Outcome fit

The PR must satisfy the related issue contract as written.

- accepted input URLs behave as promised
- canonical `seed_url`, `work_id`, and `latest_key` remain coherent
- `fetch_latest` returns the intended latest snapshot
- unsupported paths still fail clearly

### Architecture fit

The implementation should fit the existing adapter architecture without over-abstracting.

- reuse an existing adapter family when the public contract shape matches
- duplicated logic needs a strong reason
- abstraction level should match actual reuse, not hypothetical future reuse
- registry and capability wiring should stay consistent with existing sources

### Parser-contract quality

The parser contract should be understandable from code and fixtures.

- the relied-on public signal is obvious
- missing signals fail loudly
- fallback rules are intentional rather than accidental
- optimistic parsing does not silently point at the wrong latest episode

### Test evidence quality

Manual spot checks are not enough for approval.

- normalize and fetch tests cover the contract
- representative success and failure fixtures exist
- classification expectations are asserted when title or category logic matters
- `manga_watch/source_drift.py` canary coverage exists, or the defer reason is explicit
- regression output is shown for the impacted surface

### Regression safety

The PR should show it did not weaken existing source contracts.

- existing sources still pass their relevant tests
- fixture matrix remains complete
- unsupported-source and unsupported-url behavior does not regress
- docs and capability tables are updated when the public contract changes

### Evidence-to-risk proportionality

Proof burden should increase with the blast radius.

- a single-host addition inside a known family can be approved with focused fixture and regression evidence
- shared family extraction needs broader regression coverage and clearer rationale
- multi-source parser or canary strategy changes need stronger evidence than a single-host add

### Scope discipline

Reject PRs that quietly bundle unrelated work.

- extra host support not promised by the issue
- unrelated docs or runtime refactors
- behavior changes without matching issue or PR description updates

### PR approval bar

Approve only when the PR demonstrates:

- the issue promise was implemented as written
- the architecture fits the existing adapter family and repository shape
- the parser contract is clear and fails loudly on missing signals
- fixture, canary, and regression evidence is present
- no unexplained scope creep remains

## Recommended issue sections

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

## Recommended PR sections

- Issue
- Change summary
- Architecture note
- Public parsing contract used
- Verification
- Residual risk
