---
name: premortem
description: >
  Run a premortem on a plan, launch, product, hire, strategy, partnership,
  pricing change, or decision by assuming it failed 6 months from now and
  working backward to identify specific failure modes, hidden assumptions,
  warning signs, and concrete plan revisions. Use when the user says
  "premortem this", "premortem my", "run a premortem", "what could kill this",
  "future-proof this", "stress test this plan", "what am I missing here",
  "find the blind spots", "what could go wrong", "am I missing anything",
  "poke holes in this", or "where will this break", especially when the cost
  of being wrong is high. Do not use for simple feedback, factual questions,
  vague ideas with no concrete plan, already irreversible decisions, or
  requests for multiple current perspectives instead of failure analysis.
---

# Premortem

## Overview

A premortem assumes the plan already failed and then works backward to explain
why. The goal is not generic risk listing; it is a concrete failure analysis
that exposes hidden assumptions and produces a more resilient revised plan.

## Context Threshold

Before running the premortem, gather only the context needed to avoid generic
failure scenarios.

First scan available context:

- Current conversation.
- Files the user explicitly referenced or attached.
- Nearby project files, plans, briefs, `AGENTS.md`, `CLAUDE.md`, or a local
  `memory/` folder if they are likely relevant.

Do not spend more than about 30 seconds on opportunistic workspace scanning.
Proceed when you can answer:

1. What is being premortemed?
2. Who is it for, or who does it affect?
3. What does success look like?

If one of those is missing and cannot be inferred, ask the single most important
question first. Keep asking only until the minimum threshold is met.

## Workflow

### 1. Set the frame

State the premise explicitly:

> It is 6 months from now. This plan has failed. We are looking back to
> understand what went wrong.

Use this frame before analysis so the response does not drift into polite
approval or shallow risk review.

### 2. Generate raw failure reasons

Generate every genuine reason the plan could have failed. Each reason must be:

- Specific to the actual plan.
- Grounded in details the user provided or files you read.
- A real threat, not a minor inconvenience or padded edge case.
- Stated in 1-2 direct sentences.

Do not force a fixed count. Stop when the real failure modes are exhausted.

### 3. Deep-dive each failure

For each failure reason, produce an independent deep dive:

1. Failure story: 2-3 paragraphs explaining how this failure played out.
2. Underlying assumption: one sentence naming what the user was taking for
   granted.
3. Early warning signs: 1-2 observable signals that this failure mode is
   starting.

When the runtime and current instructions allow parallel agents, run one
deep-dive agent per failure reason in parallel. If parallel agents are not
available or not permitted, run the deep dives locally as independent passes and
avoid letting earlier deep dives overwrite later ones.

### 4. Synthesize the report

Return the synthesis before the detailed deep dives:

1. Most likely failure: the scenario most likely to happen and why.
2. Most dangerous failure: the scenario with the highest damage if it happens.
3. Hidden assumption: the single biggest unexamined assumption across the
   analysis.
4. Revised plan: concrete changes that make the plan more resilient. Every
   revision must map to a failure mode.
5. Pre-launch checklist: 3-5 specific checks, tests, or safeguards.

### 5. Generate artifacts when useful

For substantial premortems, create two files in the user's workspace:

- `premortem-report-[timestamp].html`: a self-contained visual report with
  the synthesis first, followed by one card per failure mode.
- `premortem-transcript-[timestamp].md`: context gathered, raw failure reasons,
  deep dives, and final synthesis.

Use a dark, readable HTML design with clear sections and no external assets.
Open or preview the HTML only if the current environment supports it and the
user's instructions allow it.

For lightweight premortems, skip files and answer directly in chat.

## Output Contract

In chat, keep the summary concise:

1. Most likely failure.
2. Hidden assumption.
3. Single most important revision.

Then point to the report/transcript if artifacts were created. Do not sugarcoat
serious failure modes, and do not pad the analysis with generic risks.
