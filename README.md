# TestAutomationAgent

An AI-native test & reliability evaluation agent: it challenges an application
with generated tests, adversarial scenarios and security probes, traces
failures to root cause, and emits a structured, evidence-backed report.

The central design principle — **the LLM interprets evidence; it does not
become the source of truth.** Full design in [design.md](design.md).

## Status

The **measurement rails** are built. The agent is not.

That order is deliberate. Design-doc §5 says something other than the agent
must be able to check whether its findings are real, from day one — otherwise
the only available quality signal is whether the reports read plausibly, which
is the exact failure mode the project exists to avoid. The rails are also the
cheap half: no LLM calls, so they run on every commit for free.

| Piece | State |
|---|---|
| Finding / eval-report / ground-truth schemas | built |
| Confidence derivation (§6) | built |
| Schema + example validation in CI | built |
| 3-bug fixture suite (§14) | built |
| Ground-truth scorer (§14) | built |
| Cost/latency/step capture + per-skill spans (§9, §10) | built |
| `test-case-generation` skill | built, one run scored |
| `defect-to-architecture-tracing` skill | **not started** (done by hand in the bug-001 run) |
| Remaining skills (adversarial, security, eval-doc, integration) | **not started** |
| GitHub Action that runs the agent on a PR | **not started** |

## Layout

```text
finding.schema.json          a single structured finding (design-doc §4, §11)
eval_report.schema.json      one full run: metadata, budget outcome, spans, findings
ground_truth.schema.json     the answer key format for a fixture app

.claude/skills/              the agent's skills (§13)
  test-case-generation/      generate + execute targeted tests, report evidence

examples/                    positive and negative examples of both schemas
fixtures/                    agent-visible apps with seeded defects (§14)
harness/
  confidence.py              derive confidence from verification status (§6)
  run_record.py              capture steps/latency/cost + per-skill spans (§9, §10)
  junit.py                   pytest JUnit XML -> recorded test results
  validate.py                schema / example / ground-truth checks
  score.py                   score a report against ground truth
  ground_truth/              the answer keys — deliberately outside fixtures/
  tests/                     tests for the harness itself
```

## Usage

```bash
pip install -r requirements-dev.txt

python -m harness.validate                     # schemas, examples, ground truth
python -m pytest                               # harness tests
python -m harness.score <report.json>          # score a run against ground truth
```

Try the scorer against the worked example, a report that gets `bug-001`
entirely right:

```bash
python -m harness.score examples/eval_report_valid.json
```

## Two rules worth knowing before adding to this

**Confidence is derived, never written by the model.** Report assembly calls
`harness.confidence.derive_confidence(verification_status)`; the model does not
emit the field. The schema additionally enforces a band per verification
status, and those bands are read *out of* `finding.schema.json` by
`confidence.py`, so there is one place to change them and no way for schema and
code to drift.

**Negative examples must assert a specific violation.** Each file in
`examples/` named `*_invalid_*` has an entry in `EXPECTED_VIOLATIONS` in
[harness/validate.py](harness/validate.py) naming the error it must produce.
Without that, an unrelated mistake keeps the example red while the rule it was
written to prove quietly goes untested.

## What the fixtures measure

Per design-doc §14, for each seeded defect: was it detected, correctly
classified by type/location/concern, and correctly root-caused — and did the
agent avoid blaming code that is known to be correct?

The scorer separates three outcomes that are easy to conflate:

- **false positive** — the finding blames code the ground truth marks correct.
- **unattributed** — the finding matches no seeded defect and no control. Not
  scored as wrong; it may be a real defect nobody seeded.
- **detected but misjudged** — found the right site, got an axis wrong.
  Detection and classification are separate metrics, per §11.

`bug-003` is the sharp one: the application is correct and the *test* is at
fault. Reporting a confirmed application defect there is scored as wrong rather
than as confident, which is how §11's "flakiness itself is the finding" becomes
a number instead of an aspiration.

## Cost and latency capture

`RunRecord` records a run while it happens, so `budget.used` and the per-skill
spans come from measurement rather than recollection:

```python
from harness.run_record import RunRecord

rec = RunRecord(run_id="run-1", trigger="manual", app_type="traditional",
                budget={"max_test_cases": 100})
with rec.skill("test-case-generation") as span:
    span.tests_generated = 16
    span.record_tool_call("pytest", "ran generated suite", retries=0)
report = rec.to_report(findings=[...])
```

**Absence is not zero.** Anything the run could not observe is listed in
`budget.used.unmeasured` instead of being defaulted to `0`. A run recorded from
inside Claude Code cannot see its own token usage, and reporting `cost_usd: 0`
there would turn "unknown" into "free" — so the field is omitted and declared.
Populating it with an estimate is forbidden for the same reason the agent may
not self-report confidence: once written down, a guess is indistinguishable
from a measurement.

Spans exist because flat totals cannot answer §10's questions. `tool_calls[].retries`
makes a retry loop attributable to a specific skill, and `tests_generated`
compared against `tests_executed` surfaces tests that were written and never
run — a silent failure that would otherwise look like a cheaper run.

## Worked example

[examples/eval_report_valid.json](examples/eval_report_valid.json) is a real
recorded run of `test-case-generation` against
`fixtures/bug-001-implementation-bug`, not a hand-written sample: 16 generated
cases, 11 failed, 5 passed, all 16 executed, 7 steps, 0.32s wall clock, with
`llm_calls` and `cost_usd` declared unmeasured. Score it with:

```bash
python -m harness.score examples/eval_report_valid.json
```

## Next

`defect-to-architecture-tracing` — the bug-001 run's classification and root
cause were assembled by hand, and that is the step that most needs a written
output contract, since it is where the temptation to conclude early lives (§5).

Then a genuinely uncontaminated measurement. The bug-001 run scores 1.0 on
every axis, but the fixture and its answer key were authored in the same
session that ran against them, so that score demonstrates the *pipeline* works
end to end — it is not evidence about detection ability. The first real
measurement needs a fixture whose defect the runner has not seen.
