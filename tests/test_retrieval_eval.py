"""Retrieval accuracy on realistic patient questions (see retrieval_cases.py to add more)."""
import pytest
from retrieval_cases import ANSWERABLE, HELD_OUT, HELD_OUT_UNANSWERABLE, UNANSWERABLE

from backend.classifier import classify
from backend.pipeline import analyze
from backend.retriever import retrieve
from backend.textutils import stem


def top3(question):
    return [s.id for s in retrieve(question, classify(question).intents)[:3]]


@pytest.mark.parametrize("question,expected", ANSWERABLE + HELD_OUT, ids=[q for q, _ in ANSWERABLE + HELD_OUT])
def test_the_right_entry_is_retrieved(question, expected):
    assert any(e in top3(question) for e in expected), f"{question!r}: wanted one of {expected}, got {top3(question)}"


@pytest.mark.parametrize("question", UNANSWERABLE)
def test_nothing_relevant_is_retrieved_for_unknown_subjects(question):
    assert [s for s in retrieve(question, classify(question).intents) if s.score >= 0.5] == []


@pytest.mark.parametrize("question", UNANSWERABLE + HELD_OUT_UNANSWERABLE)
def test_unanswerable_questions_are_forwarded_not_guessed(question):
    analysis = analyze(question)
    assert analysis.draft.kind == "no_answer"
    assert analysis.verdict.decision == "escalate"
    assert analysis.draft.used_source_ids == []
    assert analysis.holding_reply and "reception team" in analysis.holding_reply


COMMON_QUESTIONS = [
    "Where are you located?", "What are your timings?", "Do you have parking?", "How much is whitening?",
    "Who are your doctors?", "Do you accept UPI?", "what is your phone number", "Is root canal painful?",
    "how much for braces", "Which doctor does implants?", "Are you open on Sunday?", "do you take insurance",
]


@pytest.mark.parametrize("question", COMMON_QUESTIONS)
def test_everyday_questions_are_always_answered(question):
    """The 'say I don't know' safeguards must never block a normal question."""
    analysis = analyze(question)
    assert analysis.draft.kind == "answer", question
    assert analysis.draft.used_source_ids, question


@pytest.mark.parametrize("word,root", [("cleaned", "clean"), ("cleaning", "clean"), ("located", "locat"), ("locate", "locat"),
                                         ("pricing", "pric"), ("price", "pric"), ("braces", "brac"), ("brace", "brac"),
                                         ("fillings", "fill"), ("teeth", "teeth")])
def test_stemmer_gives_different_forms_the_same_root(word, root):
    assert stem(word) == root


def test_synonyms_are_editable_data(tmp_path):
    """A new synonym group in data/synonyms.json takes effect with no code change."""
    from backend import config

    assert [s.id for s in retrieve("what do you charge for a gleam", ["unknown"])] == []
    (config.DATA_DIR / "synonyms.json").write_text(
        '{"groups": [["whitening", "gleam"], ["price", "charge"]]}', encoding="utf-8")
    assert "treatment:whitening" in [s.id for s in retrieve("what do you charge for a gleam", ["unknown"])]


def test_every_retrieved_source_explains_why_it_matched():
    for source in retrieve("how much is a root canal and who does it", ["treatment_price", "doctor_info"]):
        assert source.reasons and source.method in ("precise", "topic", "words")
