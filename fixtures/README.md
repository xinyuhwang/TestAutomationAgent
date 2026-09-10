# Fixture apps

Small applications with seeded, known defects, used to measure whether the
evaluation agent actually finds real problems (design-doc §14).

Everything in this directory is **agent-visible**. Nothing here states what the
seeded defect is. The answer key lives in [`harness/ground_truth/`](../harness/ground_truth/),
outside this tree, so an agent working inside a fixture cannot read its way to
the answer.

| Fixture | Seeded category | What it tests |
|---|---|---|
| `bug-001-implementation-bug` | implementation bug | Can the agent find a wrong line, and reach the untested boundary that exposes it? |
| `bug-002-architecture-defect` | architecture defect | Can the agent tell a bad *composition* from a bad line? No single statement is wrong. |
| `bug-003-flaky-test` | flaky test | Can the agent resist blaming correct application code for an intermittent failure? |

## The property that makes a fixture useful

**Every existing test in every fixture passes.** If the shipped suite already
caught the defect, the fixture would measure nothing — the agent could report
the failure without having generated anything. Each defect sits in a boundary
or a composition the existing tests never reach, so finding it requires
generating a genuinely new test.

Verify at any time:

```bash
cd fixtures/bug-001-implementation-bug && python -m pytest   # 9 passed
cd fixtures/bug-002-architecture-defect && python -m pytest  # 7 passed
```

## bug-003 is intentionally flaky

`bug-003-flaky-test` contains one test that fails roughly 20% of the time. That
is the point of the fixture, so it is excluded from this repo's own CI by the
root [`pytest.ini`](../pytest.ini) (`testpaths = harness/tests`) — otherwise
this repo's build would flap for reasons that have nothing to do with this
repo.

The flake rate is timing-dependent and will differ across machines. Any
detection logic must re-run the suite and reason about a distribution, never a
single observation — which is exactly the `single_observation` vs
`reproduced_intermittently` distinction the finding schema encodes.
