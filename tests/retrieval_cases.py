"""A test set for retrieval: realistic patient questions and the knowledge entries that SHOULD be found.

Add a line here whenever the assistant retrieves the wrong thing for a real question. The tests in
test_retrieval_eval.py check that the expected entry is among the top 3 results.
"""

# (patient question, ids of entries of which at least ONE must be in the top 3)
ANSWERABLE = [
    # --- treatment prices (paraphrased, not just the exact alias) ---
    ("what's the charge for getting my teeth cleaned", ["treatment:scaling"]),
    ("price of white fillings", ["treatment:filling"]),
    ("how much do you charge for children", ["treatment:kids"]),
    ("wisdom tooth removal cost", ["treatment:extraction"]),
    ("I want to straighten my teeth, how much will it cost", ["treatment:braces", "treatment:aligners"]),
    ("cost to replace a missing tooth", ["treatment:implant"]),
    ("invisalign price", ["treatment:aligners"]),
    ("full mouth xray rate", ["treatment:xray"]),
    ("how much for a cap on my tooth", ["treatment:crown"]),
    ("bleaching cost", ["treatment:whitening"]),
    ("false teeth price", ["treatment:dentures"]),
    ("what is the check up fee", ["treatment:consultation"]),
    # --- doctors ---
    ("best doctor for braces", ["doctor:dr_neha_joshi"]),
    ("does dr kulkarni work on saturdays", ["doctor:dr_rahul_kulkarni"]),
    ("is there a child specialist", ["doctor:dr_pooja_bhosale"]),
    ("which doctor removes wisdom teeth", ["doctor:dr_sameer_patil"]),
    ("i need an endodontist", ["doctor:dr_rahul_kulkarni"]),
    # --- FAQs (patients rarely use the FAQ's own words) ---
    ("can i just walk in without calling", ["faq:walk_in"]),
    ("what documents should i carry for the first visit", ["faq:first_visit"]),
    ("will the root canal hurt", ["faq:rct_pain"]),
    ("are your instruments sterilized", ["faq:sterilisation"]),
    ("do you offer emi on braces", ["faq:emi"]),
    ("how long does whitening last", ["faq:whitening_last"]),
    ("is radiation from dental xrays harmful", ["faq:xray_safety"]),
    ("can you send my xray copy on whatsapp", ["faq:reports"]),
    ("how many minutes is one appointment", ["faq:visit_length"]),
    ("which languages do your staff speak", ["faq:languages"]),
    ("at what age should a baby first see a dentist", ["faq:kids_age"]),
    # --- timings, location, contact, payment ---
    ("till what time are you open today", ["clinic:timings"]),
    ("do you work on public holidays", ["clinic:timings"]),
    ("where exactly is the clinic", ["clinic:location"]),
    ("is there parking for cars", ["clinic:location"]),
    ("do you take google pay", ["clinic:payment"]),
    ("do you have cashless insurance", ["clinic:payment"]),
    ("what is your email id", ["clinic:contact"]),
    # --- appointments ---
    ("how do i book an appointment", ["clinic:policy"]),
    ("what is your cancellation policy", ["clinic:policy"]),
    ("how far in advance should i book braces", ["faq:booking_advance"]),
    ("do you send appointment reminders", ["faq:reminders"]),
]

# Questions the knowledge base cannot answer: the assistant must NOT guess.
UNANSWERABLE = [
    "what is the capital of france",
    "do you have a wheelchair ramp",
    "how much is a hair transplant",
    "what is the weather like today",
    "do you sell toothbrushes online",
    "who is the owner of the clinic",
]


# Written AFTER the synonym list was tuned, and all found on the first try. Kept as regression tests.
HELD_OUT = [
    ("what are the charges for a tooth cap", ["treatment:crown"]),
    ("does dr patil take patients on wednesday", ["doctor:dr_sameer_patil"]),
    ("i heard you offer invisible braces how much", ["treatment:aligners"]),
    ("is parking available for bikes", ["clinic:location"]),
    ("can i pay using phonepe", ["clinic:payment"]),
    ("what time do you close on saturday", ["clinic:timings"]),
    ("do you do kids dentistry", ["treatment:kids"]),
    ("is the clinic open sunday afternoon", ["clinic:timings"]),
    ("can i come without booking", ["faq:walk_in"]),
    ("how long will the whitening effect stay", ["faq:whitening_last"]),
    ("what is the clinic phone number", ["clinic:contact"]),
    ("which doctor is good with children", ["doctor:dr_pooja_bhosale"]),
    ("price for getting a tooth pulled out", ["treatment:extraction"]),
    ("how much to fix a cavity", ["treatment:filling"]),
    ("do i need to bring anything on my first appointment", ["faq:first_visit"]),
    ("is it safe to get an xray", ["faq:xray_safety"]),
    ("do you give discounts on braces", ["treatment:braces"]),
    ("will you remind me before my appointment", ["faq:reminders"]),
]
HELD_OUT_UNANSWERABLE = [
    "do you do teeth piercing",
    "is there a pharmacy inside the clinic",
    "what is the doctor's home address",
    "do you treat gum disease with laser",
]
