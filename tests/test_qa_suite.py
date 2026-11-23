"""The quality-audit suite as ordinary tests: every case in qa/ must still behave as its expectation says.

qa/run_qa.py runs each message through the real pipeline (template mode, throw-away database) and compares the outcome with
the expectation written in qa/cases*.py. This file turns that into pass/fail tests so a later change that breaks an
old behaviour is caught by `pytest`. See documentation/QA_REPORT.md for what the cases are and why.

KNOWN_FAILURES lists cases that are KNOWN not to pass. They are marked xfail(strict=True): if one is fixed, the test
fails until it is removed from the list, so the list can only shrink honestly.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from qa.cases import ROUND1  # noqa: E402
from qa.cases_round2 import ROUND2  # noqa: E402
from qa.cases_round3 import ROUND3  # noqa: E402
from qa.cases_round4 import ROUND4  # noqa: E402
from qa.run_qa import run_cases  # noqa: E402

ALL_CASES = ROUND1 + ROUND2 + ROUND3 + ROUND4

KNOWN_FAILURES = {
    "R-G2": "A requested time that is outside the clinic's opening hours (Sunday 5 PM, clinic closes at 2 PM) is not detected; "
            "the held draft echoes the time. Nothing is confirmed and a person reviews it, but the draft should say it is outside hours.",
}


@pytest.fixture(scope="module")
def results():
    return {r.id: r for r in run_cases(ALL_CASES)}


def test_there_are_at_least_30_cases_in_every_round_and_ids_are_unique():
    ids = [c.id for c in ALL_CASES]
    assert len(ids) == len(set(ids)), "duplicate case ids"
    assert len(ROUND1) >= 30 and len(ROUND2) >= 30 and len(ROUND3) >= 30 and len(ROUND4) >= 30


@pytest.mark.parametrize("case", ALL_CASES, ids=[c.id for c in ALL_CASES])
def test_case(case, results, request):
    if case.id in KNOWN_FAILURES:
        request.applymarker(pytest.mark.xfail(strict=True, reason=KNOWN_FAILURES[case.id]))
    res = results[case.id]
    assert res.passed, f"{case.message!r}\n  " + "\n  ".join(res.problems + [f"INVARIANT: {p}" for p in res.invariant_problems])


def test_no_case_ever_broke_a_safety_invariant(results):
    """Independent of every case's own expectation: nothing unverified was sent, no unknown price/doctor, no booking claim."""
    assert [r.id for r in results.values() if r.invariant_problems] == []
