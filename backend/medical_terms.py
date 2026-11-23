"""Words about medicine and health conditions, shared by the classifier (what the PATIENT writes) and the validator
(what the REPLY may say), so the two can never disagree about what counts as a medical topic."""

# Medicines, drug names and brand names (including the common Indian ones). A reply may not use any of these unless the
# clinic's own entry for the question does; a patient who asks about one is asking for medical advice.
MEDICINE_TERMS = [
    "antibiotic", "antibiotics", "amoxicillin", "amoxycillin", "augmentin", "azithromycin", "metronidazole", "paracetamol",
    "acetaminophen", "ibuprofen", "aspirin", "diclofenac", "naproxen", "tramadol", "ketorolac", "dolo", "crocin",
    "combiflam", "calpol", "painkiller", "painkillers", "analgesic", "dosage", "dose", "prescribe", "prescribed",
    "prescription", "tablet", "tablets", "capsule", "capsules", "syrup", "ointment", "mouthwash", "clove oil", "numbing",
    "lidocaine", "benzocaine", "chlorhexidine", "betadine", "medicine", "medicines", "medication", "medications",
    "diagnosis", "diagnose", "diagnosed",
]

# Situations where the safe answer depends on the patient's health, so a dentist - not a template - must answer.
HEALTH_CONDITION_PATTERN = (
    r"pregnan\w*|breast ?feeding|diabet\w*|blood pressure|hypertension|allerg\w*|asthma|heart (?:disease|condition|patient|problem|attack)|"
    r"thyroid|cancer|chemotherapy|blood thinner\w*|epilep\w*|kidney (?:disease|problem)|liver (?:disease|problem)"
)
