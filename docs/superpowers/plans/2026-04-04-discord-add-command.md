# Discord Add Command Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Discord slash command `/add url:<作品URL>` that adds a work to the crawl watchlist when existing source logic supports the URL, and returns a failure message when it does not.

**Architecture:** Reuse `manga_watch.watchlist.add_watchlist_url()` as the single normalization and persistence path, and teach `DiscordInteractionService` to parse a `url` option from the interaction payload. Keep Discord-specific behavior limited to command registration and human-readable response formatting.

**Tech Stack:** Python 3, unittest, Discord interactions, existing watchlist/storage abstractions

---

### Task 1: Red tests for `/add` interaction handling

**Files:**
- Modify: `tests/test_discord_interactions.py`

- [ ] **Step 1: Write failing tests for add success, duplicate, unsupported input, and missing option**

- [ ] **Step 2: Run the targeted interaction tests and verify the new cases fail for the expected reason**

### Task 2: Minimal `/add` implementation in interaction service

**Files:**
- Modify: `manga_watch/discord_interactions.py`

- [ ] **Step 1: Add command constant, option parsing helpers, and response formatter for watchlist add results**

- [ ] **Step 2: Route `/add` to `add_watchlist_url()` and map `WatchlistAddError` into user-facing Discord messages**

- [ ] **Step 3: Re-run targeted interaction tests and make them pass**

### Task 3: Register slash command payload

**Files:**
- Modify: `scripts/register_discord_commands.py`
- Create: `tests/test_register_discord_commands.py`

- [ ] **Step 1: Write a failing test asserting the registration payload includes `/add` with a required string `url` option**

- [ ] **Step 2: Update default command payload to include the new command**

- [ ] **Step 3: Run the registration-script tests and make them pass**

### Task 4: Verify end-to-end touched areas

**Files:**
- Modify: `README.md` (only if command documentation needs to mention `/add`)

- [ ] **Step 1: Run all targeted tests for interaction handling, watchlist behavior, and command registration**

- [ ] **Step 2: If response text or supported behavior needs documentation, update README minimally**

- [ ] **Step 3: Re-run verification after any doc-adjacent code change and summarize results**
