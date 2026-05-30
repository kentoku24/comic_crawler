# Codebase Modernization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Modernize `comic_crawler` through small behavior-preserving refactor passes that reduce change friction without changing public runtime behavior.

**Architecture:** Start by pinning parity contracts, then extract responsibilities from oversized modules behind stable public APIs. Each pass must keep entry points, env vars, storage shape, Discord behavior, source identity, and notification semantics stable unless a separate migration Issue explicitly changes them.

**Tech Stack:** Python 3.12, stdlib `unittest`, existing `manga_watch` modules, GitHub Issue #339, existing JSON/Firestore storage backends, Discord interaction endpoint tests.

---

## File Map

- Create: `docs/refactor-parity.md`
  - Stable behavior contract and validation matrix for all refactor passes.
- Modify over later passes: `manga_watch/check.py`
  - Keep `run_check()` and CLI public behavior stable; move state transition logic behind helper modules.
- Create later: `manga_watch/check_state.py`
  - State transition, history, metadata merge, failure-entry helpers.
- Create later: `manga_watch/piccoma_availability.py`
  - Piccoma wait-free config, readable limit, and availability-event construction.
- Modify later: `manga_watch/discord_command_registration.py`
  - Keep public `default_interaction_commands()` stable while moving command metadata to a shared registry.
- Modify later: `manga_watch/discord_interactions.py`
  - Keep `DiscordInteractionService` public behavior stable while simplifying routing.
- Create later: `manga_watch/discord_command_specs.py`
  - Shared command metadata for registration and routing.
- Modify later: `manga_watch/storage.py`
  - Keep public import compatibility by re-exporting split storage helpers.
- Create later: `manga_watch/storage_paths.py`, `manga_watch/storage_codec.py`, `manga_watch/storage_repository.py`, `manga_watch/component_context_store.py`
  - Split storage responsibilities.
- Modify later: `manga_watch/source_search.py`
  - Keep public `supported_search_sources()` and `search_source()` stable.
- Create later: `manga_watch/source_search_strategies/`
  - Source-specific search parsers.
- Modify later: `manga_watch/source_drift.py` and selected source adapters
  - Share small parser helpers only where runtime/canary behavior stays equivalent.
- Modify later: `manga_watch/runner.py`
  - Keep public runner entrypoint stable while separating coordination, outbox, and report formatting.
- Create later: `manga_watch/run_coordinator.py`, `manga_watch/delivery_outbox.py`, `manga_watch/run_report.py`
  - Runner responsibility split.
- Create later: `tests/helpers/`
  - Test builders for state/watchlist fixtures.

## Global Rules

- Do not change public APIs, env names, command names, persisted schema, source identity, latest-key generation, or Discord visibility in this plan.
- If a pass reveals that behavior must change, stop and create a separate migration or behavior-change Issue.
- Each pass must be independently reviewable.
- Each pass must include validation evidence in the PR description.
- Keep existing dirty user or prior-agent changes intact; do not revert unrelated files.

## Task 1: Commit-Free Baseline Parity Documentation

**Files:**
- Create: `docs/refactor-parity.md`
- Modify: none

- [ ] **Step 1: Review current issue scope**

Run:

```bash
gh issue view 339 --repo kentoku24/comic_crawler --json number,title,body,url
```

Expected: Issue #339 describes behavior-preserving modernization and lists Pass 1 as baseline / parity spec.

- [ ] **Step 2: Add parity contract doc**

Create `docs/refactor-parity.md` with these sections:

- Public Runtime Entry Points
- Environment Variables
- Storage Schema
- Source Identity
- Discord Interaction Contract
- Notification / Runner Contract
- Source Search / Drift Contract
- Required Validation Matrix
- Migration Split Triggers

The doc must state that the following are out of scope for ordinary refactor passes:

- dependency upgrades
- framework upgrades
- unittest to pytest migration
- formatter/linter/type-checker introduction
- storage schema version changes
- source identity or latest-key changes
- Discord command name, visibility, or response-payload behavior changes
- legacy env fallback removal
- notification delivery semantic changes

- [ ] **Step 3: Validate docs-only diff**

Run:

```bash
git diff -- docs/refactor-parity.md
```

Expected: one new docs file, no Python behavior changes.

## Task 2: Create Implementation Plan Artifact

**Files:**
- Create: `docs/superpowers/plans/2026-05-30-codebase-modernization.md`
- Test: docs only

- [ ] **Step 1: Add plan file**

Create `docs/superpowers/plans/2026-05-30-codebase-modernization.md` with:

- a file map
- global rules
- pass-by-pass tasks
- exact validation commands
- separate migration triggers

- [ ] **Step 2: Confirm plan references parity doc**

Run:

```bash
rg -n "docs/refactor-parity.md|Migration Split Triggers|Discord Interaction Contract" docs/superpowers/plans/2026-05-30-codebase-modernization.md
```

Expected: all three references are present.

## Task 3: Pass 1 Validation

**Files:**
- No new implementation files
- Validate all docs and current behavior

- [ ] **Step 1: Run full unit tests**

Run:

```bash
python -m unittest
```

Expected: all tests pass. Existing skipped tests may remain skipped.

- [ ] **Step 2: Run dry-run Discord command registration**

Run:

```bash
DISCORD_BOT_TOKEN=dummy DISCORD_APPLICATION_ID=dummy \
  python scripts/register_discord_commands.py --dry-run
```

Expected: JSON command payload is printed and no network call is required.

- [ ] **Step 3: Run status parity smoke check**

Run:

```bash
python -m manga_watch.check --status --format json
```

Expected: valid JSON status output.

- [ ] **Step 4: Run syntax and whitespace checks**

Run:

```bash
python -m py_compile \
  manga_watch/check.py \
  manga_watch/discord_interactions.py \
  manga_watch/discord_command_registration.py \
  manga_watch/storage.py \
  manga_watch/source_search.py \
  manga_watch/runner.py
git diff --check
```

Expected: no syntax errors and no whitespace errors.

## Task 4: Pass 2 Dead Code Audit

**Files:**
- Candidate: `manga_watch/discord_title_search.py`
- Candidate tests: `tests/test_discord_title_search.py`
- Candidate: `manga_watch/watchlist.py` retired CLI section

- [ ] **Step 1: Prove runtime references**

Run:

```bash
rg -n "discord_title_search|TITLE_COMMAND|handle_title_query" manga_watch tests README.md doc docs
rg -n "deprecated_cli|python -m manga_watch.watchlist|MANGA_WATCH_URLS|DEFAULT_ADAPTERS" manga_watch tests README.md doc docs
```

Expected: identify runtime references separately from tests/docs.

- [ ] **Step 2: Decide delete vs keep**

If a candidate has runtime references, keep it and document why.
If it is test-only and not documented as a supported entry point, delete it in a separate PR.

- [ ] **Step 3: Validate**

Run:

```bash
python -m unittest tests.test_watchlist
python -m unittest
git diff --check
```

Expected: no behavior regressions.

## Task 5: Extract Check State Transitions

**Files:**
- Create: `manga_watch/check_state.py`
- Modify: `manga_watch/check.py`
- Test: `tests/test_check.py`, `tests/test_storage.py`

- [ ] **Step 1: Move pure state helpers**

Move the following behavior-preserving helpers from `check.py` into `check_state.py`:

- metadata merge
- history sync
- unread state
- failure entry
- gap estimation
- item transition

Keep imports or re-exports so existing tests still refer to `manga_watch.check` until tests are intentionally updated.

- [ ] **Step 2: Validate**

Run:

```bash
python -m unittest tests.test_check tests.test_storage
python -m unittest
git diff --check
```

Expected: behavior unchanged.

## Task 6: Extract Piccoma Availability Boundary

**Files:**
- Create: `manga_watch/piccoma_availability.py`
- Modify: `manga_watch/check.py`
- Test: Piccoma sections in `tests/test_check.py`, `tests/test_sources.py`

- [ ] **Step 1: Move Piccoma wait-free helpers**

Move Piccoma-specific functions into `piccoma_availability.py`:

- wait-free config lookup
- readable-limit calculation
- effective authenticated/manual config merge
- wait-free update construction
- state-entry application

- [ ] **Step 2: Keep generic check flow thin**

`check.py` should call a narrow Piccoma availability hook after latest transition.

- [ ] **Step 3: Validate**

Run:

```bash
python -m unittest tests.test_check tests.test_sources
python -m unittest
git diff --check
```

Expected: Piccoma wait-free behavior unchanged.

## Task 7: Unify Discord Command Specs

**Files:**
- Create: `manga_watch/discord_command_specs.py`
- Modify: `manga_watch/discord_command_registration.py`
- Modify: `manga_watch/discord_interactions.py`
- Test: Discord command and interaction tests

- [ ] **Step 1: Add shared command metadata**

Create command specs containing:

- command name
- registration payload
- visibility policy
- modal vs message response type where applicable

Do not change the JSON payload emitted by `default_interaction_commands()`.

- [ ] **Step 2: Route registration through specs**

`default_interaction_commands()` should return the same list in the same order as before.

- [ ] **Step 3: Route interaction through specs where safe**

Start with simple command lookup and leave complex deferred handlers intact until tests prove equivalence.

- [ ] **Step 4: Validate**

Run:

```bash
python -m unittest \
  tests.test_discord_command_registration \
  tests.test_discord_command_registration_search \
  tests.test_discord_command_registration_where \
  tests.test_discord_interactions \
  tests.test_discord_interactions_search \
  tests.test_discord_interactions_where \
  tests.test_discord_supertwins_interactions
python -m unittest
git diff --check
```

Expected: command payload and visibility behavior unchanged.

## Task 8: Split Storage Responsibilities

**Files:**
- Create: `manga_watch/storage_paths.py`
- Create: `manga_watch/storage_codec.py`
- Create: `manga_watch/storage_repository.py`
- Create: `manga_watch/component_context_store.py`
- Modify: `manga_watch/storage.py`
- Test: storage and web admin tests

- [ ] **Step 1: Extract path/env helpers**

Move path/env helpers while keeping imports from `manga_watch.storage` working.

- [ ] **Step 2: Extract codec/normalization helpers**

Move validation and runtime/storage key conversion while keeping function names stable.

- [ ] **Step 3: Extract repository access**

Move JSON/Firestore repository selection behind stable wrappers.

- [ ] **Step 4: Validate**

Run:

```bash
python -m unittest tests.test_storage tests.test_firestore_storage tests.test_migrate_storage
python -m unittest tests.test_web_admin_api tests.test_web_admin_operations
python -m unittest
git diff --check
```

Expected: persisted schemas and read/write behavior unchanged.

## Task 9: Split Source Search Strategies

**Files:**
- Create: `manga_watch/source_search_strategies/`
- Modify: `manga_watch/source_search.py`
- Test: source search and Discord search tests

- [ ] **Step 1: Introduce strategy registry**

Keep `supported_search_sources()` and `search_source()` public APIs stable.

- [ ] **Step 2: Move one low-risk source first**

Move a simple parser first and validate before moving the rest.

- [ ] **Step 3: Move remaining sources in small groups**

Group related parser styles; do not rewrite parser behavior while moving.

- [ ] **Step 4: Validate**

Run:

```bash
python -m unittest tests.test_source_search tests.test_discord_search tests.test_discord_interactions_search tests.test_discord_supertwins
python -m unittest
git diff --check
```

Expected: search result ordering, labels, URLs, and supported source choices unchanged.

## Task 10: Share Source Adapter Helpers

**Files:**
- Modify: selected `manga_watch/sources/*.py`
- Modify: `manga_watch/source_drift.py`
- Test: source and drift tests

- [ ] **Step 1: Identify duplicated parser families**

Run:

```bash
rg -n "parse_.*feed_latest|_series_title_from_channel_title|html_title\\(" manga_watch/sources manga_watch/source_drift.py
```

Expected: list parser families before changing code.

- [ ] **Step 2: Extract only one proven helper at a time**

Prefer helper extraction where runtime adapter and canary use the same stable parse rule.

- [ ] **Step 3: Validate**

Run:

```bash
python -m unittest tests.test_sources tests.test_source_drift
python -m unittest
git diff --check
```

Expected: fixture expectations and canary contract unchanged.

## Task 11: Split Runner / Outbox / Report

**Files:**
- Create: `manga_watch/run_coordinator.py`
- Create: `manga_watch/delivery_outbox.py`
- Create: `manga_watch/run_report.py`
- Modify: `manga_watch/runner.py`
- Test: runner and outbound tests

- [ ] **Step 1: Extract pure formatting first**

Move report formatting without changing content.

- [ ] **Step 2: Extract outbox operations**

Move notification outbox load/enqueue/deliver logic behind stable functions.

- [ ] **Step 3: Extract coordinator class only after helpers are stable**

Keep `RunnerConfig`, `RunCoordinator`, and `main()` import compatibility where needed.

- [ ] **Step 4: Validate**

Run:

```bash
python -m unittest tests.test_runner tests.test_discord_outbound tests.test_run_job
python -m unittest
git diff --check
```

Expected: runner reports, delivery durability, and fetch behavior unchanged.

## Task 12: Test Helper Cleanup

**Files:**
- Create: `tests/helpers/`
- Modify: selected large test files

- [ ] **Step 1: Extract builders without changing assertions**

Start with duplicated watchlist/state JSON builders.

- [ ] **Step 2: Validate affected tests after each extraction**

Run the touched test module after each extraction.

- [ ] **Step 3: Validate full suite**

Run:

```bash
python -m unittest
git diff --check
```

Expected: no production-code behavior changes.

## Final Verification for Each PR

Run:

```bash
python -m unittest
git diff --check
```

Also run the pass-specific focused suite listed above.

If a pass touches Python implementation files, run:

```bash
python -m py_compile <touched python modules>
```

Each PR description must include:

- Current behavior
- Structural improvement
- Validation evidence
- Any deferred migration or behavior-change Issue
