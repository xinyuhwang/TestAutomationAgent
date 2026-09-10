"""Capture cost/latency/step actuals while a run happens (design-doc §9, §10).

Two rules shape this module.

**Absence is not zero.** Anything the harness cannot observe is declared in
`budget.used.unmeasured` rather than defaulted to 0. A run recorded from inside
Claude Code, for instance, cannot see its own token usage; reporting
`cost_usd: 0` there would turn "unknown" into "free". Counters are only
populated from something that was actually measured — the same
evidence-over-narrative rule the agent applies to the app under test (§1).

**Budget exhaustion is an outcome, not a crash.** `status` becomes
`budget_exhausted` and the partial spans are still emitted, because a run that
burned its budget in one skill is exactly the thing §10 exists to explain.

Usage:

    rec = RunRecord(run_id="run-1", trigger="manual", app_type="traditional",
                    budget={"max_test_cases": 100}, fixture_id="bug-001-...")
    with rec.skill("test-case-generation") as span:
        span.tests_generated = 12
        span.record_tool_call("pytest", "ran generated suite", retries=0)
        span.record_test("test_partial_page", "failed")
    report = rec.to_report(findings=[...])
"""

import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator

# Counters no caller can measure from inside a Claude Code session. They are
# declared unmeasured unless something explicitly supplies them.
LLM_SIDE_COUNTERS = ("llm_calls", "cost_usd")


class BudgetExhausted(Exception):
    """Raised when a limit from design-doc §9 is hit."""


@dataclass
class SkillSpan:
    skill: str
    status: str = "completed"
    duration_seconds: float | None = None
    llm_calls: int | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    cost_usd: float | None = None
    tests_generated: int = 0
    tool_calls: list[dict] = field(default_factory=list)
    tests_executed: list[dict] = field(default_factory=list)

    def record_tool_call(
        self,
        tool: str,
        summary: str | None = None,
        retries: int = 0,
        duration_seconds: float | None = None,
    ) -> None:
        entry: dict[str, Any] = {"tool": tool, "retries": retries}
        if summary:
            entry["summary"] = summary
        if duration_seconds is not None:
            entry["duration_seconds"] = round(duration_seconds, 3)
        self.tool_calls.append(entry)

    def record_test(
        self,
        test_id: str,
        result: str,
        repetitions: int | None = None,
        failures: int | None = None,
        duration_seconds: float | None = None,
    ) -> None:
        entry: dict[str, Any] = {"test_id": test_id, "result": result}
        if repetitions is not None:
            entry["repetitions"] = repetitions
        if failures is not None:
            entry["failures"] = failures
        if duration_seconds is not None:
            entry["duration_seconds"] = round(duration_seconds, 3)
        self.tests_executed.append(entry)

    @property
    def tests_never_executed(self) -> int:
        """Generated but never run — §10's third question."""
        return max(0, self.tests_generated - len(self.tests_executed))

    @property
    def retries(self) -> int:
        return sum(c.get("retries", 0) for c in self.tool_calls)

    def to_dict(self) -> dict:
        out: dict[str, Any] = {"skill": self.skill, "status": self.status}
        if self.duration_seconds is not None:
            out["duration_seconds"] = round(self.duration_seconds, 3)
        for name in ("llm_calls", "tokens_in", "tokens_out", "cost_usd"):
            value = getattr(self, name)
            if value is not None:
                out[name] = value
        if self.tests_generated:
            out["tests_generated"] = self.tests_generated
        if self.tool_calls:
            out["tool_calls"] = self.tool_calls
        if self.tests_executed:
            out["tests_executed"] = self.tests_executed
        return out


class RunRecord:
    def __init__(
        self,
        run_id: str,
        trigger: str,
        app_type: str,
        budget: dict | None = None,
        fixture_id: str | None = None,
        trace_id: str | None = None,
    ):
        self.run_id = run_id
        self.trace_id = trace_id
        self.trigger = trigger
        self.app_type = app_type
        self.fixture_id = fixture_id
        self.budget = dict(budget or {})
        self.spans: list[SkillSpan] = []
        self.status = "completed"
        self._started = time.monotonic()
        self._steps = 0

    def step(self, n: int = 1) -> None:
        """Count a discrete action, enforcing max_steps."""
        self._steps += n
        limit = self.budget.get("max_steps")
        if limit is not None and self._steps > limit:
            self.status = "budget_exhausted"
            raise BudgetExhausted(f"max_steps={limit} exceeded")

    @contextmanager
    def skill(self, name: str) -> Iterator[SkillSpan]:
        span = SkillSpan(skill=name)
        self.spans.append(span)
        started = time.monotonic()
        try:
            yield span
        except BudgetExhausted:
            span.status = "budget_exhausted"
            self.status = "budget_exhausted"
            raise
        except Exception:
            span.status = "error"
            self.status = "error"
            raise
        finally:
            span.duration_seconds = time.monotonic() - started
            self._check_budget()

    def _check_budget(self) -> None:
        limit = self.budget.get("max_test_cases")
        if limit is not None and self.tests_generated > limit:
            self.status = "budget_exhausted"

        limit = self.budget.get("max_runtime_seconds")
        if limit is not None and self.runtime_seconds > limit:
            self.status = "budget_exhausted"

    @property
    def runtime_seconds(self) -> float:
        return time.monotonic() - self._started

    @property
    def tests_generated(self) -> int:
        return sum(s.tests_generated for s in self.spans)

    @property
    def tests_executed(self) -> int:
        return sum(len(s.tests_executed) for s in self.spans)

    @property
    def tests_never_executed(self) -> int:
        return sum(s.tests_never_executed for s in self.spans)

    def used(self) -> dict:
        """budget.used, with anything unobserved declared rather than zeroed."""
        used: dict[str, Any] = {
            "steps": self._steps,
            "runtime_seconds": round(self.runtime_seconds, 3),
            "test_cases": self.tests_generated,
            "retries": sum(s.retries for s in self.spans),
        }

        unmeasured = []
        for name in LLM_SIDE_COUNTERS:
            supplied = [getattr(s, name) for s in self.spans]
            observed = [v for v in supplied if v is not None]
            if observed:
                total = sum(observed)
                used[name] = round(total, 4) if name == "cost_usd" else total
            else:
                unmeasured.append(name)

        if unmeasured:
            used["unmeasured"] = unmeasured
        return used

    def to_report(self, findings: list[dict], **extra: Any) -> dict:
        report: dict[str, Any] = {
            "run_id": self.run_id,
            "trigger": self.trigger,
            "app_type": self.app_type,
            "status": self.status,
        }
        if self.trace_id:
            report["trace_id"] = self.trace_id
        if self.fixture_id:
            report["fixture_id"] = self.fixture_id
        if self.budget or self.spans:
            report["budget"] = {**self.budget, "used": self.used()}
        if self.spans:
            report["skill_spans"] = [s.to_dict() for s in self.spans]
        report["findings"] = findings
        report.update(extra)
        return report
