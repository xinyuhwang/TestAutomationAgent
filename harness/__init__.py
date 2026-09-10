"""Measurement rails for the evaluation agent.

The agent evaluates applications; this package evaluates the agent
(design-doc §5, §14). Nothing here calls an LLM — it is all deterministic,
so it can run on every commit for free.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

FINDING_SCHEMA = REPO_ROOT / "finding.schema.json"
EVAL_REPORT_SCHEMA = REPO_ROOT / "eval_report.schema.json"
GROUND_TRUTH_SCHEMA = REPO_ROOT / "ground_truth.schema.json"

EXAMPLES_DIR = REPO_ROOT / "examples"

# The fixture apps as the agent sees them. Nothing in here reveals the seeded
# defect, so a fixture directory can be handed to the agent verbatim.
FIXTURES_DIR = REPO_ROOT / "fixtures"

# Answer key, deliberately kept outside FIXTURES_DIR: an agent working inside a
# fixture cannot read its way to the answer, which is a property of the layout
# rather than of anyone remembering to exclude a file.
GROUND_TRUTH_DIR = Path(__file__).resolve().parent / "ground_truth"
