# Design Doc: AI-Native Test & Reliability Evaluation Agent

**Status:** Draft v1
**Owner:** Xinyu Wang
**Last updated:** 2026-09-10

---

## 1. Summary

An agent that challenges applications — both traditional web/backend systems and agentic AI systems — with generated test cases, adversarial/corner-case scenarios, and security probes; traces failures back to root cause (implementation bug vs. architecture defect vs. flaky test); and produces a structured, evidence-backed evaluation report. It runs inside CI/CD (GitHub Actions + Claude Code), not as a chat bot, and is designed from day one to be measurable against known-defect fixture applications rather than judged only on how plausible its reports sound.

The central design principle: **the LLM interprets evidence; it does not become the source of truth.** Every finding must be traceable to something that actually happened — a failing test, a trace, a reproduced failure — not just a fluent explanation.

---

## 2. Goals / Non-Goals

### Goals (v1)
- Given a PR diff, generate targeted tests, execute them, and produce a structured eval report.
- Distinguish implementation bug / architecture defect / flaky test / test defect / security issue, with evidence for each classification.
- Support both traditional apps and agentic apps under the same report schema.
- Be measurable: ship with a small fixture suite of seeded, known defects so detection accuracy can be checked, not assumed.
- Fit into existing CI — PR comment + artifact, no new always-on infrastructure.

### Non-Goals (v1 — explicitly deferred)
- Multi-agent orchestration (manager agent + specialist agents). Define the *interface* now; implement later.
- Discord/Slack as primary interface. Notification-only, added later if at all.
- Long-term agent memory, vector DB.
- Autonomous production deployment or code merging.
- Production database or production network access of any kind.
- A dashboard/UI. Markdown + JSON artifacts are the interface for v1.

---

## 3. Core Design Principles

1. **Evidence is the source of truth; the model interprets it.** Tests, logs, traces, diffs, reproductions — not model narrative — ground every claim.
2. **Don't let the agent conclude a root cause too early.** Every conclusion must show its work: evidence → hypothesis → investigation → verified (or not) conclusion.
3. **Separate orthogonal dimensions of a finding.** Where a defect lives, what property it violates, how bad it is, how sure we are, and whether a control gap (e.g. missing human approval) exists are five different axes — never collapse them into one "layer" field.
4. **Confidence is derived, not declared.** The model doesn't get to self-report a probability; confidence is computed from what verification actually occurred.
5. **The agent evaluates the app; something else must evaluate the agent.** Ship a way to check whether findings are real from day one, however small.
6. **Executing code and calling tools is a safety-relevant capability.** Treat permissions, budgets, and sandboxing as first-class from v1, not hardening added later.

---

## 4. Finding Schema

Each finding is a structured record, not free text:

```yaml
id: SEC-017

location:
  component: tool_execution
  module: database_tool
  # location vocabulary: agent_loop | orchestration | evaluation
  #                       | tooling | application | data | infrastructure

concerns:
  - security
  - authorization
  # concern vocabulary: reliability | security | observability | latency
  #                      | cost | correctness | safety

control_gap:
  human_in_the_loop: true
  authorization: true
  # control_gap vocabulary: human_in_the_loop | authorization | validation | approval

classification:
  type: security_issue
  # type vocabulary: implementation_bug | architecture_defect
  #                   | flaky_test | test_defect | security_issue

evidence:
  - "test reproduced race condition 7/10 times under 20 concurrent requests"
  - "trace_id abc123: SQL executed twice for single request"

hypotheses:
  - "retry policy may cause duplicate tool invocation"

investigations:
  - "reproduced with retry disabled; duplicate execution disappeared"

root_cause:
  status: confirmed        # confirmed | unconfirmed | inconclusive
  explanation: "retry executed before original call's transaction committed"

severity: P1                # P0-P3, impact-based
confidence: 0.91             # derived from verification status, see §6
verification:
  status: reproduced         # reproduced | reproduced_intermittently
                              # | hypothesis_only | single_observation
```

For agentic apps, `location.component` typically resolves to one of `agent_loop | orchestration | tool_execution | evaluation_layer`; for traditional apps it typically resolves to `api | business_logic | data_layer | infrastructure`. Same schema, different vocabulary populated based on app type — no separate report format.

---

## 5. Root-Cause Investigation Protocol

The agent is not permitted to write a `root_cause` with `status: confirmed` unless an `investigations` entry documents an actual reproduction step. The enforced sequence:

```
Evidence           what was observed (test failure, log, trace, diff)
   ↓
Hypothesis         what the agent believes caused it
   ↓
Investigation      what the agent did to test the hypothesis
   ↓
Conclusion         confirmed / unconfirmed / inconclusive, with explanation
```

If no investigation was performed, `root_cause.status` must be `unconfirmed` and the finding is reported as a hypothesis, not a conclusion. This is enforced by the skill's output contract, not left to model discretion.

---

## 6. Confidence Model

Confidence is **computed**, not asked of the model as a free-floating number. Baseline mapping from `verification.status`:

| verification.status | confidence |
|---|---|
| reproduced | 1.0 |
| reproduced_intermittently | 0.6 |
| hypothesis_only | 0.3 |
| single_observation | 0.2 |

Severity and confidence are reported independently and never merged — a P0 at 0.55 confidence and a P1 at 0.98 confidence are both valid and mean very different things for triage.

---

## 7. Skills

| Skill | Purpose | App-type handling |
|---|---|---|
| `test-case-generation` | Happy path, boundary, equivalence classes from diff/spec, existing tests, architecture | Traditional: function/API contracts. Agentic: tool schemas, expected agent-loop transitions |
| `adversarial-testing` | Corner cases, malformed input, concurrency, resource limits | Traditional: fuzz-style. Agentic: adversarial prompts, tool-result injection, malformed tool schemas |
| `defect-to-architecture-tracing` | Evidence → hypothesis → investigation → root cause (§5) | Same protocol both types; location vocabulary differs |
| `security-review` | OWASP-style pass + stack-specific checks | Agentic apps add prompt-injection surface, tool-permission scope, secrets-in-tool-results |
| `integration-coordination` | **Interface only in v1.** Defines the handoff contract (`task_spec` in → `findings` out) for a future coding/deploy agent | N/A yet — no second agent exists |
| `eval-doc-generation` | Assembles findings into the structured report (§4), including new/known/regression diffing | Shared schema, app-type-aware vocabulary |

Test generation's fuller pipeline (target for hardening phase, not v1 blocker):

```
requirement/spec + diff + architecture + existing tests
   → test hypothesis generation
   → test case generation
   → executable test
   → run → observe
   → did it execute? exercise new behavior? expose a failure? was the failure real?
```

---

## 8. Execution Policy (Permissions)

Because the agent executes code, runs tests, and performs adversarial/security probing, it operates under an explicit, restrictive policy — not implicit trust:

```yaml
execution_policy:
  filesystem:
    read: true
    write: workspace_only

  network:
    default: deny
    allowed:
      - staging.example.com

  secrets:
    production: deny
    staging: limited

  destructive_operations:
    default: deny

  human_approval_required:
    - database_write
    - production_access
    - external_side_effect
```

Recursive property worth preserving: the agent should be able to report both "the application under test lacks human-in-the-loop control here" *and* "I am not permitted to take this action without human approval" about itself. Same control-gap concept applied to itself and to the system it's evaluating.

---

## 9. Budgets

Agentic failure modes (unbounded retry/think loops) are different from traditional program failure modes, so every run has explicit limits, and hitting them is a first-class outcome rather than an unexplained failure:

```yaml
budget:
  max_steps: 50
  max_llm_calls: 30
  max_runtime_seconds: 600
  max_test_cases: 100
  max_retries: 3
  max_cost_usd: 2.00
```

A run that exhausts budget reports `status: budget_exhausted`, distinct from `status: completed` or `status: error`.

---

## 10. Observability (of the agent itself)

The agent under test gets evaluated for observability; the testing agent needs the same property applied to itself, captured per run:

```
run_id, trace_id
  └── skill (test-generation, adversarial-testing, defect-tracing, eval-doc, ...)
        └── LLM call (tokens, latency, cost)
        └── tool call (input/output summary, retry count)
        └── test executed (result)
```

This is what makes questions like "why did this run cost $1.83," "which skill triggered the retry loop," and "how many tests were generated but never executed" answerable — which directly feeds the cost/latency/reliability concerns the agent itself reports on for the target application.

---

## 11. Classification Taxonomy Details

Rather than one `layer` field, findings are tagged along independent axes:

- **Location** — where the defect lives: `agent_loop | orchestration | evaluation | tooling | application | data | infrastructure`
- **Concern** — what property is violated: `reliability | security | observability | latency | cost | correctness | safety`
- **Control gap** — whether a process/authorization safeguard is missing: `human_in_the_loop | authorization | validation | approval`
- **Severity** — impact: `P0–P3`
- **Confidence** — derived from verification (§6)
- **Verification** — evidence strength: `reproduced | reproduced_intermittently | hypothesis_only | single_observation`

Flaky tests get their own explicit classification rather than being forced into "implementation bug" or silently ignored:

```yaml
classification:
  type: flaky_test
  confidence: 0.87
evidence:
  repetitions: 20
  failures: 3
  failure_pattern: "fails only under >15 concurrent requests"
```

The agent's report should be able to say, plainly: *"This test fails intermittently under identical inputs; there is not yet sufficient evidence to classify the application behavior as defective."*

---

## 12. Architecture

```
                    ┌────────────────────┐
                    │   GitHub / CI      │
                    └─────────┬──────────┘
                              │
                              ▼
                 ┌────────────────────────┐
                 │     Agent Runtime      │   (config passed to Claude Code
                 │  state / budget / ACL  │    invocation — not a standing
                 │  retries / tracing     │    service in v1)
                 └───────────┬────────────┘
                             │
             ┌───────────────┼────────────────┐
             ▼               ▼                ▼
        Test Gen       Adversarial       Security
          Skill           Skill            Skill
             │               │                │
             └───────────────┼────────────────┘
                             ▼
                    ┌─────────────────┐
                    │ Test Sandbox    │
                    └────────┬────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │ Evidence Record │   (structured JSON CI artifact —
                    └────────┬────────┘    not a database in v1)
                             │
                ┌────────────┼─────────────┐
                ▼            ▼             ▼
             Defect      Architecture    Eval
             Tracing      Analysis       Engine
                │            │             │
                └────────────┼─────────────┘
                             ▼
                    ┌─────────────────┐
                    │ Eval Report     │
                    │ (schema §4)     │
                    └────────┬────────┘
                             │
                    ┌────────┴────────┐
                    ▼                 ▼
                 GitHub PR      (later: Discord/Slack
                 comment         notification only)
```

**Deliberately not new infrastructure in v1:** "Agent Runtime" = config/flags to the CI-invoked agent process. "Evidence Record" = a structured JSON artifact per run, not a database. The one piece of persistent state accepted early is a `findings.json` baseline checked into the repo or carried as a CI artifact, used purely for new/known/regression diffing in PR comments.

---

## 13. Deployment

- Skills live in-repo (e.g. `.claude/skills/`).
- GitHub Action triggers on PR open/update: runs the diff-scoped skills, posts a PR comment summarizing **new / known / regression** findings, attaches the full structured report as a CI artifact.
- Scheduled (nightly) run does the heavier adversarial + security pass across the full app, not just the diff.
- Discord/Slack, if added later, is a thin push of the eval-doc summary — not the source of truth and not built in v1.

---

## 14. Evaluating the Evaluator

The agent evaluates applications; a separate, small harness evaluates the agent, using fixture apps with seeded, known defects.

**v1 fixture set (small, just enough to validate discrimination between categories):**

```
fixture-app/
├── bug-001-implementation-bug     (e.g. off-by-one)
├── bug-002-architecture-defect    (e.g. retry duplicates side effect)
└── bug-003-flaky-test             (intermittent under concurrency)
```

For each: did the agent detect it? Correctly classify its type/location/concern? Correctly identify root cause? Avoid false positives on the other fixtures?

**Deferred to a hardening phase (post-v1), not a prerequisite to shipping:**
- Full 6+ bug fixture suite (adding auth bypass, bad tool schema, missing timeout, agent-loop infinite retry).
- Mutation testing (`>` → `>=`, remove auth check, disable retry, return stale cache, remove null handling) to measure raw detection rate at scale, complementing the fixture suite's root-cause-accuracy check.
- Aggregate metrics: defect detection rate, false positive rate, root-cause accuracy, security finding precision.

```
                   ┌───────────────────┐
                   │ Evaluation        │
                   │ Harness           │
                   └─────────┬─────────┘
                             ▼
                   ┌───────────────────┐
                   │ Testing Agent     │
                   └─────────┬─────────┘
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
           Tests          Findings       Reports
              └──────────────┼──────────────┘
                             ▼
                   Ground-truth comparison
```

---

## 15. Multi-Agent Interface (defined now, not implemented)

`integration-coordination` skill contract:

```yaml
# input
task_spec:
  scope: <diff | full_app | component>
  target: <path/component identifier>
  constraints: <execution_policy reference, budget reference>

# output
findings: <list of finding records, schema per §4>
```

Nothing is implemented behind this beyond the current single agent. The value is that a future coding agent, deploy agent, or specialist security agent can plug into this contract without a redesign — avoiding an early multi-agent system whose main failure mode becomes "why did Agent B misunderstand Agent A" instead of testing the target application.

---

## 16. V1 Vertical Slice (build this first)

```
GitHub PR
   → understand diff
   → generate 5–20 targeted tests
   → execute
   → collect evidence
   → investigate failures (evidence → hypothesis → investigation → conclusion)
   → classify (implementation bug / architecture defect / flaky test / test defect / security issue)
   → structured eval report (§4 schema)
   → PR comment (new / known / regression)
   → check against 3-bug fixture suite (§14)
```

**Explicitly after v1**, in rough order: adversarial testing → security review → integration-coordination contract hardening → full fixture suite + mutation testing → notification layer (Discord/Slack) → multi-agent execution.

---

## 17. Open Questions

- Exact vocabulary completeness for `location` and `concern` enums — likely needs iteration once real findings start populating them.
- Where the `findings.json` baseline lives long-term (repo-committed vs. CI cache vs. small external store) once run volume grows past what a repo file comfortably tracks.
- Cost/latency budget defaults (§9) — starting numbers are guesses and should be tuned against actual v1 runs.
- Whether traditional-app and agentic-app test generation eventually need different skills rather than one skill with two vocabularies, once real usage shows how much the reasoning actually diverges.
