import pytest

from backend.classifier import classify, is_affirmation

CASES = [
    ("What are your timings?", "clinic_timings"),
    ("Is the clinic open on Sunday?", "clinic_timings"),
    ("Where are you located?", "location"),
    ("How much does a root canal cost?", "treatment_price"),
    ("root canal ka kharcha kitna hoga", "treatment_price"),
    ("braces kiti paise", "treatment_price"),
    ("Which doctor does braces?", "doctor_info"),
    ("I want to book an appointment", "appointment_booking"),
    ("Can I reschedule my appointment?", "appointment_change"),
    ("Do you accept insurance?", "payment_insurance"),
    ("Is root canal painful?", "treatment_info"),
    ("Hello", "greeting"),
    ("Thank you!", "thanks"),
    ("ok", "thanks"),
    ("Severe pain and swelling", "emergency"),
    ("I want a refund, I am very disappointed", "complaint"),
    ("My tooth hurts when I eat", "medical_advice"),
    ("Can I take paracetamol?", "medical_advice"),
    ("asdf qwerty", "unknown"),
]


@pytest.mark.parametrize("message,expected", CASES)
def test_intent(message, expected):
    assert classify(message).intent == expected


def test_sensitive_topics_are_flagged():
    for message in ("Severe pain and swelling", "I was overcharged", "my tooth hurts"):
        assert classify(message).sensitive


def test_normal_questions_are_not_sensitive():
    for message in ("Is root canal painful?", "what are your timings", "does root canal hurt"):
        assert not classify(message).sensitive


def test_emergency_is_urgent():
    assert classify("Unbearable pain, please help").urgent
    assert not classify("What are your timings?").urgent


def test_one_message_can_have_several_topics():
    cls = classify("What are your timings and how much is whitening?")
    assert {"clinic_timings", "treatment_price"} <= set(cls.intents)


def test_greeting_is_remembered_alongside_a_question():
    cls = classify("Hi! What are your timings?")
    assert cls.intent == "clinic_timings" and cls.greeting


def test_booking_details_are_extracted():
    assert classify("book me for Saturday evening").entities["when"] == "saturday evening"


def test_devanagari_is_detected():
    assert classify("नमस्कार, वेळ काय आहे?").script == "devanagari"
    assert classify("namaskar").script == "latin"


def test_confidence_is_higher_for_clear_questions():
    assert classify("How much does a root canal cost?").confidence > classify("sunday").confidence


@pytest.mark.parametrize("text,expected", [("yes", True), ("Yes please", True), ("ok sure", True), ("book me", False), ("what time", False)])
def test_affirmation(text, expected):
    assert is_affirmation(text) is expected
