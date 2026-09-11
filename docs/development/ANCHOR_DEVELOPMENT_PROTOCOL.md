# Anchor Development Protocol

Version: 1.0
Status: Ratified
Ratified after: D5 Product Integration
Initial baseline: main @ fd3baca
Applies to: All Project Anchor development work

This protocol was derived from measured Project Anchor development-session
evidence following D5 and is intended to preserve correctness while allocating
verification effort according to risk.

---

## 1. Purpose

Anchor is financial software.

Development must therefore optimize for two goals simultaneously:

1. correctness and protection of financial invariants;
2. efficient use of engineering time, model usage, machine resources, and verification effort.

The objective is not to maximize the number of tests run.

The objective is to obtain enough independent evidence to conclude that a change is correct, safe, and production-ready.

The standard philosophy is:

Implement
→ targeted proof
→ realistic browser proof when applicable
→ domain regression
→ one final full suite when warranted by risk

Do not repeatedly rerun broad verification merely to increase subjective confidence.

---

## 2. Core Principles

### 2.1 Risk determines verification

Every development gate must be assigned a risk tier before implementation begins.

Verification effort must be proportional to that tier.

A copy change and a financial cash-flow change must not receive the same QA burden.

### 2.2 Diverse evidence beats repeated evidence

Confidence should come from different forms of proof agreeing:

- deterministic tests;
- financial identity tests;
- architecture guardrails;
- targeted mutation tests;
- browser behavior;
- persistence behavior;
- type/lint/build checks;
- human product review.

Repeatedly running the same full test suite is not equivalent to independent evidence.

### 2.3 A degraded environment cannot produce trustworthy timing evidence

Unexpected test slowness, widespread exact timeouts, resource exhaustion, battery throttling, host sleep, and orphan processes must be classified as possible environment failures before being treated as product regressions.

### 2.4 Fresh context is preferred

A fresh Claude Code session should normally be used for each development gate.

Long inherited context materially increases model cost and makes development state harder to reason about.

### 2.5 Stop when evidence becomes unreliable

Do not respond to unreliable verification by increasing the amount of unreliable verification.

One abnormal broad failure triggers diagnosis, not repeated full-suite attempts.

---

## 3. Risk Tiers

### Tier 1: Financial / Contract Critical

Examples:

- NOI calculations;
- rent schedules;
- lease rollover;
- recoveries;
- vacancy;
- TI / LC;
- free rent;
- debt;
- DSCR;
- IRR;
- equity multiple;
- exit valuation;
- waterfalls;
- promotes;
- financial fingerprints;
- canonical monthly / annual financial contracts.

Default verification:

- focused unit tests;
- explicit financial identity tests;
- negative-path tests;
- focused mutation proofs for key invariants;
- relevant domain regression;
- browser validation if the change is user-facing;
- one final full backend suite;
- one final full frontend suite if frontend contracts changed;
- type/lint/build;
- human review where interpretation or presentation matters.

Financial formulas must never be changed as incidental cleanup inside a lower-risk gate.

---

### Tier 2: State / Integration Critical

Examples:

- persistence;
- database migrations;
- API contracts;
- mode dispatch;
- fingerprints;
- stale-state behavior;
- sensitivity orchestration;
- AI grounding state;
- save / load / duplicate / delete behavior.

Default verification:

- targeted tests;
- negative-path tests;
- persistence round-trip tests;
- realistic browser E2E;
- relevant domain regression;
- one final relevant full suite;
- type/lint/build.

Mutation testing is allowed when there is a specific state or dispatch invariant worth protecting.

---

### Tier 3: Product / UI Behavior

Examples:

- NumericInput;
- form interactions;
- keyboard behavior;
- results-table interactions;
- navigation;
- tabs;
- stale banners;
- focus behavior;
- workspace state;
- client-side analyst workflows.

Default verification:

- component / interaction tests;
- realistic browser E2E;
- relevant frontend domain tests;
- type/lint/build;
- human visual review where appropriate.

Run the full frontend suite when the changed component is shared broadly or has substantial cross-mode blast radius.

A full backend suite is normally unnecessary when no backend production code changed.

Broad mutation testing is normally unnecessary.

---

### Tier 4: Presentation / Copy

Examples:

- wording;
- labels;
- tooltips;
- spacing;
- CSS;
- visual hierarchy;
- non-functional table styling.

Default verification:

- focused frontend test only if behavior is affected;
- the specific fast architecture / source-text guardrail tests that monitor the touched source text (see below);
- type/lint/build;
- browser screenshot / human visual review.

Normally do not run:

- full backend;
- full frontend;
- mutation campaigns;
- persistence suites.

Do not escalate a Tier 4 change into Tier 1-style verification without a concrete reason.

#### Tier 4 guardrail check

Some architecture and source-text guardrail tests read production source directly — for example, tests that count where a CSS class is used, or that forbid implementation vocabulary in product copy. A presentation, copy, or CSS change can trip them without changing any behavior.

If a Tier 4 change touches source text monitored by such cheap guardrails, run those specific fast guardrail tests.

This does not justify a full frontend suite, a full backend suite, or broad mutation testing unless another risk factor independently requires them.

Rationale: in D5.7, a CSS class appearing in one additional place tripped a source-text guardrail that only a full frontend run happened to catch. Running the relevant guardrail directly captures that protection without the full suite.

---

## 4. Session Discipline

### 4.1 One gate, one fresh session

Start each development gate in a fresh Claude Code session by default.

Avoid carrying one session through multiple major gates.

### 4.2 Context thresholds

Context growth is a risk and cost signal.

Guidelines:

- under ~300k context: generally healthy;
- ~300k to 350k: consider whether the gate can close soon;
- ~350k to 500k: strongly prefer checkpointing and restarting;
- over ~500k: start a fresh session unless the current task is minutes from completion.

These thresholds are guidance, not financial or product rules.

### 4.3 Separate implementation and closeout when useful

For larger Tier 1 or Tier 2 work:

Session A:

- implement;
- targeted tests;
- focused negative proofs;
- checkpoint.

Session B:

- browser verification;
- domain regression;
- final suites;
- closeout.

Do not keep an implementation session alive for hours merely to preserve conversational context.

---

## 5. Machine Preflight

Run a lightweight machine-health check before expensive verification.

Preferred state:

- AC power connected;
- battery saver off;
- the machine will not sleep during the expected run (see 5.1);
- >= 4 GB free RAM preferred;
- >= 20 GB free disk;
- no stale Vitest processes;
- no stale Pytest processes;
- no stale Uvicorn processes;
- no orphan Vite servers;
- no unnecessary Playwright / Chromium workers;
- expected development ports either free or intentionally owned;
- no duplicate full test suites;
- unnecessary heavy applications closed (see 5.2).

### 5.1 Host availability / sleep

Before browser verification or broad-suite verification:

- connect AC power;
- confirm the machine is not configured to sleep, while plugged in, within the expected duration of the run;
- if a long unattended verification run is expected, ensure Windows will remain awake for that period;
- do not close the laptop lid if the configured lid action would suspend the machine.

Do not prescribe or make a permanent power-plan modification.

If a power or sleep setting is changed temporarily solely for verification, restore the user's normal setting afterward.

A run during which the host slept or became unavailable does not produce trustworthy evidence, including its test durations. Treat it as an environment failure (see 5.4).

Rationale: the D5 session evidence contained multi-hour unexplained stalls — foreground commands overrunning their timeouts by hours, and single tests reporting multi-hour durations — consistent with the host sleeping or becoming unavailable.

### 5.2 Heavy applications

Close unnecessary heavy applications before any browser verification or any broad / domain / full-suite verification, regardless of risk tier.

Examples:

- Steam;
- games;
- unnecessary memory-heavy browser windows.

Do not require closing normal development tools (editor, language servers, terminals) that are behaving normally.

### 5.3 Resource warning zone

If free RAM falls near 2 GB, process creation becomes unreliable, or the machine begins paging heavily, stop broad verification.

Do not continue merely because a test process is technically still alive.

### 5.4 Performance anomaly rule

If normally fast tests suddenly hit exact 5-second timeouts across unrelated files, suspect the environment first.

If an already-running backend suite that normally completes around its recent healthy baseline suddenly takes dramatically longer, treat this as an environmental warning signal.

Do not turn runtime heuristics into rigid product assertions because suite size will evolve.

---

## 6. Testing Sequence

The default verification order is:

1. targeted tests directly covering the change;
2. explicit negative proofs / mutation proofs where warranted;
3. realistic browser proof when behavior is user-facing;
4. relevant domain regression;
5. one final relevant full suite when required by risk tier;
6. type checking;
7. lint;
8. production build.

Do not start with repeated full suites.

Do not use full suites as the primary debugging mechanism.

---

## 7. Full-Suite Policy

### 7.1 Final suite

For Tier 1 and major Tier 2 changes, normally run:

- one final full frontend suite, if frontend behavior/contracts are implicated;
- one final full backend suite, if backend behavior/contracts are implicated.

### 7.2 Failed broad run

If a broad suite fails:

1. inspect the failure;
2. determine whether it is code, test, or environment;
3. run the directly affected test;
4. fix the root cause if required;
5. rerun the relevant targeted/domain tests.

Only rerun the full suite after the implementation has changed or the environmental cause has been corrected.

Do not immediately launch the same full suite again.

### 7.3 Environmental mass failures

Many unrelated exact timeout failures are not evidence of many simultaneous regressions.

Stop and diagnose environment health.

---

## 8. Browser Verification

Browser testing is first-class verification for user-facing behavior.

Realistic browser QA is mandatory when a change materially affects:

- input behavior;
- keyboard behavior;
- mouse / focus behavior;
- navigation;
- hydration;
- save / reopen;
- stale / current state;
- persistence;
- conditional controls;
- workspace switching;
- tables;
- cross-mode flows.

Successful manual workflows should increasingly become reusable Playwright flows.

Prefer scripted Playwright flows over dozens of model-driven individual browser actions when the workflow is stable.

Do not make paid AI calls when a local stub/fake can validate product behavior.

---

## 9. Mutation Testing

Mutation testing is surgical, not ceremonial.

Use it to answer a specific question:

"If this invariant is removed or weakened, will a test fail?"

Good examples:

- remove `status === "solved"`;
- make unknown operating mode fall through;
- remove an exit-NOI validity condition;
- weaken suite override shadowing;
- allow an unapproved financial module.

Default target:

1 to 5 meaningful mutants.

Do not run large speculative mutation campaigns unless the financial risk clearly justifies them.

Tier 4 changes should normally have no mutation testing.

---

## 10. Test Timeout Policy

Keep normal test timeout budgets strict.

Do not globally raise Vitest timeouts to accommodate a degraded machine.

If a single integration-heavy test legitimately exceeds the normal budget on a healthy machine:

1. profile it;
2. remove unnecessary waits or polling;
3. preserve behavioral coverage;
4. only then consider a narrowly scoped per-test timeout.

A broad timeout increase requires explicit justification.

---

## 11. Git Safety

### 11.1 No stash-based baseline comparison

Do not use `git stash` to compare current behavior against HEAD during verification.

Stash / checkout workflows can rewrite line endings on Windows and contaminate evidence.

Use a separate Git worktree for baseline comparisons.

### 11.2 Protect the index

Automated architecture tests must not modify the developer's Git index.

Use repository-safe methods such as private index copies when Git inspection requires it.

### 11.3 Feature branches

Use feature branches as checkpoints.

Keep `main` as the latest accepted, working baseline.

Prefer genuine merge commits for major Anchor development phases when preserving gate history has value.

Do not rewrite accepted history unless explicitly approved.

---

## 12. File Editing

Prefer direct Edit / patch operations for normal code changes.

Avoid whole-file rewrites through Python or shell scripts unless rewriting the complete file is genuinely intended.

This reduces line-ending and formatting risk.

Do not globally normalize repository line endings during an unrelated gate.

Tests that inspect source text must normalize line endings at their own boundary.

---

## 13. Background Processes

Do not create farms of polling loops.

Prefer one background job with explicit completion output.

### 13.1 Stopping a task is not proof its children stopped

Stopping a Claude background task, or terminating its parent shell, is not proof that its child processes terminated.

TaskStop and parent-process termination have previously left child processes alive on this machine — including Vitest workers and a Vite dev server that kept holding a development port long after the session that started it had ended.

On Windows:

- verify the actual remaining process trees (for example with a PowerShell / CIM process query, not a Git Bash `ps` listing, which does not reliably show Windows processes);
- verify the expected development ports are free or intentionally owned;
- terminate the full Claude-owned process tree when necessary;
- confirm no orphan Vite, Vitest, Pytest, Uvicorn, or Chromium / Playwright process remains.

Do not kill user-owned processes merely because they share the same executable name. Identify ownership (command line, parent process, start time, port) before terminating anything.

### 13.2 Closeout check

At gate closeout, verify there are no unexpected Claude-owned:

- Vitest;
- Node / Vite;
- Pytest;
- Uvicorn;
- Chromium / Playwright

processes left running.

Do not kill editor language servers or user-owned services without cause.

---

## 14. Model Usage

Use model capability according to risk.

### High-capability reasoning model

Prefer for:

- architecture;
- financial logic;
- contracts;
- migrations;
- complex debugging;
- difficult reviews;
- gate planning;
- final code review.

### Faster / lower-cost coding model

May be used for:

- mechanical implementation from an approved specification;
- repetitive tests;
- copy;
- CSS;
- straightforward refactors;
- low-risk presentation work.

Preferred pattern:

Think expensive
→ execute efficiently
→ review expensive

Do not downgrade financial reasoning solely to reduce usage.

---

## 15. Subagents

Subagents are opt-in, not default.

Use them when work is genuinely separable, especially:

- independent read-only research;
- isolated code review;
- parallel analysis of unrelated domains.

Do not spawn subagents simply because the capability exists.

Each subagent must have:

- a narrow question;
- bounded scope;
- clear output;
- no unnecessary duplication of the parent context.

### 15.1 Tooling efficiency note: automated review hooks

Minor optimization, not a primary protocol rule.

If an expensive security-review hook runs both at commit and at push against the same unchanged tree, prefer deduplicating or reusing the first result if the repository tooling supports this safely.

Do not weaken security review merely to reduce tokens.

---

## 16. Prompt Design

Gate prompts should remain precise, but stable rules should not be recopied indefinitely.

Stable rules belong in:

- CLAUDE.md;
- this protocol;
- architecture invariant documents.

A normal future gate prompt should primarily contain:

- objective;
- risk tier;
- permitted scope;
- change contract;
- acceptance criteria;
- gate-specific negative proofs;
- gate-specific stop conditions.

Reference permanent project rules instead of restating them.

Clarity is more important than minimizing prompt length.

Fresh sessions provide more token savings than aggressively shortening a well-written gate prompt.

---

## 17. Architecture and Financial Invariants

Permanent underwriting invariants should live in a dedicated architecture document.

Financial gates must explicitly preserve those invariants unless the gate exists to change one of them.

AI must not silently replace deterministic financial calculations.

Documents / AI interpretation should flow through analyst approval into deterministic underwriting logic.

For Project Anchor, the architectural principle remains:

Documents
→ Proposed Data
→ Analyst Approval
→ Deterministic Engine
→ Decision Support

---

## 18. Human Review

Automated tests do not replace analyst judgment.

Human review is required when a gate materially changes:

- visual hierarchy;
- analyst workflow;
- financial presentation;
- terminology;
- interaction design;
- decision-support clarity.

A human acceptance gate should evaluate the actual product, not screenshots alone when interactive behavior matters.

---

## 19. Stop Conditions

Claude should stop and report rather than expanding scope when:

1. a financial defect is discovered outside the assigned financial scope;
2. a schema migration becomes necessary unexpectedly;
3. a supposedly low-risk gate requires major architecture changes;
4. many unrelated tests begin timing out;
5. machine resources become unreliable;
6. battery throttling materially slows verification;
7. unexpected orphan processes or port conflicts contaminate testing;
8. a browser flow reveals a material product defect;
9. verification would require weakening tests merely to turn them green;
10. the task has grown beyond its assigned risk tier;
11. source changes would invalidate previously accepted financial assumptions;
12. the session has become too large or tangled to reason about safely.

Stopping is a successful safety action, not a failed gate.

---

## 20. Closeout Standard

Before committing a completed gate:

- required targeted tests pass;
- required browser behavior passes;
- required domain regression passes;
- required final suite passes;
- type/lint/build pass as appropriate;
- Git diff matches assigned scope;
- machine/environment failures are separated from code failures;
- no unexpected background processes remain (see 13.1 and 13.2).

Then:

1. create the gate commit;
2. push the feature branch;
3. report verification evidence;
4. request human acceptance when applicable.

Do not automatically begin the next development gate.

---

## 21. Evidence Retention

Important development evidence should be retained long enough to evaluate whether this protocol improves efficiency.

Track, when practical:

- gate duration;
- model/context size;
- approximate model cost;
- test runtime;
- number of full-suite runs;
- environment failures;
- defects caught by targeted tests;
- defects caught by browser QA;
- defects caught by mutation testing;
- defects caught only by full suites.

Session transcripts may be subject to automatic cleanup.

Archive important session evidence when it is useful for long-term process analysis.

---

## 22. Periodic Protocol Review

This protocol is not immutable.

Review it after approximately:

- 4 to 6 weeks of meaningful development;

or

- one major future Anchor phase;

whichever comes first.

Compare actual results against the D5 evidence baseline.

Questions to revisit:

- Are gates faster?
- Is model usage lower?
- Are browser tests still finding meaningful defects?
- Are full suites catching anything unique?
- Are mutation tests worth their cost?
- Are machine-health stops preventing false investigations?
- Are session sizes staying controlled?
- Are any protocol rules creating unnecessary friction?

Change the protocol when evidence justifies it.

---

## 23. Definition of Success

Anchor development is efficient when:

- financial correctness remains uncompromised;
- realistic workflows are tested;
- serious defects are caught before merge;
- verification effort scales with risk;
- environment failures are identified early;
- full suites are used deliberately;
- Claude sessions remain bounded;
- token usage buys new evidence rather than repeated reassurance;
- main remains a trustworthy working baseline.

The goal is not less rigor.

The goal is better-targeted rigor.
