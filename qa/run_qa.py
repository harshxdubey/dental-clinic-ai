"""Run the quality-audit cases through the REAL pipeline and record everything about each one.

    python -m qa.run_qa                       # round 1, prints a summary
    python -m qa.run_qa --round 2 --json qa/results/round2.json
    python -m qa.run_qa --only A1 D5 --verbose

What it does for every case (all in a throw-away database and a throw-away copy of data/ - your real
demo database and knowledge base are never touched):

  1. sends the message through `webhook.handle_incoming_message`, exactly as the chat page / Meta would;
  2. records the intent, the retrieved knowledge entries, the AI's answer, the verification result and
     whether the answer was auto-replied or held for a person;
  3. compares that with the expectation written in qa/cases.py;
  4. ALSO checks a few independent safety invariants that do not depend on the case's own expectations
     (see `invariant_problems`) - they are a second opinion that does not trust the validator.

Template mode only (USE_LLM = False): no API key, no network. The Claude-written-answer path is NOT exercised.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend import config  # noqa: E402

from qa.cases import AUTO, ESCALATED, PENDING, ROUND1, Case  # noqa: E402
from qa.cases_round2 import ROUND2  # noqa: E402
from qa.cases_round3 import ROUND3  # noqa: E402
from qa.cases_round4 import ROUND4  # noqa: E402

MONEY = re.compile(r"(?:₹|rs\.?|inr)\s?(\d[\d,]*)", re.I)
MARKERS = ["SOURCES:", "ANSWER:", "NO_ANSWER", "<sources>", "system prompt"]
ENTRY_ID = re.compile(r"\b(?:treatment|doctor|faq|clinic):[a-z_]+\b")


@dataclass
class Result:
    id: str
    category: str
    message: str
    intent: str = ""
    intents: list = field(default_factory=list)
    confidence: float = 0.0
    urgent: bool = False
    sources: list = field(default_factory=list)      # [{"id","score","method","used"}]
    answer_kind: str = ""                            # what the "answer" field holds
    answer: str = ""                                 # what a patient would read (sent reply, else the draft)
    sent_text: str = ""                              # what was actually delivered to the patient ("" = nothing)
    draft: str = ""                                  # the AI's draft (what a receptionist sees)
    decision: str = ""                               # auto_send / needs_approval / escalate
    status: str = ""                                 # auto_replied / pending_approval / escalated
    failed_checks: list = field(default_factory=list)  # [{"name","severity","detail"}]
    reasons: list = field(default_factory=list)
    expected_routes: list = field(default_factory=list)
    expected_summary: str = ""
    actual_summary: str = ""
    passed: bool = False
    problems: list = field(default_factory=list)
    invariant_problems: list = field(default_factory=list)
    round: str = ""


# ----------------------------------------------------------------------------------------------------
def _walk(node, key=""):
    """Yield (key, value) for every scalar in nested JSON."""
    if isinstance(node, dict):
        for k, v in node.items():
            yield from _walk(v, k)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v, key)
    else:
        yield key, node


def known_amounts(data_dir: Path) -> set[int]:
    """Every rupee amount that appears anywhere in the knowledge base (from fields or text)."""
    amounts: set[int] = set()
    for path in data_dir.glob("*.json"):
        for key, value in _walk(json.loads(path.read_text(encoding="utf-8"))):
            if isinstance(value, (int, float)) and "price" in key.lower():
                amounts.add(int(value))
            elif isinstance(value, str):
                amounts.update(int(m.replace(",", "")) for m in MONEY.findall(value))
    return amounts


def doctor_names(data_dir: Path) -> set[str]:
    doctors = json.loads((data_dir / "doctors.json").read_text(encoding="utf-8"))
    items = doctors if isinstance(doctors, list) else next(v for v in doctors.values() if isinstance(v, list))
    return {d["name"].lower() for d in items}


def invariant_problems(res: Result, amounts: set[int], doctors: set[str], notices: set[str]) -> list[str]:
    """Rules that must hold for EVERY message, whatever the case expected. Independent of the validator."""
    problems = []
    visible = [t for t in (res.sent_text,) if t]
    # 1. an automatic AI answer may never go out with a failed blocking/warning check
    if res.status == AUTO:
        bad = [c["name"] for c in res.failed_checks if c["severity"] in ("block", "warn")]
        if bad:
            problems.append(f"auto-replied although checks failed: {', '.join(bad)}")
        if res.sent_text.strip() != res.draft.strip():
            problems.append("auto-reply text differs from the verified draft")
    # 2. a held message may only ever have received a fixed notice
    elif res.sent_text and res.sent_text not in notices:
        problems.append("held message received something other than the fixed notice")
    # 3. everything a patient receives: only known prices, no unknown doctors, no internal markers
    for text in visible:
        for raw in MONEY.findall(text):
            if int(raw.replace(",", "")) not in amounts:
                problems.append(f"sent a price that is not in the knowledge base: {raw}")
        for name in re.findall(r"\bDr\.?\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?", text):
            bare = name.lower().replace("dr.", "").replace("dr ", "").strip()
            if not any(bare in d for d in doctors):
                problems.append(f"sent a doctor name that is not in the knowledge base: {name}")
        for marker in MARKERS:
            if marker.lower() in text.lower():
                problems.append(f"sent an internal marker: {marker}")
        if ENTRY_ID.search(text):
            problems.append("sent an internal knowledge-base id")
    # 4. nothing may claim a booking/cancellation/availability as fact (independent regex list)
    for text in visible:
        if re.search(r"\b(appointment|appointments|booking|slot)\b.{0,40}\b(is|has been|have been|are)\s+(confirmed|booked|cancelled|canceled)\b(?!\s+(by|once|only|after|when|as soon))", text, re.I) \
                or re.search(r"\byour appointment (is|has been) (confirmed|booked)\b(?!\s+(by|once))", text, re.I) \
                or re.search(r"\b(is|are) available (today|tomorrow|tonight|on (mon|tues|wednes|thurs|fri|satur|sun)day)\b", text, re.I):
            problems.append("sent text that claims an appointment is confirmed/booked/available")
    return problems


def evaluate(case: Case, res: Result) -> list[str]:
    """Compare the actual outcome with the case's expectation. Returns the list of reasons it failed."""
    problems = []
    if res.status not in case.routes:
        problems.append(f"route: expected {' or '.join(sorted(case.routes))}, got {res.status}")
    if case.intent_any and res.intent not in case.intent_any:
        problems.append(f"intent: expected one of {case.intent_any}, got {res.intent}")
    missing = [i for i in case.intents_include if i not in res.intents and i != res.intent]
    if missing:
        problems.append(f"intents: missing {missing} (detected {res.intents})")
    got_ids = {s["id"] for s in res.sources}
    miss_src = [s for s in case.sources_include if s not in got_ids]
    if miss_src:
        problems.append(f"sources: not retrieved {miss_src}")
    shown = (res.sent_text if res.sent_text.strip() == res.draft.strip() else res.sent_text + "\n" + res.draft).lower()
    for needle in case.must_contain:
        if needle.lower() not in shown:
            problems.append(f"missing in reply/draft: {needle!r}")
    for needle in case.must_not_contain:
        if needle.lower() in shown:
            problems.append(f"forbidden text present: {needle!r}")
    for snippet in case.at_most_once:
        if shown.count(snippet.lower()) > 1:
            problems.append(f"repeated {shown.count(snippet.lower())} times: {snippet!r}")
    for pattern in case.must_not_match:
        found = re.search(pattern, shown, re.I)
        if found:
            problems.append(f"forbidden claim (pattern): {found.group(0)!r}")
    if case.urgent is not None and res.urgent != case.urgent:
        problems.append(f"urgent flag: expected {case.urgent}, got {res.urgent}")
    return problems


# ----------------------------------------------------------------------------------------------------
class Sandbox:
    """A throw-away copy of the knowledge base + an empty database, with the settings the audit assumes."""

    def __enter__(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="clinic_qa_"))
        shutil.copytree(ROOT / "data", self.tmp / "data", ignore=shutil.ignore_patterns("backups"))
        self.saved = {k: getattr(config, k) for k in
                      ("DATA_DIR", "DATABASE_PATH", "USE_LLM", "AUTO_REPLY_DEFAULT", "MIN_CLASSIFIER_CONFIDENCE",
                       "MIN_SOURCE_SCORE", "WHATSAPP_MODE", "APPROVE_MODEL_ANSWERS")}
        config.DATA_DIR = self.tmp / "data"
        config.DATABASE_PATH = self.tmp / "qa.db"
        config.USE_LLM = False
        config.AUTO_REPLY_DEFAULT = True
        config.MIN_CLASSIFIER_CONFIDENCE = 0.7
        config.MIN_SOURCE_SCORE = 0.5
        config.WHATSAPP_MODE = "simulated"
        config.APPROVE_MODEL_ANSWERS = False
        from backend import database as db
        db.init_db()
        return self

    def __exit__(self, *exc):
        for k, v in self.saved.items():
            setattr(config, k, v)
        shutil.rmtree(self.tmp, ignore_errors=True)


def run_cases(cases: list[Case], round_name: str = "") -> list[Result]:
    from backend import database as db
    from backend import webhook
    from backend.ai_response import FALLBACK_REPLY, NON_TEXT_NOTICE

    results = []
    with Sandbox():
        amounts, doctors = known_amounts(config.DATA_DIR), doctor_names(config.DATA_DIR)
        notices = {FALLBACK_REPLY, NON_TEXT_NOTICE}
        for n, case in enumerate(cases, start=1):
            phone = f"91990{n:07d}"                     # a different patient for every case
            for earlier in case.prior:        # context: messages the same patient sent before this one
                webhook.handle_incoming_message(phone, f"QA {case.id}", earlier)
            outcome = webhook.handle_incoming_message(phone, f"QA {case.id}", case.message)
            inquiry = db.get_inquiry(outcome["inquiry_id"])
            conversation = db.find_conversation(phone)
            this_id = outcome["patient_message"]["id"]     # only what was sent in reply to THIS message, not to earlier ones
            replies = [m for m in db.list_messages(conversation["id"]) if m["role"] != "patient" and m["id"] > this_id]
            sent = replies[-1]["text"] if replies else ""
            draft = inquiry.get("draft") or ""
            checks = inquiry.get("checks") or []
            failed = [{"name": c["name"], "severity": c["severity"], "detail": c["detail"]}
                      for c in checks if not c["passed"] and c["severity"] != "info"]
            res = Result(
                id=case.id, category=case.category, message=case.message, round=round_name,
                intent=inquiry["intent"], intents=inquiry.get("intents") or [], confidence=inquiry.get("confidence") or 0,
                urgent=bool(inquiry.get("urgent")),
                sources=[{"id": s["id"], "score": s["score"], "method": s.get("method", ""), "used": s.get("used", False)}
                         for s in (inquiry.get("sources") or [])],
                sent_text=sent, draft=draft, decision=inquiry["decision"], status=outcome["status"],
                failed_checks=failed, reasons=inquiry.get("reasons") or [],
                expected_routes=sorted(case.routes),
            )
            if sent and draft and sent.strip() == draft.strip():
                res.answer_kind = "sent automatically"
                res.answer = sent
            elif sent:
                res.answer_kind = "fixed notice sent; " + ("AI draft held (not sent)" if draft else "no draft")
                res.answer = sent + (f"\n[held draft, NOT sent: {draft}]" if draft else "")
            elif draft:
                res.answer_kind = "draft held, nothing sent"
                res.answer = draft
            else:
                res.answer_kind = "nothing drafted, nothing sent"
            res.problems = evaluate(case, res)
            res.invariant_problems = invariant_problems(res, amounts, doctors, notices)
            res.passed = not res.problems and not res.invariant_problems
            res.expected_summary = _expected_text(case)
            res.actual_summary = (f"{res.status}; intent={res.intent}; urgent={res.urgent}; "
                                  f"failed checks: {', '.join(c['name'] for c in failed) or 'none'}")
            results.append(res)
    return results


def _expected_text(case: Case) -> str:
    parts = [" or ".join(sorted(case.routes))]
    if case.intent_any:
        parts.append(f"intent in {case.intent_any}")
    if case.intents_include:
        parts.append(f"topics {case.intents_include}")
    if case.sources_include:
        parts.append(f"sources {case.sources_include}")
    if case.must_contain:
        parts.append(f"contains {case.must_contain}")
    if case.must_not_contain:
        parts.append(f"never says {case.must_not_contain}")
    if case.urgent is not None:
        parts.append(f"urgent={case.urgent}")
    return "; ".join(parts)


# ----------------------------------------------------------------------------------------------------
def summarise(results: list[Result]) -> dict:
    total, passed = len(results), sum(r.passed for r in results)
    by_cat: dict = {}
    for r in results:
        c = by_cat.setdefault(r.category, [0, 0])
        c[0] += 1
        c[1] += r.passed
    unsafe = [r for r in results if r.invariant_problems]
    return {"total": total, "passed": passed, "failed": total - passed,
            "accuracy": round(100 * passed / total, 1) if total else 0.0,
            "by_category": {k: {"total": v[0], "passed": v[1]} for k, v in by_cat.items()},
            "invariant_violations": [r.id for r in unsafe],
            "failed_ids": [r.id for r in results if not r.passed]}


def print_summary(results: list[Result], verbose: bool = False) -> None:
    s = summarise(results)
    for r in results:
        if verbose or not r.passed:
            mark = "PASS" if r.passed else "FAIL"
            print(f"[{mark}] {r.id:<3} {r.message[:78]}")
            print(f"        -> {r.status}, intent={r.intent}, sources={[x['id'] for x in r.sources if x['score'] >= 0.5][:4]}")
            if verbose or not r.passed:
                print(f"        answer ({r.answer_kind}): {r.answer[:230]!r}")
            for p in r.problems + [f"INVARIANT: {p}" for p in r.invariant_problems]:
                print(f"        x {p}")
    print(f"\n{s['passed']}/{s['total']} passed = {s['accuracy']}%   invariant violations: {s['invariant_violations'] or 'none'}")
    for cat, v in s["by_category"].items():
        print(f"   {cat:<26} {v['passed']}/{v['total']}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--round", choices=["1", "2", "3", "4", "all"], default="1")
    ap.add_argument("--json", help="write the full results to this file")
    ap.add_argument("--only", nargs="*", help="run only these case ids")
    ap.add_argument("--verbose", action="store_true", help="show passing cases too")
    args = ap.parse_args()
    cases = {"1": ROUND1, "2": ROUND2, "3": ROUND3, "4": ROUND4, "all": ROUND1 + ROUND2 + ROUND3 + ROUND4}[args.round]
    if args.only:
        cases = [c for c in cases if c.id in args.only]
    results = run_cases(cases, f"round{args.round}")
    print_summary(results, args.verbose)
    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"summary": summarise(results), "results": [asdict(r) for r in results]},
                                  ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\nwritten: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
