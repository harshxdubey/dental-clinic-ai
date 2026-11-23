"""STAGE 2 - CLASSIFIER: works out what the patient is asking about.

This is deliberately simple and explainable: a list of keyword patterns, each with a
weight. The intent with the highest total weight wins. No model, no training data -
so you can read exactly why a message was classified the way it was, and fix it by
editing a pattern below.

Messages are normalised first (lower-case, no punctuation), so "Can't" becomes "can t".
Hinglish / Marathi-in-English-letters keywords (kitna, kimat, kiti, kab, kahan...) are
included because many Pune patients type that way.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from .medical_terms import HEALTH_CONDITION_PATTERN, MEDICINE_TERMS
from .textutils import normalize

# When two intents tie, the earlier one in this list wins.
PRIORITY = [
    "emergency", "complaint", "medical_advice",
    "appointment_change", "appointment_booking",
    "treatment_price", "doctor_info", "clinic_timings", "location",
    "payment_insurance", "contact_info", "treatment_info", "general_faq",
    "greeting", "thanks",
]

# The most topics answered in one reply. (It was 3: a fourth question in the same message was silently dropped.)
MAX_TOPICS = 5

# Topics a human must always handle (and the score needed to trigger each one).
SENSITIVE_MIN = {"emergency": 1.5, "complaint": 1.5, "medical_advice": 1.0}

_TREATMENT_WORDS = (r"(filling|fillings|root canal|rct|crown|crowns|cap|extraction|implants?|braces|aligners?|surgery|treatment|"
                    r"procedure|cleaning|scaling|whitening|dentures?|x ?rays?|antibiotics?|stitches)")

_SYMPTOM = (
    r"\b(toothache|tooth ache|tooth pain|gum pain|jaw pain|ear pain"
    r"|pain in (my |the )?(tooth|teeth|gum|gums|jaw)"
    r"|my (tooth|teeth|gum|gums|jaw|mouth)\b[a-z ]{0,25}\b(hurts?|hurting|paining|painful|aching|aches|pain|sensitive|loose|bleeds?|swollen)"
    r"|i (have|am having|m having|feel|feeling|got) (a |some |severe |bad |terrible |sharp )?(pain|ache)"
    r"|dukh(?:ta|ti|te|ne|\s+raha|\s+rahi)"
    # Hindi "dard" (pain) is a symptom only when it is the patient's own: "mere daant mein dard", "bachche ko dard hai".
    # "Root canal mein dard hota hai kya?" asks a general question that the clinic's FAQ answers.
    r"|(?:mere|meri|mera|mujhe|humein|hamare|bachche|bacche|bachhe|bete|beti|papa|mummy)\b[^.?!]{0,30}\bdard"
    r"|\bdaant\w*\s+(?:mein\s+|me\s+|ka\s+|ki\s+|ke\s+)?(?:\w+\s+)?dard"
    r"|\bdard\s+(?:ho\s+raha|ho\s+rahi|ho\s+gaya|hone\s+laga))\b"
)

_RULES: dict[str, list[tuple[str, float]]] = {
    "emergency": [
        (r"\b(emergency|urgent|urgently|unbearable|excruciating|severe|severely)\b", 2.0),
        (r"\b(bleeding|bleed|swelling|swollen)\b", 1.2),
        (r"\b(abscess|pus|oozing)\b", 1.2),
        (r"\b(knocked out|broken tooth|tooth broke|tooth broken|chipped|fractured|accident|injury|injured)\b", 1.6),
        (r"\b(cant|can t|cannot|unable to) (eat|sleep|breathe|swallow|chew|open (my )?mouth)\b", 2.0),
        (r"\bfever\b", 1.0),
        # an injury: a fall, a blow, a knock ("my filling fell out" is not one)
        (r"\b(fell|fall|fallen|hit|struck|punched|kicked|knocked|collided|crash|crashed)\b(?! out)", 1.6),
        (r"\b(tooth|teeth)\b.{0,25}\b(broken|broke|chipped|cracked|fractured)\b|\b(broken|chipped|cracked|fractured)\b.{0,15}\b(tooth|teeth)\b", 1.6),
        # bleeding that does not stop, or a lot of blood
        (r"\bblood\b", 1.2),
        # Hindi / Hinglish: severe pain ("bahut tez dard", "raat se so nahi paya"), blood (khoon), swelling (sujan)
        (r"\b(bahut|bohot|bohat)\s+(tez|zyada|jyada|jada)\s+dard\b|\b(tez|asahya|asahaniya)\s+dard\b|\bbardasht\s+nahi\b|\b(so|sleep)\s+nahi\s+(paya|paye|pa\s+raha|pa\s+rahi)\b|\bneend\s+nahi\b", 2.0),
        (r"\b(khoon|sujan|soojan|suj\s+gaya|suj\s+gayi)\b", 1.2),
        (r"\b(toot|toota|tuta|tut)\s*(gaya|gayi|gaye)\b|\bgir\s+(gaya|gayi|gaye)\b|\bchot\b|\bhaadsa\b", 1.6),
    ],
    "complaint": [
        (r"\b(complaint|complain|refund|overcharged|overcharging|disappointed|dissatisfied|unhappy|worst|rude|"
         r"negligence|negligent|legal|lawyer|consumer court|bad experience|terrible|pathetic|fraud|cheated|cheating)\b", 1.6),
    ],
    "medical_advice": [
        (_SYMPTOM, 1.6),
        (r"\b(medicine|medicines|medication|tablet|tablets|antibiotic|antibiotics|painkiller|painkillers|dose|dosage|"
         r"prescribe|prescribed|home remedy|home remedies|clove oil|ointment)\b", 1.6),
        (r"\b(" + "|".join(re.escape(t) for t in MEDICINE_TERMS) + r")\b", 1.6),
        (r"\b(" + HEALTH_CONDITION_PATTERN + r")\b", 1.6),
        (r"\b(dawai|dawa|dawaai|davai|goli|golia)\b", 1.6),
        (r"\bcan i (take|eat|drink|brush|smoke|exercise|have)\b", 1.5),
        (r"\b(should i worry|should i take|is it normal|is this normal|what should i do|how to (stop|treat|cure|reduce))\b", 1.5),
        # "should I get a filling or a root canal?", "do I need a crown?" ask the assistant to choose a treatment: a dentist's job
        (r"\b(?:should i (?:get|have|go for|choose|do|opt for|undergo)|do i need)\s+(?:\w+\s+){0,4}?" + _TREATMENT_WORDS + r"\b", 1.6),
        (r"\b(which (treatment|procedure|one) (is|should|do)|what treatment (do|should)|which is better)\b", 1.6),
        (r"\bi (think|feel|suspect) (i have|i might have|i may have|there is|there s)\b", 1.0),
        (r"\b(mouthwash|toothpaste|gel|spray|rinse)\b.{0,30}\b(should|which|best)\b|\b(which|best)\b.{0,30}\b(mouthwash|toothpaste)\b", 1.6),
        (r"\b(infection|infected|diagnosis|diagnose|lump|ulcer|white patch|black spot|sensitivity)\b", 1.0),
    ],
    "appointment_change": [
        (r"\b(reschedule|rescheduling|cancel|cancelling|cancellation|postpone|prepone|"
         r"change (my |the )?(appointment|appt|slot|time|date))\b", 2.0),
        (r"\b(move|shift|push|delay|swap)\b.{0,20}\b(appointment|appt|slot|booking|visit)\b|"
         r"\b(appointment|appt|slot|booking)\b.{0,25}\b(move|moved|shift|shifted|postponed|delayed)\b", 2.0),
    ],
    "appointment_booking": [
        (r"\b(book|booking|appointment|appointments|appt|slot|slots|schedule)\b", 1.0),
        # Weak alone: "is parking available?", "is EMI available?" are not booking requests. _availability_means_booking()
        # adds the missing weight when the question is about a person or a time.
        (r"\b(availability|available|visit)\b", 0.5),
        (r"\b(i want to come|can i come|want to see|need to see|see a dentist|see the doctor|meet the doctor)\b", 1.0),
        (r"\b(like|looking|wanted|wish) to (see|meet|visit|come|book|consult)\b", 1.0),
        (r"\b(an?|any|the|some|one)\s+(opening|vacancy)\b", 1.0),
        (r"\baa\s+(sakta|sakti|sakte|jaun|jaoon|jaaun)\b|\baana\s+(hai|chahta|chahti|chahte)\b|\b(karwana|karvana|karwani|karvani|dikhana|dikhwana)\s+(hai|tha)\b|"
        r"\b(appointment|slot|time)\s+(chahiye|chahie|milega|mil\s+sakta|mil\s+sakti)\b", 1.0),
        (r"\bi (will|ll|am going to|m going to|can) (come|visit|reach|drop in|walk in)\b|\b(coming|come) (now|immediately|right away|today|tomorrow|tonight)\b", 1.0),
    ],
    "treatment_price": [
        (r"\b(price|prices|pricing|cost|costs|charge|charges|charged|fee|fees|rs|inr|rupees|estimate|"
         r"quote|quotation|expensive|cheap|affordable|kimat|kiti|paise|kharcha|kharch|daam)\b", 1.2),
        # "kitna / kitne" = how much / how many: a price only when it is not about time ("kitne baje" = what time, "kitna time" = how long)
        (r"\bkitna\b(?! (time|samay|der))|\bkitne\b(?! (baje|din|mahine|months|visit|visits|sitting|sittings|hafte|week|weeks|log|saal|year|years))", 1.2),
        (r"(?<!success )(?<!failure )(?<!survival )(?<!interest )(?<!heart )(?<!pulse )(?<!exchange )\brates?\b", 1.2),
        (r"\bhow much(?! (time|pain|long|days|duration))\b", 1.2),
    ],
    "treatment_info": [
        (r"\b(kitna (time|samay)|kitne (din|mahine|months|visit|visits|sitting|sittings|hafte|week|weeks)|kitni der|time lagega|samay lagega)\b", 0.9),
        (r"\b(how long|how many (visits|sessions|days|appointments)|procedure|painful|sessions?|"
         r"duration|recovery|process|safe|safety|side effects?|results?|how does|suitable|benefits?)\b", 0.9),
        # Very generic phrases: weak on their own, so they never add a topic to a clearer question.
        (r"\b(what is|what are|explain|tell me about|details about|information about)\b", 0.6),
    ],
    "doctor_info": [
        (r"\b(kaun|kon)\s+(karta|karti|karte|dekhta|dekhti|dekhte)\b", 1.0),
        (r"\b(doctor|doctors|dr|dentist|dentists|specialist|specialists|surgeon|orthodontist|endodontist|"
         r"pedodontist|paediatric|pediatric|experience|experienced|qualification|qualified|degree|"
         r"who treats|who does|who will)\b", 1.0),
    ],
    "clinic_timings": [
        (r"\b(timing|timings|time table|hours|working hours|open|opens|opening|close|closes|closing|closed|"
         r"open till|till what time|what time|kab|kitne baje|vel|kadhi|lunch)\b", 1.0),
        (r"\b(sunday|saturday|holiday|holidays|weekend)\b", 0.6),
    ],
    "location": [
        (r"\b(where|(?<!email )(?<!e mail )(?<!mail )(?<!web )(?<!website )address|location|located|locate|direction|directions|map|maps|google maps|landmark|"
         r"how to reach|how do i reach|route|nearby|near|kahan|kahaan|kuthe|kuthay|pata|patta|parking|park)\b", 1.0),
    ],
    "contact_info": [
        (r"\b(phone|phone number|contact|contact number|call you|mobile number|landline|email|e mail|"
         r"whatsapp number|helpline)\b", 1.0),
    ],
    "payment_insurance": [
        (r"\b(insurance|cashless|mediclaim|tpa|upi|gpay|phonepe|paytm|card|cards|cash|emi|payment|payments|pay|"
         r"installment|installments|instalment|instalments)\b", 1.0),
    ],
    "greeting": [
        (r"\b(hi|hii|hiii|hello|hey|heyy|namaste|namaskar|hola|good (morning|afternoon|evening))\b", 1.0),
    ],
    "thanks": [
        (r"\b(thanks|thank you|thankyou|thx|dhanyavad|shukriya)\b", 1.0),
        (r"^(ok|okay|k|kk|fine|great|perfect|got it|noted|cool|nice)$", 0.9),
    ],
}
RULES = {intent: [(re.compile(rx), w) for rx, w in rules] for intent, rules in _RULES.items()}

_WHEN = re.compile(
    r"\b(today|tomorrow|tonight|day after tomorrow|next week|this week|weekend|monday|tuesday|wednesday|"
    r"thursday|friday|saturday|sunday|morning|afternoon|evening|aaj|kal|parso|(?<!\d )(?<!\d)\d{1,2} ?(?:am|pm))\b"
)
_AFFIRMATION = re.compile(r"^(yes|yeah|yep|yup|sure|ok|okay|please|yes please|ok please|haan|ha|ho|hoy|definitely)( .*)?$")
_ACK_EMOJI = re.compile("^[\\s\U0001F44D\U0001F64F\U0001F60A\U0001F600\U0001F642\U0001F44C\u2705\u2764\U0001F4AF\U0001F91D\U0001F603\U0001F604\U0001F64C\ufe0f\u200d]+$")
_DEVANAGARI = re.compile(r"[ऀ-ॿ]")


_AMPLIFIER = re.compile(r"\b(a lot|lots|heavy|heavily|profuse|profusely|wont stop|won t stop|not stopping|will not stop|"
                        r"does not stop|doesn t stop|nonstop|non stop|continuously|continuous|bahut|zyada|jyada|nahi ruk|ruk nahi|lagatar)\b")
_CLOCK = re.compile(r"\b\d{1,2} ?(?:am|pm)\b|\bat \d{1,2}(?: \d{2})?\b")      # "5 pm", "at 4 30" (the colon is already gone)
_AVAILABILITY = re.compile(r"\b(available|availability|free)\b")
_PRICE_FREE = re.compile(r"\bfree\b")
_FREE_NOT_PRICE = re.compile(r"\b(parking|park|wifi|wi fi|water|tea|coffee|delivery)\b")


_SPECIFIC_DATE = re.compile(r"\b(today|tomorrow|tonight|day after tomorrow|this week|next week|this weekend|aaj|kal|parso)\b")
_PRESENCE = re.compile(r"\b(be there|be in|be around|be present|come in|coming in|working|sitting|attending|seeing patients)\b")


def _availability_means_booking(norm: str, has_time: bool) -> bool:
    """"Is Dr. Neha available tomorrow at 5?" asks for a free slot. "Is parking available?" and "What days is Dr. Anjali
    available?" (a working-days question the knowledge base answers) do not."""
    if _PRESENCE.search(norm) and _SPECIFIC_DATE.search(norm):
        return True      # "Will Dr. Pooja be there tomorrow?": the weekly timetable cannot say whether she is in on a particular day
    return bool(_AVAILABILITY.search(norm)) and has_time


def _free_means_price(norm: str) -> bool:
    """"Whitening is free, right?" is a question about the price. "Is there free parking?" is not."""
    return bool(_PRICE_FREE.search(norm)) and not _FREE_NOT_PRICE.search(norm)


@dataclass
class Classification:
    intent: str                                   # the main topic, e.g. "treatment_price"
    confidence: float                             # 0.0 - 1.0
    intents: list = field(default_factory=list)   # every topic to answer, best first
    scores: dict = field(default_factory=dict)    # raw score per intent (for debugging)
    sensitive: bool = False                       # emergency / complaint / medical advice
    urgent: bool = False                          # needs a human quickly
    greeting: bool = False                        # message also said hello
    script: str = "latin"                         # "latin" or "devanagari"
    entities: dict = field(default_factory=dict)  # e.g. {"when": "saturday evening"}
    caution: list = field(default_factory=list)   # weak signs of a health concern ("emergency" for just "bleeding"): a person checks the reply

    def to_dict(self) -> dict:
        return asdict(self)


def is_affirmation(text: str) -> bool:
    """True for a bare "yes / ok / sure" style reply."""
    return bool(_AFFIRMATION.match(normalize(text)))


# Words whose misspelling would hide the topic ("prise", "whiteing", "apointment"). Only 5+ letter words, only one edit away.
_TYPO_VOCAB = tuple("""price prices pricing charge charges timing timings appointment appointments availability available
    location address doctor doctors dentist treatment insurance payment number whitening cleaning braces implant implants
    crown filling extraction emergency urgent bleeding swelling cancel reschedule booking saturday sunday tomorrow parking
    phone email opening closing painful medicine antibiotic painkiller consultation""".split())
_TYPO_SAFE = frozenset("pride prime prize prick prices charm crowd crowns closed closes sundae".split())


def _one_edit_away(a: str, b: str) -> bool:
    """True if a can become b by one insertion, deletion, substitution or swap of neighbouring letters."""
    if a == b or abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        diff = [i for i in range(len(a)) if a[i] != b[i]]
        return len(diff) == 1 or (len(diff) == 2 and diff[1] == diff[0] + 1 and a[diff[0]] == b[diff[1]] and a[diff[1]] == b[diff[0]])
    short, long_ = (a, b) if len(a) < len(b) else (b, a)
    i = 0
    while i < len(short) and short[i] == long_[i]:
        i += 1
    return short[i:] == long_[i + 1:]


def fix_typos(norm: str) -> str:
    """Repair one-letter misspellings of the topic keywords: "wht is the prise of teeth whiteing" -> "... price ... whitening"."""
    fixed = []
    for word in norm.split():
        if len(word) >= 5 and word not in _TYPO_VOCAB and word not in _TYPO_SAFE:
            match = next((v for v in _TYPO_VOCAB if _one_edit_away(word, v)), None)
            word = match or word
        fixed.append(word)
    return " ".join(fixed)


def classify(text: str) -> Classification:
    norm = fix_typos(normalize(text))

    scores: dict[str, float] = {}
    for intent, rules in RULES.items():
        total = sum(weight for rx, weight in rules if rx.search(norm))
        if total:
            scores[intent] = round(min(total, 3.0), 2)

    script = "devanagari" if _DEVANAGARI.search(text) else "latin"
    greeting = scores.get("greeting", 0) >= 1.0
    when = list(dict.fromkeys(_WHEN.findall(norm)))
    entities = {"when": " ".join(when)} if when else {}

    if _ACK_EMOJI.match(text):
        scores["thanks"] = 1.0                      # a thumbs-up or folded hands is an acknowledgement
    if 0 < scores.get("emergency", 0) and _AMPLIFIER.search(norm):
        scores["emergency"] = round(min(scores["emergency"] + 0.9, 3.0), 2)   # "bleeding ... and it won't stop"
    if _CLOCK.search(norm) and (re.search(r"\b(dr|doctor)\b", norm) or re.search(r"\b(see|meet|visit|come)\b", norm)) \
            and not re.search(r"\b(open|close|closes|closing|timing|timings|hours)\b", norm):
        scores["appointment_booking"] = max(scores.get("appointment_booking", 0), 1.0)   # "see Dr. Neha next Tuesday at 4:30"
    if _availability_means_booking(norm, bool(when)):
        scores["appointment_booking"] = max(scores.get("appointment_booking", 0), 1.0)
    if _free_means_price(norm):
        scores["treatment_price"] = max(scores.get("treatment_price", 0), 1.2)
    # Only the generic phrases ("what is ...?") matched: that names no topic. Say so, instead of calling the question
    # about "the capital of France" a treatment question. (The retriever may still recognise the topic and promote it.)
    if 0 < scores.get("treatment_info", 0) < 0.9 and len(scores) == 1:
        scores.pop("treatment_info")

    if scores.get("appointment_change", 0) >= 0.9:
        scores.pop("appointment_booking", None)   # "reschedule my appointment" mentions an appointment but books nothing new
    sensitive_hits = [i for i in ("emergency", "complaint", "medical_advice") if scores.get(i, 0) >= SENSITIVE_MIN[i]]
    # "bleeding gums, price of scaling?": a health word too weak to call an emergency. It must not become the topic of the
    # reply (a "sorry you're dealing with this" message, auto-sent), but it must make a person look at the reply.
    weak_signs = [i for i in ("emergency", "complaint", "medical_advice") if 0 < scores.get(i, 0) < SENSITIVE_MIN[i]]
    substantive = {k: v for k, v in scores.items() if k not in ("greeting", "thanks", *sensitive_hits, *weak_signs)}

    if sensitive_hits:
        intent = sensitive_hits[0]
        intents = [intent]
        top = scores[intent]
    elif substantive and max(substantive.values()) >= 0.5:
        ordered = sorted(substantive, key=lambda i: (-substantive[i], PRIORITY.index(i)))
        top = substantive[ordered[0]]
        intents = [i for i in ordered if substantive[i] >= 0.9 and substantive[i] >= 0.35 * top][:MAX_TOPICS] or ordered[:1]
        intent = intents[0]
    elif scores.get("thanks"):
        intent, intents, top = "thanks", ["thanks"], scores["thanks"]
    elif greeting:
        intent, intents, top = "greeting", ["greeting"], scores["greeting"]
    else:
        intent, intents, top = "unknown", ["unknown"], 0.0

    confidence = 0.2 if intent == "unknown" else round(min(0.97, 0.45 + 0.3 * top), 2)

    return Classification(
        intent=intent,
        confidence=confidence,
        intents=intents,
        scores=scores,
        sensitive=bool(sensitive_hits),
        urgent=scores.get("emergency", 0) >= SENSITIVE_MIN["emergency"],
        greeting=greeting and intent != "greeting",
        script=script,
        entities=entities,
        caution=weak_signs,
    )
