"""The validator is the safety net, so these tests try hard to sneak bad answers past it."""
from backend.ai_response import Draft
from backend.classifier import classify
from backend.pipeline import analyze
from backend.retriever import retrieve
from backend.validator import AUTO_SEND, ESCALATE, NEEDS_APPROVAL, validate


def check(draft_text, message="how much is a root canal", needs_sources=True, **kwargs):
    cls = classify(message)
    sources = retrieve(message, cls.intents)
    draft = Draft(text=draft_text, needs_sources=needs_sources, used_source_ids=[s.id for s in sources])
    return validate(draft, cls, sources, message, **kwargs)


def failed(verdict):
    return {c.name for c in verdict.checks if not c.passed}


def test_a_correct_answer_passes():
    verdict = check("Root Canal Treatment costs ₹4,000 – ₹9,000 per tooth.")
    assert verdict.decision == AUTO_SEND and not failed(verdict)


def test_invented_price_is_blocked():
    verdict = check("A root canal costs ₹1,500 per tooth.")
    assert verdict.decision == ESCALATE
    assert "numbers_grounded" in failed(verdict)


def test_price_formatting_differences_are_allowed():
    assert check("A root canal is Rs 4000 to Rs 9000 per tooth.").decision == AUTO_SEND


def test_invented_offer_is_blocked():
    verdict = check("Root canal is ₹4,000 and we are offering a discount this week!")
    assert verdict.decision == ESCALATE and "no_unsupported_claims" in failed(verdict)


def test_guarantees_are_blocked():
    assert "no_unsupported_claims" in failed(check("Root canal is ₹4,000 and completely painless, guaranteed."))


def test_medical_advice_is_blocked():
    verdict = check("Take paracetamol and rinse with salt water.")
    assert verdict.decision == ESCALATE and "no_medical_advice" in failed(verdict)


def test_unknown_links_are_blocked():
    verdict = check("Book here: https://evil.example.com/pay")
    assert "links_grounded" in failed(verdict)


def test_known_links_are_allowed():
    message = "where are you located"
    cls = classify(message)
    sources = retrieve(message, cls.intents)
    link = "https://maps.example.com/sample-dental-clinic-pune"
    draft = Draft(text=f"Find us: {link}", used_source_ids=[s.id for s in sources])
    assert "links_grounded" not in failed(validate(draft, cls, sources, message))


def test_empty_draft_is_escalated():
    assert check("").decision == ESCALATE


def test_answer_with_no_source_is_blocked():
    cls = classify("hello there")
    verdict = validate(Draft(text="Our clinic hours are 10 AM to 8 PM.", needs_sources=True), cls, [], "hello there")
    assert verdict.decision == ESCALATE and "facts_supported" in failed(verdict)


def test_greeting_needs_no_sources():
    assert analyze("hello").verdict.decision == AUTO_SEND


def test_low_confidence_needs_approval():
    assert analyze("sunday").verdict.decision == NEEDS_APPROVAL


def test_appointments_always_need_approval():
    assert analyze("I want to book an appointment tomorrow").verdict.decision == NEEDS_APPROVAL


def test_sensitive_topics_always_escalate():
    for message in ("Severe pain and swelling", "I want a refund", "my tooth hurts", "can I take an antibiotic"):
        assert analyze(message).verdict.decision == ESCALATE, message


def test_unknown_messages_escalate():
    assert analyze("asdf qwerty").verdict.decision == ESCALATE


def test_auto_reply_switch_forces_approval():
    assert analyze("hello", auto_reply_enabled=False).verdict.decision == NEEDS_APPROVAL
    assert analyze("Severe pain", auto_reply_enabled=False).verdict.decision == ESCALATE  # still escalates


def test_non_english_script_needs_approval():
    assert analyze("नमस्कार, तुमची वेळ काय आहे?").verdict.decision in (NEEDS_APPROVAL, ESCALATE)


def test_list_numbering_is_not_mistaken_for_a_fake_number():
    verdict = check("Here are the steps:\n1. Call us\n2. Visit\nRoot canal costs ₹4,000.")
    assert "numbers_grounded" not in failed(verdict)
