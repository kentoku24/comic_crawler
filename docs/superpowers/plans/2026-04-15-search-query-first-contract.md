# Search Query-First Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Switch `/search` to a query-first slash command contract while preserving single-source behavior when `source` is provided.

**Architecture:** Update slash command registration so `query` is the first required option and `source` becomes optional. Keep interaction routing thin by passing through `source=None`, then relax `SearchCommandHandler.start()` so this slice only accepts the new contract without implementing cross-source aggregation yet.

**Tech Stack:** Python, unittest, Discord interaction payloads

---

### Task 1: Lock the new slash command contract in tests

**Files:**
- Modify: `tests/test_discord_command_registration_search.py`
- Modify: `tests/test_discord_interactions_search.py`
- Modify: `tests/test_discord_search.py`

- [ ] **Step 1: Write failing tests for query-first registration and source-optional routing**
- [ ] **Step 2: Run focused tests to verify they fail for the expected contract mismatch**

Run:
```bash
/Users/kentoku.matsunami/Documents/GitHub/comic_crawler/.venv/bin/python -m unittest \
  tests.test_discord_command_registration_search \
  tests.test_discord_interactions_search \
  tests.test_discord_search
```

### Task 2: Implement the minimal plumbing change

**Files:**
- Modify: `manga_watch/discord_command_registration.py`
- Modify: `manga_watch/discord_search.py`
- Modify: `manga_watch/discord_interactions.py`

- [ ] **Step 1: Reorder `/search` options to `query`, `source`, `visibility` and make `source` optional**
- [ ] **Step 2: Keep interaction routing unchanged except for allowing missing `source`**
- [ ] **Step 3: Make `SearchCommandHandler.start()` accept `source=None` without returning the old missing-source message**

### Task 3: Verify the slice and prepare for PR review

**Files:**
- Verify: `tests/test_discord_command_registration_search.py`
- Verify: `tests/test_discord_interactions_search.py`
- Verify: `tests/test_discord_search.py`

- [ ] **Step 1: Re-run focused tests until green**
- [ ] **Step 2: Run the nearby regression suite to confirm no contract regressions**
- [ ] **Step 3: Commit only the slice changes and use the PR reviewer / merger loop**

Run:
```bash
/Users/kentoku.matsunami/Documents/GitHub/comic_crawler/.venv/bin/python -m unittest \
  tests.test_discord_command_registration_search \
  tests.test_discord_interactions_search \
  tests.test_discord_search \
```
