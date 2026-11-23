from backend import knowledge
from backend.retriever import retrieve


def ids(sources):
    return [s.id for s in sources]


def test_finds_the_treatment_named_in_the_message():
    sources = retrieve("what is the price of root canal", ["treatment_price"])
    assert sources[0].id == "treatment:root_canal"
    assert sources[0].score == 1.0
    assert "₹4,000" in sources[0].text


def test_tolerates_typos():
    assert "treatment:root_canal" in ids(retrieve("rootcanal cost", ["treatment_price"]))
    assert "treatment:whitening" in ids(retrieve("teeth whiteing price", ["treatment_price"]))


def test_unrelated_words_do_not_match_treatments():
    assert not [s for s in retrieve("are you calling me back", ["unknown"]) if s.kind == "treatment"]


def test_finds_several_treatments():
    found = ids(retrieve("braces and whitening price", ["treatment_price"]))
    assert "treatment:braces" in found and "treatment:whitening" in found


def test_finds_doctor_by_name():
    sources = retrieve("is dr neha available", ["doctor_info"])
    assert sources[0].id == "doctor:dr_neha_joshi"


def test_a_patient_name_is_not_mistaken_for_a_doctor():
    assert not [s for s in retrieve("hi i am rahul", ["greeting"]) if s.kind == "doctor"]


def test_finds_the_doctor_who_handles_a_treatment():
    assert "doctor:dr_sameer_patil" in ids(retrieve("who does implants", ["doctor_info"]))


def test_lists_all_doctors_when_asked_generally():
    doctors = [s for s in retrieve("who are your doctors", ["doctor_info"]) if s.kind == "doctor"]
    assert len(doctors) == len(knowledge.load()["doctors"])


def test_finds_matching_faq():
    sources = retrieve("is root canal painful", ["treatment_info"])
    faq = next(s for s in sources if s.kind == "faq")
    assert faq.id == "faq:rct_pain" and faq.score >= 0.6


def test_clinic_facts_follow_the_intent():
    assert "clinic:timings" in ids(retrieve("when are you open", ["clinic_timings"]))
    assert "clinic:location" in ids(retrieve("where are you", ["location"]))
    assert "clinic:payment" in ids(retrieve("do you take upi", ["payment_insurance"]))


def test_nothing_found_for_nonsense():
    assert retrieve("asdf qwerty", ["unknown"]) == []


def test_results_are_sorted_best_first():
    scores = [s.score for s in retrieve("root canal price and doctor", ["treatment_price", "doctor_info"])]
    assert scores == sorted(scores, reverse=True)


def test_indian_price_formatting():
    assert knowledge.format_inr(4000) == "₹4,000"
    assert knowledge.format_inr(25000) == "₹25,000"
    assert knowledge.format_inr(200000) == "₹2,00,000"
    assert knowledge.format_price_range(500, 500) == "₹500"
