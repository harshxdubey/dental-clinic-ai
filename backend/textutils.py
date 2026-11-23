"""Small text helpers shared by the classifier, retriever and validator."""
from __future__ import annotations

import re

# Words that carry little meaning when we compare a question with clinic information.
STOPWORDS = frozenset(
    """a an the is are was were be been am do does did can could will would should may might
    i me my we our you your it its this that these those of in on at to for from with
    and or but if so as by about any have has had how what when where which who why whom
    please tell want know need get getting got also there their they them just like really
    much many one ones some something anything thing id still yes no ok okay hi hello hey
    thanks thank today tomorrow tonight now let us kindly""".split()
)

# Hindi / Hinglish / Marathi written in English letters: the small grammar words that say nothing about WHAT is being
# asked ("Aapki clinic kab khulti hai?" is about the clinic's opening time - "aapki" and "hai" are just grammar).
# Without this list every such word looked like an unknown subject and a perfectly answerable question was sent to a person.
# Only words that are not also common English words belong here.
HINGLISH_FILLER = frozenset(
    """hai hain hoga hogi hoge hota hoti hote ho raha rahi rahe
    ka ki ke ko se mein mei
    aap aapka aapki aapke aapko aapse
    yahan yaha wahan waha
    kya kyun kyu kaise
    mujhe mera meri mere hum humko hamara hamare
    lagega lagegi lagenge lagta lagti lagwane lagwana lagvane
    chahiye chahie karna karni karne karwana karwane karvana karvane
    kijiye kijiyega batao bataiye bataye bataiyega batana
    nahi nahin abhi kuch koi aur bhi toh
    ahe aahe aahet ahet
    tumcha tumchi tumche tumhi mala majha majhi madhe sathi
    cha chi che pls plz plss sir madam bro ur ya wat wht abt hw thx tq tnx
    log dete deta deti dena lete leta leti lena karte karta karti milta milti milte rehta rehti rehte rakhte rakhta rakhti""".split()
)
STOPWORDS = STOPWORDS | HINGLISH_FILLER


_VOCATIVE = re.compile(r"(?i)^\W*(?:hello|hi|hii|hey|dear|good\s+(?:morning|afternoon|evening|day)|namaste)[\s,]+(?:doctor|dr|sir|madam|ma'am|sirji)\b[\s,!.:-]*"
                       r"|[\s,]+(?:doctor|sir|madam|ma'am|sirji)\s*[?.!]*\s*$")
_ASKING = re.compile(r"(?i)^\W*(?:(?:and|also|so|but|please)\s+)*(?:what|which|how|where|when|who|why|do|does|did|can|could|will|would|is|are|am|"
                     r"have|has|should|kya|kaun|kab|kahan|kaise|kitna|kitni|kitne)\b")


def strip_vocative(text: str) -> str:
    """"Hello doctor, what time do you open?" -> "what time do you open?" (the doctor is being addressed, not asked about)."""
    stripped = _VOCATIVE.sub("", text, count=1).strip()
    return stripped or text


def question_part(message: str) -> str:
    """The sentences that actually ask something. "My friend told me about you. What are your hours?" -> "What are your hours?"
    Chatty lead-ins must not decide whether the question can be answered. (If nothing looks like a question, the whole message.)"""
    sentences = re.split(r"(?<=[.!?])\s+|\n+", message.strip())
    asked = [s for s in sentences if s.rstrip().endswith("?") or _ASKING.match(s)]
    return " ".join(asked) or message


def normalize(text: str) -> str:
    """Lower-case, turn punctuation into spaces, and collapse whitespace.

    "Root-canal cost?? (Rs. 5,000)" -> "root canal cost rs 5 000"
    """
    text = text.lower().replace("₹", " rs ")
    text = re.sub(r"[^\w\s]|_", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def stem(word: str) -> str:
    """Cut a word back to a rough root so different forms match: cleaned/cleaning -> clean, located/locate -> locat.

    It is deliberately crude (no libraries needed). It only has to be consistent: the same
    function is applied to the patient's words and to the clinic information.
    """
    if len(word) <= 3 or not word.isalpha():
        return word
    if word.endswith("ies") and len(word) > 4:
        word = word[:-3] + "y"
    elif word.endswith(("sses", "xes", "ches", "shes")):
        word = word[:-2]
    elif word.endswith("s") and not word.endswith(("ss", "us", "is")):
        word = word[:-1]
    for suffix in ("ing", "ed"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            word = word[: -len(suffix)]
            break
    # drop a silent final "e" so that locate/located, price/pricing and close/closed share one root
    if len(word) > 3 and word.endswith("e"):
        word = word[:-1]
    return word


def tokens(text: str) -> list[str]:
    """Meaningful, stemmed words of a text (stop-words removed)."""
    return [stem(w) for w in normalize(text).split() if w not in STOPWORDS and len(w) > 1]


_LIST_MARKER = re.compile(r"(?m)^\s*\d+[.)]\s+")


def extract_numbers(text: str) -> set[str]:
    """Every number in a text, normalised so "₹4,000" and "4000" compare equal.

    Used by the validator to make sure the AI never invents a price, phone number,
    time or year that is not in the knowledge base.
    """
    text = _LIST_MARKER.sub("", text)  # ignore "1. " list numbering
    numbers = set()
    for match in re.finditer(r"\d[\d,]*", text):
        digits = match.group().replace(",", "")
        numbers.add(digits.lstrip("0") or "0")
    return numbers


_PRICE_PATTERNS = [
    re.compile(r"(?:₹|\brs\.?|\binr)\s*(\d[\d,]*)", re.I),                          # ₹4,000   Rs. 4000   INR 4000
    re.compile(r"(\d[\d,]*)\s*(?:rupees|\brs\b|\binr\b|/-)", re.I),                  # 4000 rupees
    re.compile(r"(?:₹|\brs\.?|\binr)\s*\d[\d,]*\s*(?:-|–|—|to)\s*(?:₹|rs\.?\s*)?(\d[\d,]*)", re.I),  # ₹4,000 – 9,000
    re.compile(r"\b(?:costs?|prices?|priced|charges?|charged|fees?)\s+(?:is\s+|of\s+|at\s+)?(\d[\d,]{2,})", re.I),  # costs 5000
]


def extract_prices(text: str) -> set[str]:
    """Amounts of money in a text, as plain digit strings ("₹4,000 – 9,000" -> {"4000", "9000"})."""
    amounts = set()
    for pattern in _PRICE_PATTERNS:
        for match in pattern.finditer(text):
            digits = match.group(1).replace(",", "")
            if digits:
                amounts.add(digits.lstrip("0") or "0")
    return amounts
