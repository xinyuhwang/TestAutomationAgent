---
name: test-case-generation
description: Generate and execute targeted tests for a diff or component — happy path, boundary values, equivalence classes and spec-derived invariants — chosen by what existing tests do NOT cover. Produces executed tests and observed evidence, never conclusions. Use when asked to test a PR diff, find untested behaviour, or produce evidence for an evaluation report.
---

# Test Case Generation

Generate tests that could plausibly fail, execute them, and report what was
observed. This skill produces **evidence, not conclusions** — classification
and root cause belong to `defect-to-architecture-tracing`, which consumes this
skill's output.

## The rule that makes this skill worth running

**Target the gap between the spec and the existing tests.** A test that
duplicates existing coverage cannot find anything; it only costs money. Before
generating anything, read the existing suite and write down what it does *not*
exercise. Every generated test must name the gap it targets.

If the existing suite already fails, stop and report that instead. There is
nothing to generate: the defect is already visible.

## Pipeline

Follow in order (design-doc §7). Do not skip to writing tests.

1. **Gather** — spec (README/docstrings/type hints), the diff if scoped to one,
   the existing tests, and the architecture around the target.
2. **Extract the contract.** List what the code *promises*, in the spec's own
   words. Quote it. Invariants stated in prose ("every item must appear on some
   page", "a customer must never be charged more than they authorised") are the
   highest-value test sources, because they are checkable and rarely tested
   directly.
3. **Map existing coverage** against that contract. Produce a gap list.
4. **Generate test hypotheses** — for each gap, what input class could break
   the promise? Prioritise:
   - **Spec invariants** — properties that must hold across all inputs.
     Strongest signal; a failure here is unambiguous.
   - **Equivalence classes** — partition each input. For integers: zero,
     one, many, negative, and *the remainder case* (`n % k != 0`), which is
     the single most commonly untested partition.
   - **Boundaries** — at, either side of, and across every limit
     (`k-1`, `k`, `k+1`), plus empty and maximum.
   - **Cross-function consistency** — two functions deriving from the same
     quantity must agree. Bugs hide in the disagreement, not in either
     function alone.
   - **Error paths** — validation that exists but is never triggered.
5. **Write executable tests.** Assert the behaviour the *spec* requires, never
   the behaviour the current code exhibits — otherwise you encode the bug as
   expected. Give each test a name stating the property, and a docstring naming
   the gap it fills.
6. **Execute.** A generated test that never runs is worth nothing.
7. **Triage each result** against these four questions, in order:
   - Did it execute at all, or error on import/setup?
   - Does it exercise behaviour the existing suite did not?
   - Did it expose a failure?
   - **Is the failure real, or is the test wrong?** Re-read the spec before
     believing your own assertion. A test asserting something the contract
     never promised is a test defect, and reporting it as an application bug is
     the most expensive mistake this skill can make.

## Where to write

Workspace only (design-doc §8). Copy the target into a workspace and generate
there. Never add generated tests to the target's own suite — a fixture or repo
whose committed tests now catch the defect has stopped being a measurement.

## Instrumentation

Record the run as you go, so cost and latency come from measurement rather
than recollection:

```python
from harness.run_record import RunRecord

rec = RunRecord(run_id=..., trigger="manual", app_type="traditional",
                budget={"max_test_cases": 100}, fixture_id=...)
with rec.skill("test-case-generation") as span:
    span.tests_generated = <count written>
    span.record_tool_call("pytest", "<what was run>", retries=0)
    span.record_test("<test id>", "passed|failed|error|skipped")
```

`tests_generated` must be the number written, counted independently of the
number executed — the gap between them is a silent failure this skill is
required to surface, not a smaller bill (§10).

Do not populate `llm_calls` or `cost_usd` with estimates. If the runtime cannot
observe them, leave them unset; `RunRecord` declares them unmeasured. A
guessed cost is indistinguishable from a measured one once written down.

## Output

```yaml
contract:        # quoted promises the target makes
coverage_gaps:   # what the existing suite does not exercise
generated:       # test id -> the gap it targets
observations:    # test id -> result, plus the concrete numbers observed
```

Observations feed `evidence[]` in a finding. Write what happened
(`page_count(10, 3) returned 3, expected 4`), with actual values — not what it
means. Do not write `classification`, `root_cause`, or `confidence`: those are
produced downstream, and `confidence` is always derived
(`harness.confidence.derive_confidence`), never chosen (§6).
