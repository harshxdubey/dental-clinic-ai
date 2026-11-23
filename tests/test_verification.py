"""Answer verification and routing.

Part 1  each of the five checks, on its own, with good and bad examples
Part 2  the send gate: an unverified AI answer cannot be sent by any code path
Part 3  end to end: a failing answer is NOT sent, becomes a pending item with everything the receptionist needs,
        and is only sent after a human approves, edits or rejects it
"""
import pytest
from retrieval_cases import ANSWERABLE

from backend import config, database, outbound, validator
from backend.ai_response import FALLBACK_REPLY, Draft
from backend.classifier import classify
from backend.pipeline import analyze
from backend.retriever import Source, retrieve
from backend.validator import AUTO_SEND, ESCALATE, NEEDS_APPROVAL

PHONE = "919000000001"
ROOT_CANAL = "treatment:root_canal"


# ---------------------------------------------------------------- helpers
def verify(question, text, ids=None, mode="claude"):
    """Run the verifier on a hand-written (bad or good) answer for a question."""
    cls = classify(question)
    sources = retrieve(question, cls.intents)
    draft = Draft(text=text, mode=mode, used_source_ids=ids if ids is not None else [s.id for s in sources[:2]])
    return validator.validate(draft, cls, sources, question)


def failed(verdict):
    return {c.name for c in verdict.checks if not c.passed}


def text_check(text, name, sources=(), patient=""):
    return next(c for c in validator.text_checks(text, list(sources), patient) if c.name == name)


def src(entry_id):
    return next(s for s in retrieve(" ".join(entry_id.split(":")[1].split("_")), []) if s.id == entry_id)


def chat(client, phone=PHONE):
    return client.get(f"/api/chat/{phone}/messages").json()["messages"]


def ask(client, text, phone=PHONE):
    response = client.post("/api/webhook/whatsapp", json={"phone": phone, "name": "Aarav", "text": text})
    assert response.status_code == 200, response.text
    return response.json()


def detail(client, inquiry_id):
    return client.get(f"/api/dashboard/inquiries/{inquiry_id}").json()


# ================================================================ Part 1: the five checks
# ---- 1. relevant source ----
def test_1_no_relevant_source_means_nothing_is_sent():
    analysis = analyze("do you have a wheelchair ramp")
    assert analysis.verdict.decision == ESCALATE and "answer_found" in failed(analysis.verdict)


def test_1_a_claimed_fact_needs_a_retrieved_source():
    cls = classify("hello there")
    verdict = validator.validate(Draft(text="Our clinic hours are 10 AM to 8 PM.", needs_sources=True), cls, [], "hello there")
    assert verdict.decision == ESCALATE and {"facts_supported", "sources_cited"} <= failed(verdict)


def test_1_citing_an_entry_that_was_not_retrieved_fails():
    verdict = verify("how much is a root canal", "A root canal costs ₹4,000 – ₹9,000.", ids=["treatment:braces"])
    assert "sources_cited" in failed(verdict) and verdict.decision == ESCALATE


# ---- 2. prices and doctor names ----
PRICE_CASES = [
    ("A root canal costs ₹5,000 per tooth.", True),
    ("A root canal costs Rs 5000.", True),
    ("The fee is 5,000 rupees.", True),
    ("It costs 5000.", True),
    ("A root canal costs ₹4,000 – ₹9,000 per tooth.", False),
    ("A root canal is Rs 4000 to Rs 9000.", False),
    ("The dentist sees you for 30 minutes.", False),   # a number that is not a price
]


@pytest.mark.parametrize("text,bad", PRICE_CASES)
def test_2_prices(text, bad):
    check = text_check(text, "prices_supported", [src(ROOT_CANAL)])
    assert check.passed is (not bad), check.detail


def test_2_a_price_repeated_from_the_patients_message_is_not_a_source():
    verdict = verify("i heard a root canal costs Rs 1500 is that right", "Yes, a root canal costs ₹1,500.", ids=[ROOT_CANAL])
    assert "prices_supported" in failed(verdict) and verdict.decision == ESCALATE


def test_2_unknown_doctor():
    check = text_check("Dr. Priya Sharma will treat you.", "doctors_supported", [src(ROOT_CANAL)])
    assert not check.passed and "not a doctor at this clinic" in check.detail


def test_2_real_doctor_but_not_in_the_sources():
    assert not text_check("Dr. Neha Joshi sees braces patients.", "doctors_supported", [src(ROOT_CANAL)]).passed


def test_2_real_doctor_found_in_the_sources_is_fine():
    sources = [src(ROOT_CANAL)]   # its text says "Handled by: Dr. Rahul Kulkarni"
    assert text_check("Dr. Rahul Kulkarni does root canals.", "doctors_supported", sources).passed
    assert text_check("Dr. Kulkarni does root canals.", "doctors_supported", sources).passed
    assert text_check("Rahul Kulkarni does root canals.", "doctors_supported", sources).passed   # no "Dr."


def test_2_a_patient_called_rahul_is_not_mistaken_for_the_doctor():
    assert text_check("Hello Rahul, how can I help?", "doctors_supported", [], patient="Hi, I'm Rahul").passed


def test_2_invented_offers_links_and_numbers():
    sources = [src(ROOT_CANAL)]
    assert not text_check("We have a discount this week!", "no_unsupported_claims", sources).passed
    assert not text_check("Book at https://evil.example/pay", "links_grounded", sources).passed
    assert not text_check("Email us at someone@else.com", "links_grounded", sources).passed
    assert not text_check("Open from 9 AM.", "numbers_grounded", sources).passed


# ---- 3. appointment availability (no calendar is connected) ----
CLAIMS = [
    "Yes, we have a slot available tomorrow at 5 PM.", "Your appointment is confirmed for Saturday.",
    "I've booked you in for 5 PM.", "I will book you for Monday.", "Dr. Neha is available tomorrow at 3 PM.",
    "We can see you today.", "You can come in tomorrow.", "Slots are open this week.", "See you on Saturday!",
    "Your slot is booked.", "You're all set!", "Appointment confirmed.", "We have an opening at 4.",
]
NOT_CLAIMS = [
    "Our reception team will confirm the exact slot with you.", "Appointments are confirmed by our reception team.",
    "Available: Tuesday, Thursday, Saturday, 2:00 PM to 8:00 PM", "Walk-ins are welcome on a first-come basis.",
    "Please arrive 10 minutes early for your first visit.", "We send a reminder the day before your appointment.",
    "Booking ahead helps you avoid waiting.", "I've noted that you'd like to visit around Saturday.",
    "Sunday visits are by appointment only.", "Our clinic hours are: Monday to Saturday 10:00 AM to 8:00 PM",
]


@pytest.mark.parametrize("sentence", CLAIMS)
def test_3_claims_about_availability_or_a_confirmed_booking_are_caught(sentence):
    check = text_check(sentence, "no_appointment_claims")
    assert not check.passed and check.group == "calendar" and "No calendar is connected" in check.detail


@pytest.mark.parametrize("sentence", NOT_CLAIMS)
def test_3_ordinary_appointment_information_is_not_flagged(sentence):
    assert text_check(sentence, "no_appointment_claims").passed


# ---- 4. diagnosis and medicine ----
MEDICAL_BAD = [
    ("You probably have gingivitis.", "no_diagnosis"), ("It looks like an infection.", "no_diagnosis"),
    ("Your gums are inflamed.", "no_diagnosis"), ("Take ibuprofen twice a day.", "no_medical_advice"),
    ("An antibiotic will clear it up.", "no_medical_advice"), ("I recommend a root canal.", "no_treatment_advice"),
    ("You need a crown on that tooth.", "no_treatment_advice"), ("You should rinse with salt water.", "no_treatment_advice"),
]


@pytest.mark.parametrize("text,check_name", MEDICAL_BAD)
def test_4_diagnosis_and_medicine_are_caught(text, check_name):
    check = text_check(text, check_name)
    assert not check.passed and check.group == "medical"


def test_4_the_clinics_own_wording_is_allowed():
    faq = next(s for s in retrieve("what should i bring for my first visit", []) if s.id == "faq:first_visit")
    # the clinic's own FAQ says "a list of the medicines you currently take" - quoting it is fine
    assert text_check(faq.text, "no_medical_advice", [faq]).passed
    assert not text_check(faq.text, "no_medical_advice", []).passed   # but not when it is NOT in the sources


def test_4_normal_clinical_information_is_not_flagged():
    sentence = "Root canal treatment is done under local anaesthesia, so most patients feel little or no pain."
    assert all(text_check(sentence, n).passed for n in ("no_medical_advice", "no_diagnosis", "no_treatment_advice"))
    assert text_check("Happy to help! Message us anytime if you need anything else.", "no_treatment_advice").passed


# ---- 5. valid and complete ----
BROKEN = ["Our hours are {hours}.", "Call us on [phone number].", "See <link> for details.", "TODO: add price",
          "SOURCES: treatment:root_canal", "Details: treatment:root_canal", "As an AI language model I cannot say.",
          "I'm sorry, but I can't help with that."]


@pytest.mark.parametrize("text", BROKEN)
def test_5_placeholders_and_leaked_internals_are_caught(text):
    assert not text_check(text, "well_formed").passed


@pytest.mark.parametrize("text,complete", [
    ("A root canal costs ₹4,000 – ₹9,000 per tooth and the dentist will confirm the exact cost after an", False),
    ("A root canal costs ₹4,000 – ₹9,000 per tooth.", True), ("Happy to help 😊", True),
    ("Call us on +91 90000 00000", True), ("• Monday to Saturday: 10:00 AM to 8:00 PM", True),
])
def test_5_a_reply_cut_off_mid_sentence_is_caught(text, complete):
    check = text_check_mode(text, "not_truncated")
    assert check.passed is complete


def text_check_mode(text, name):
    return next(c for c in validator.text_checks(text, [], "", mode="claude") if c.name == name)


def test_5_the_answer_must_cover_everything_asked():
    verdict = verify("what are your timings and where are you located", "We are open Monday to Saturday 10:00 AM to 8:00 PM.",
                     ids=["clinic:timings"])
    assert "covers_question" in failed(verdict) and verdict.decision == NEEDS_APPROVAL
    both = verify("what are your timings and where are you located",
                  "We are open Monday to Saturday 10:00 AM to 8:00 PM at Shop 12, Sample Plaza, Baner Road, Pune.",
                  ids=["clinic:timings", "clinic:location"])
    assert "covers_question" not in failed(both)


def test_5_naming_two_treatments_but_pricing_one_is_incomplete():
    verdict = verify("price of braces and whitening", "Braces cost ₹30,000 – ₹80,000 for the full treatment.",
                     ids=["treatment:braces", "treatment:whitening"])
    assert "covers_question" in failed(verdict)


def test_5_too_short_or_too_long_is_flagged():
    assert "length_ok" in failed(verify("how much is a root canal", "₹4,000", ids=[ROOT_CANAL]))
    assert "length_ok" in failed(verify("how much is a root canal", "A root canal costs ₹4,000. " * 60, ids=[ROOT_CANAL]))


def test_a_good_answer_passes_every_check():
    verdict = verify("how much is a root canal", "A root canal costs ₹4,000 – ₹9,000 per tooth, depending on the tooth. "
                     "The dentist confirms the exact cost after an examination.", ids=[ROOT_CANAL])
    assert verdict.decision == AUTO_SEND and failed(verdict) == set()
    assert {c.group for c in verdict.checks} >= {"source", "price_doctor", "calendar", "medical", "validity", "routing"}


# ---- the verifier never wrongly stops our own correct answers ----
EVERYDAY = [q for q, _ in ANSWERABLE] + [
    "Where are you located?", "What are your timings?", "Who are your doctors?", "how much for braces", "hello", "thanks",
    "can my 5 year old come for a checkup", "what is the price", "do you accept insurance or UPI?",
]


@pytest.mark.parametrize("question", EVERYDAY)
def test_correct_template_answers_never_fail_a_hard_check(question):
    analysis = analyze(question)
    if analysis.draft.kind == "no_answer" or analysis.classification.sensitive:
        return
    assert [c.name for c in validator.failed_blocks(analysis.verdict.checks)] == [], question
    assert "covers_question" not in failed(analysis.verdict), question


# ================================================================ Part 2: the send gate
@pytest.fixture
def conversation(client):
    return database.get_or_create_conversation(PHONE, "Aarav")


def good_verdict(text):
    cls = classify("how much is a root canal")
    sources = retrieve("how much is a root canal", cls.intents)
    return validator.validate(Draft(text=text, used_source_ids=[ROOT_CANAL]), cls, sources, "how much is a root canal")


GOOD_TEXT = "A root canal costs ₹4,000 – ₹9,000 per tooth, depending on the tooth. The dentist confirms the exact cost after an examination."


def test_gate_an_ai_message_without_a_verdict_is_refused(conversation):
    with pytest.raises(outbound.UnverifiedMessageError):
        outbound.send_reply(conversation, GOOD_TEXT, "assistant")
    assert database.list_messages(conversation["id"]) == []


def test_gate_a_verdict_for_different_text_is_refused(conversation):
    verdict = good_verdict(GOOD_TEXT)
    assert verdict.decision == AUTO_SEND
    with pytest.raises(outbound.UnverifiedMessageError):   # changed after it was verified
        outbound.send_reply(conversation, GOOD_TEXT.replace("9,000", "1,000"), "assistant", verdict=verdict)


def test_gate_a_failed_verdict_is_refused(conversation):
    verdict = verify("how much is a root canal", "A root canal costs ₹5,000.", ids=[ROOT_CANAL])
    assert verdict.decision == ESCALATE
    with pytest.raises(outbound.UnverifiedMessageError):
        outbound.send_reply(conversation, "A root canal costs ₹5,000.", "assistant", verdict=verdict)


def test_gate_verified_text_is_sent_and_recorded_with_its_sources(conversation):
    verdict = good_verdict(GOOD_TEXT)
    message = outbound.send_reply(conversation, GOOD_TEXT, "assistant", verdict=verdict,
                                  sources=[{"id": ROOT_CANAL, "title": "Root Canal Treatment (RCT)", "file": "treatments.json"}])
    assert message["role"] == "assistant" and message["sources"][0]["id"] == ROOT_CANAL
    assert message["meta"]["verified"] is True and message["meta"]["checks_passed"] == message["meta"]["checks_total"]
    assert database.list_messages(conversation["id"])[0]["sources"][0]["file"] == "treatments.json"


def test_gate_only_the_fixed_not_in_knowledge_base_notice_is_exempt(conversation):
    message = outbound.send_reply(conversation, FALLBACK_REPLY, "assistant")
    assert message["meta"]["kind"] == "not_in_knowledge_base_notice"


def test_gate_a_person_may_always_send(conversation):
    assert outbound.send_reply(conversation, "Come in at 5.", "receptionist")["role"] == "receptionist"


# ================================================================ Part 3: end to end
BAD_ANSWERS = {   # (question, what the model wrongly writes, ids it cites, the check that must stop it)
    "invented price": ("how much is a root canal", "A root canal costs ₹1,500 per tooth.", ROOT_CANAL, "prices_supported"),
    "unknown doctor": ("how much is a root canal", "A root canal costs ₹4,000 – ₹9,000. Dr. Priya Sharma will treat you.",
                       ROOT_CANAL, "doctors_supported"),
    "claims a slot is free": ("what are your timings", "We are open 10:00 AM to 8:00 PM and we have a slot available tomorrow at 5 PM.",
                              "clinic:timings", "no_appointment_claims"),
    "diagnosis and medicine": ("is root canal painful", "It sounds like you probably have an infection. Take ibuprofen.",
                               "faq:rct_pain", "no_diagnosis"),
    "unfilled placeholder": ("what are your timings", "Our clinic hours are {hours}. Message us anytime.", "clinic:timings", "well_formed"),
    "cut off": ("how much is a root canal", "A root canal costs ₹4,000 – ₹9,000 per tooth and the exact cost is confirmed after an",
                ROOT_CANAL, "not_truncated"),
}


def reply_for(question, text, cited):
    return f"SOURCES: {cited}\nANSWER:\n{text}"


@pytest.mark.parametrize("label", list(BAD_ANSWERS))
def test_a_failing_answer_is_not_sent_and_becomes_a_pending_item(client, model, label):
    question, bad, cited, expected_check = BAD_ANSWERS[label]
    model(reply=reply_for(question, bad, cited))
    result = ask(client, question)

    # nothing reached the patient
    assert result["reply"] is None and result["status"] in ("escalated", "pending_approval")
    assert [m["role"] for m in chat(client)] == ["patient"]

    # a pending item exists, with everything the receptionist needs
    item = detail(client, result["inquiry_id"])
    assert item["status"] in ("escalated", "pending_approval")
    assert item["question"] == question and any(m["text"] == question for m in item["thread"])       # original message
    assert item["draft"] == bad and item["draft_mode"] == "claude"                                      # the AI's draft
    assert expected_check in {c["name"] for c in item["checks"] if not c["passed"]}                     # which check failed
    assert item["reasons"] and expected_check in " ".join(c["name"] for c in item["checks"] if not c["passed"])   # the reason
    assert item["sources"] and all(s["file"] and s["why"] for s in item["sources"])                     # retrieved sources
    assert item["audit"][0]["event"] == "verified" and item["audit"][-1]["event"] == "held"
    assert client.get("/api/dashboard/inquiries", params={"status": "open"}).json()["inquiries"][0]["failed_checks"] >= 1


def test_a_passing_answer_is_sent_automatically_with_its_source_recorded(client, model):
    model()   # the stand-in model writes a correct, cited answer
    result = ask(client, "How much does a root canal cost?")
    assert result["status"] == "auto_replied" and result["reply"]["role"] == "assistant"

    messages = chat(client)
    assert [m["role"] for m in messages] == ["patient", "assistant"]
    assert set(messages[1]) == {"id", "role", "text", "created_at"}      # the patient never sees sources or checks

    item = detail(client, result["inquiry_id"])
    reply = item["thread"][-1]                                           # the conversation history records answer + source
    assert reply["text"].startswith("A root canal costs") and reply["sources"][0]["id"] == ROOT_CANAL
    assert reply["meta"]["verified"] is True
    assert [e["event"] for e in item["audit"]] == ["verified", "sent"]


def test_template_answers_that_pass_record_their_sources_too(client):
    result = ask(client, "What are your timings?")
    reply = detail(client, result["inquiry_id"])["thread"][-1]
    assert reply["sources"][0]["id"] == "clinic:timings" and reply["meta"]["verified"]


def failed_item(client, model, label="invented price"):
    question, bad, cited, _ = BAD_ANSWERS[label]
    model(reply=reply_for(question, bad, cited))
    return ask(client, question)["inquiry_id"], bad


def test_approving_a_draft_that_failed_needs_explicit_confirmation_and_only_then_is_sent(client, model):
    inquiry_id, bad = failed_item(client, model)
    url = f"/api/dashboard/inquiries/{inquiry_id}/send"

    refused = client.post(url, json={"text": bad})
    assert refused.status_code == 409
    warnings = refused.json()["detail"]["warnings"]
    assert refused.json()["detail"]["needs_acknowledgement"] and any("Price not found" in w["detail"] for w in warnings)
    assert [m["role"] for m in chat(client)] == ["patient"]               # still nothing sent

    done = client.post(url, json={"text": bad, "acknowledge": True}).json()
    assert done["status"] == "approved" and done["resolved_by"] == "Receptionist"
    sent = chat(client)[-1]
    assert sent["role"] == "receptionist" and sent["text"] == bad
    meta = detail(client, inquiry_id)["thread"][-1]["meta"]
    assert meta["approved_by"] == "Receptionist" and meta["edited"] is False and meta["overrode_checks"]
    assert "Overrode" in detail(client, inquiry_id)["audit"][-1]["detail"]


def test_editing_the_draft_fixes_it_and_sends_without_confirmation(client, model):
    inquiry_id, bad = failed_item(client, model)
    fixed = "A root canal costs ₹4,000 – ₹9,000 per tooth. The dentist confirms the exact cost after an examination."
    done = client.post(f"/api/dashboard/inquiries/{inquiry_id}/send", json={"text": fixed}).json()
    assert done["status"] == "replied" and done["final_reply"] == fixed
    item = detail(client, inquiry_id)
    assert item["thread"][-1]["meta"]["edited"] is True
    assert item["thread"][-1]["sources"][0]["id"] == ROOT_CANAL            # still records what it was based on
    assert item["audit"][-1]["event"] == "sent_edited"


def test_an_edit_that_introduces_a_new_mistake_is_flagged(client, model):
    inquiry_id, _ = failed_item(client, model)
    url = f"/api/dashboard/inquiries/{inquiry_id}/send"
    for typo, fragment in (("A root canal costs ₹2,500 per tooth.", "Price not found"),
                           ("Dr. Priya Sharma will call you.", "not a doctor"),
                           ("Take paracetamol and rest.", "Medicine wording"),
                           ("Our hours are {hours}.", "should never reach a patient")):
        response = client.post(url, json={"text": typo})
        assert response.status_code == 409, typo
        assert fragment in str(response.json()["detail"]["warnings"]), typo
    assert [m["role"] for m in chat(client)] == ["patient"]


def test_a_receptionist_may_confirm_times_and_appointments_in_their_own_words(client, model):
    inquiry_id, _ = failed_item(client, model)
    done = client.post(f"/api/dashboard/inquiries/{inquiry_id}/send",
                       json={"text": "Your appointment is confirmed for Saturday at 5 PM. See you then!"})
    assert done.status_code == 200 and done.json()["status"] == "replied"


def test_rejecting_the_draft_never_sends_it_and_leaves_the_message_open(client, model):
    inquiry_id, bad = failed_item(client, model)
    rejected = client.post(f"/api/dashboard/inquiries/{inquiry_id}/reject", json={"reason": "Wrong price"}).json()
    assert rejected["status"] == "escalated" and rejected["draft"] == ""
    assert rejected["rag"]["draft_rejected"] and rejected["rag"]["rejected_draft"] == bad
    assert rejected["audit"][-1]["event"] == "rejected" and "Wrong price" in rejected["audit"][-1]["detail"]
    assert any("rejected by the receptionist" in r for r in rejected["reasons"])
    assert [m["role"] for m in chat(client)] == ["patient"]

    assert client.post(f"/api/dashboard/inquiries/{inquiry_id}/reject", json={}).status_code == 409   # nothing left to reject
    own = client.post(f"/api/dashboard/inquiries/{inquiry_id}/send", json={"text": "A root canal is ₹4,000 – ₹9,000."}).json()
    assert own["status"] == "replied"
    assert [m["role"] for m in chat(client)] == ["patient", "receptionist"]


def test_dismissing_sends_nothing_and_is_recorded(client, model):
    inquiry_id, _ = failed_item(client, model)
    done = client.post(f"/api/dashboard/inquiries/{inquiry_id}/dismiss").json()
    assert done["status"] == "dismissed" and done["audit"][-1]["event"] == "dismissed"
    assert [m["role"] for m in chat(client)] == ["patient"]


def test_the_audit_trail_tells_the_whole_story(client, model):
    inquiry_id, bad = failed_item(client, model)
    client.post(f"/api/dashboard/inquiries/{inquiry_id}/reject", json={})
    client.post(f"/api/dashboard/inquiries/{inquiry_id}/send", json={"text": "It is ₹4,000 – ₹9,000."})
    trail = detail(client, inquiry_id)["audit"]
    assert [(e["by"], e["event"]) for e in trail] == [
        ("AI assistant", "verified"), ("AI assistant", "held"), ("Receptionist", "rejected"), ("Receptionist", "sent_manual")]
    assert "failed" in trail[0]["detail"] and all(e["at"] for e in trail)


def test_setting_can_hold_every_model_written_answer_for_approval(client, model, monkeypatch):
    model()
    monkeypatch.setattr(config, "APPROVE_MODEL_ANSWERS", True)
    result = ask(client, "How much does a root canal cost?")
    assert result["status"] == "pending_approval" and result["reply"] is None
    assert any("approve every answer written by the AI model" in r for r in detail(client, result["inquiry_id"])["reasons"])


def test_a_truncated_model_reply_is_discarded_in_favour_of_the_template(client, model):
    stub = model(reply="SOURCES: treatment:root_canal\nANSWER:\nA root canal costs", stop_reason="max_tokens")
    result = ask(client, "How much does a root canal cost?")
    item = detail(client, result["inquiry_id"])
    assert item["draft_mode"] == "template" and "cut off" in item["draft_note"] and "₹4,000" in item["draft"]
    assert stub.calls


# ---------------------------------------------------------------- database upgrade
def test_an_older_database_gains_the_new_columns(tmp_path, monkeypatch):
    import sqlite3

    old = tmp_path / "old.db"
    connection = sqlite3.connect(old)
    connection.executescript("""
        CREATE TABLE conversations (id INTEGER PRIMARY KEY AUTOINCREMENT, phone TEXT UNIQUE, name TEXT, created_at TEXT, updated_at TEXT);
        CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, conversation_id INTEGER, role TEXT, text TEXT, inquiry_id INTEGER, created_at TEXT);
        CREATE TABLE inquiries (id INTEGER PRIMARY KEY AUTOINCREMENT, conversation_id INTEGER, message_id INTEGER, question TEXT, intent TEXT,
            intents TEXT, confidence REAL, urgent INTEGER, draft TEXT, draft_mode TEXT, draft_note TEXT, sources TEXT, checks TEXT, reasons TEXT,
            decision TEXT, status TEXT, final_reply TEXT, resolved_by TEXT, created_at TEXT, updated_at TEXT, resolved_at TEXT);
        INSERT INTO conversations VALUES (1, '919000000001', 'Old', 'x', 'x');
        INSERT INTO messages VALUES (1, 1, 'patient', 'old message', NULL, 'x');
    """)
    connection.close()
    monkeypatch.setattr(config, "DATABASE_PATH", old)
    database.init_db()
    columns = lambda table: {row[1] for row in sqlite3.connect(old).execute(f"PRAGMA table_info({table})")}   # noqa: E731
    assert {"rag", "audit"} <= columns("inquiries") and {"sources", "meta", "wa_id", "delivery", "delivery_error"} <= columns("messages")
    assert "channel" in columns("conversations") and "whatsapp_events" in {
        r[0] for r in sqlite3.connect(old).execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert database.list_messages(1)[0]["sources"] == []          # existing rows still read fine
