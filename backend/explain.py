"""Show your work: how one question is answered, step by step.

Used in two places:
  * the dashboard's "Knowledge base -> Test a question" view  (POST /api/kb/ask)
  * the command line:   python -m backend.explain "How much is a root canal?"

Nothing is saved or sent - it only analyses the question.
"""
from __future__ import annotations

import argparse
import textwrap

from . import ai_response, config, pipeline, rag


def trace(question: str, auto_reply_enabled: bool = True) -> dict:
    analysis = pipeline.analyze(question, auto_reply_enabled=auto_reply_enabled)
    record = analysis.to_record()
    cls, draft = analysis.classification, analysis.draft
    would_use_model = config.USE_LLM and ai_response.model_is_eligible(cls, analysis.sources)

    if draft.kind == "no_answer":
        how = ("Nothing in the clinic's information answers this question, so no answer was written. "
               "The patient gets a short 'I don't know, I've asked reception' message and the question is forwarded.")
    elif draft.mode == "claude":
        how = (f"The retrieved entries were given to Claude ({draft.model}) as its only context. It wrote the answer "
               "and named the entries it used.")
    else:
        how = ("Template mode: the answer was assembled from the retrieved entries with fixed wording. "
               "No AI model was called.")
        if not config.USE_LLM and ai_response.model_is_eligible(cls, analysis.sources):
            how += " (With an API key, Claude would write this answer from the context shown below.)"

    return {
        "question": question,
        "understood": {
            "intent": cls.intent, "intents": cls.intents, "confidence": cls.confidence,
            "sensitive": cls.sensitive, "urgent": cls.urgent, "entities": cls.entities,
        },
        "retrieved": record["sources"],
        "context": rag.build_context(analysis.sources),
        "prompt": rag.build_prompt(question, analysis.sources),
        "generation": {"mode": draft.mode, "model": draft.model or None, "kind": draft.kind, "how": how,
                       "model_would_be_used": would_use_model, "note": draft.note},
        "answer": "" if draft.kind == "no_answer" else draft.text,
        "parts": draft.parts,
        "used_sources": list(draft.used_source_ids),
        "answerable": draft.kind != "no_answer",
        "holding_reply": analysis.holding_reply,
        "decision": analysis.verdict.decision,
        "reasons": analysis.verdict.reasons,
        "checks": record["checks"],
    }


# --------------------------------------------------------------------------
# Command-line output
# --------------------------------------------------------------------------
def _wrap(text: str, indent: str = "    ", width: int = 96) -> str:
    out = []
    for line in text.splitlines() or [""]:
        out.append(textwrap.fill(line, width=width, initial_indent=indent, subsequent_indent=indent + "  ") if line.strip() else "")
    return "\n".join(out)


def format_trace(t: dict, show_prompt: bool = False) -> str:
    u = t["understood"]
    lines = [f'QUESTION  "{t["question"]}"', "",
             f"1. UNDERSTOOD   topic: {', '.join(u['intents'])}   confidence: {u['confidence']:.0%}"
             + ("   [SENSITIVE]" if u["sensitive"] else ""), "",
             "2. RETRIEVED FROM THE KNOWLEDGE BASE"]
    if not t["retrieved"]:
        lines.append("    (nothing relevant found)")
    for s in t["retrieved"]:
        flag = "USED " if s["used"] else "     "
        lines.append(f"  {flag}{s['id']:<34} score {s['score']:.2f}  [{s['method']}]  {s['file']}"
                     + ("  (dummy data)" if s["dummy"] else ""))
        for why in s["why"]:
            lines.append(f"        - {why}")
    lines += ["", "3. HOW THE ANSWER WAS GENERATED", _wrap(t["generation"]["how"])]
    if show_prompt:
        lines += ["", "   Context given to the model:", _wrap(t["context"] or "(empty)", "      | ", 110)]
    lines += ["", "4. ANSWER" + (" (not sent - nothing to answer from)" if not t["answerable"] else "")]
    if t["answerable"]:
        lines.append(_wrap(t["answer"], "    | ", 100))
        lines += ["", "5. SOURCE REFERENCES (internal, shown to the receptionist, never sent to the patient)"]
        for part in t["parts"]:
            if part["sources"]:
                first = part["text"].strip().splitlines()[0][:70]
                lines.append(f'    "{first}{"…" if len(part["text"]) > 70 else ""}"  <-  {", ".join(part["sources"])}')
    else:
        lines.append(_wrap('Patient is told: "' + (t["holding_reply"] or "") + '"', "    | ", 100))
        lines += ["", "5. FORWARDED TO RECEPTION  (the receptionist sees the question and writes the reply)"]
    lines += ["", f"6. DECISION     {t['decision'].upper()}"]
    lines += [_wrap("- " + r, "      ") for r in t["reasons"]]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Show how the assistant answers a patient question.")
    parser.add_argument("questions", nargs="+", help="one or more patient questions, in quotes")
    parser.add_argument("--prompt", action="store_true", help="also print the context given to the AI model")
    args = parser.parse_args()
    for i, question in enumerate(args.questions):
        if i:
            print("\n" + "=" * 100 + "\n")
        print(format_trace(trace(question), show_prompt=args.prompt))


if __name__ == "__main__":
    main()
