"""STAGE 3 - RETRIEVER: finds the clinic information that relates to a patient's question.

For every question it searches ALL the clinic's knowledge entries (treatments, doctors, FAQs and
general clinic facts) and returns the best matches as "sources". Each source has:

  * an id, e.g. `treatment:root_canal`  - the internal reference shown to the receptionist
  * a score from 0 to 1                 - how well it matches
  * reasons                             - plain-English notes on WHY it matched

Three simple methods are combined (no vector database, no machine learning):

  1. Precise matches   treatment names ("root canal", even misspelled), doctor names, FAQ keywords.
                       Words are cut back to a root first, so "cleaned" matches "cleaning".
  2. Topic matches     if the patient asks about timings, the clinic-hours entry is retrieved.
  3. Word overlap      every other entry is scored by how many of the question's words it contains
                       (rare words count more). A small synonym list (data/synonyms.json) lets
                       "cost" find information written with "price".

If nothing scores high enough, nothing is returned - and the assistant then says it does not know.
"""
from __future__ import annotations

import difflib
import math
import re
from collections import Counter
from dataclasses import dataclass, field

from . import knowledge
from .textutils import question_part, STOPWORDS, normalize, stem

MIN_SCORE = 0.45        # weaker matches are discarded
LEXICAL_MAX = 0.85      # word-overlap alone can never look as certain as an exact match

# Words that describe the KIND of question rather than its subject ("how much does X cost").
_QUESTION_WORDS = (
    "price cost fee charge rate treatment procedure service offer provide available availability "
    "doctor dentist appointment book booking slot visit timing time open close hour address location "
    "phone number contact pay payment information info detail kharcha kitna kimat cheap expensive afford treat "
    "kab kaun kahan kahaan kitni kitne kiti kuthe kadhi kon paisa "
    "work working morning afternoon evening night day days week weekend monday tuesday wednesday thursday friday saturday sunday "
    "early late till until lunch right correct true whatsapp mobile telephone landline call email mail "
    "long take taking duration session sitting send share give show provide forward subah shaam dopahar raat baje aaj kal parso "
    "accept accepted exactly exact actually currently precisely"
).split()


_METHOD_RANK = {"precise": 0, "topic": 1, "words": 2}


@dataclass
class Source:
    id: str          # e.g. "treatment:root_canal"
    kind: str        # treatment | doctor | faq | clinic
    title: str
    text: str        # the facts (this is the only text the AI may quote)
    score: float     # 0.0 - 1.0 match strength
    file: str        # which data file it came from
    reasons: list = field(default_factory=list)   # why it matched
    method: str = "precise"                       # precise (name/keyword) | topic | words (word overlap)
    dummy: bool = False                           # is this sample data?
    data: dict = field(default_factory=dict, repr=False)  # the raw record (not stored in the DB)

    @classmethod
    def from_record(cls, record: dict) -> "Source":
        """Rebuild a source from what the database stored (used to re-check a receptionist's edited reply)."""
        return cls(id=record["id"], kind=record["kind"], title=record["title"], text=record["text"],
                   score=record["score"], file=record.get("file", ""), reasons=record.get("why", []),
                   method=record.get("method", "precise"), dummy=record.get("dummy", False))

    def to_dict(self) -> dict:
        return {
            "id": self.id, "kind": self.kind, "title": self.title, "text": self.text,
            "score": round(self.score, 2), "file": self.file, "why": self.reasons, "method": self.method,
            "dummy": self.dummy,
        }


# --------------------------------------------------------------------------
# Word index (built once per version of the knowledge base)
# --------------------------------------------------------------------------
class _Index:
    def __init__(self, kb: dict):
        self.canon: dict[str, str] = {}
        for group in kb["synonyms"]:
            roots = [stem(normalize(w)) for w in group if normalize(w)]
            for root in roots:
                self.canon.setdefault(root, roots[0])

        self.entry_terms = {
            e.id: set(self.terms(f"{e.title} {' '.join(e.keywords)} {e.text}")) for e in kb["entries"]
        }
        # a patient who writes "I am Rahul" must not be matched to Dr. Rahul by name alone
        self.name_terms = {e.id: set(self.terms(e.title)) for e in kb["entries"] if e.kind == "doctor"}
        count = len(kb["entries"]) or 1
        document_frequency = Counter(t for terms in self.entry_terms.values() for t in terms)
        self.document_frequency = document_frequency
        self.idf = {t: math.log(1 + count / (n + 0.5)) for t, n in document_frequency.items()}
        self.unseen_idf = math.log(1 + count / 0.5)   # a word no entry contains is very telling
        self.question_terms = {self.canon.get(stem(w), stem(w)) for w in _QUESTION_WORDS}

    def terms(self, text: str) -> list[str]:
        """Meaningful words of a text: no filler words, cut to a root, synonyms unified."""
        out = []
        for word in normalize(text).split():
            if word in STOPWORDS or len(word) < 2:
                continue
            root = stem(word)
            out.append(self.canon.get(root, root))
        return out


_index_cache: dict = {"kb": None, "index": None}


def index_for(kb: dict) -> "_Index":
    """The word index of a loaded knowledge base (used by the drafting code to see which words the clinic's entries explain)."""
    return _index(kb)


def _index(kb: dict) -> _Index:
    if _index_cache["kb"] is not kb:
        _index_cache.update(kb=kb, index=_Index(kb))
    return _index_cache["index"]


# --------------------------------------------------------------------------
# 1. Precise matches
# --------------------------------------------------------------------------
def _close_together(idx: _Index, query: str, terms: set) -> bool:
    """Do all the words of a phrase occur near each other in the question? In a 100-word message the words of
    "how much time will it take" are all somewhere, by chance; that is not the question being asked."""
    if len(terms) < 2:
        return True
    ordered = idx.terms(query)
    need, best = len(terms), None
    for start in range(len(ordered)):
        seen = set()
        for end in range(start, len(ordered)):
            if ordered[end] in terms:
                seen.add(ordered[end])
            if len(seen) == need:
                span = end - start + 1
                best = span if best is None else min(best, span)
                break
    return best is not None and best <= need + 3


def _phrase_match(idx: _Index, query: str, query_terms: set, phrase: str, focus_terms: set | None = None):
    """How well a phrase (an alias or keyword) appears in the question. Returns (score, note) or None."""
    phrase_norm = normalize(phrase)
    if not phrase_norm:
        return None
    if re.search(rf"\b{re.escape(phrase_norm)}\b", query):
        return 1.0, f"the question contains “{phrase}”"
    words = [w for w in phrase_norm.split() if w not in STOPWORDS]
    terms = set(idx.terms(phrase))
    # a multi-word phrase must not shrink to a single common word, or it would match too easily
    if terms and terms <= query_terms and not (len(words) >= 2 and len(terms) < 2) and _close_together(idx, query, terms):
        # A multi-word phrase that shrinks to ONE generic word ("no appointment" -> "appointment") would match
        # almost every question about that word, so only a distinctive leftover word ("walk in" -> "walk") counts.
        if len(terms) == 1 and len(phrase_norm.split()) >= 2:
            only = next(iter(terms))
            # ...and the one word left must be distinctive. "how long will i be there" shrinks to "long", which sits in
            # a quarter of the entries; a message that merely says "for a long time" is not asking how long a visit takes.
            if only in idx.question_terms or idx.document_frequency.get(only, 0) > 3:
                return None
            if focus_terms is not None and only not in focus_terms:
                return None   # the word is in the message, but not in the sentence that actually asks something
        return 0.93, f"the question has the same words as “{phrase}” (in another form)"
    return None


def _typo_match(query_words: list[str], alias: str):
    """Catch misspellings: 'rootcanal', 'whiteing'. Returns (score, note) or None."""
    alias_norm = normalize(alias)
    if len(alias_norm) < 5:
        return None
    size, best, best_text = len(alias_norm.split()), 0.0, ""
    for i in range(len(query_words) - size + 1):
        candidate = " ".join(query_words[i:i + size])
        if candidate[:1] != alias_norm[:1]:
            continue
        ratio = difflib.SequenceMatcher(None, candidate, alias_norm).ratio()
        if ratio > best:
            best, best_text = ratio, candidate
    if best >= 0.85:
        return round(0.9 * best, 2), f"“{best_text}” looks like a misspelling of “{alias}”"
    return None


def _match_treatments(idx: _Index, query: str, query_terms: set, kb: dict) -> dict[str, tuple[float, str]]:
    words = query.split()
    found = {}
    for t in kb["treatments"]:
        best = (0.0, "")
        for alias in [t["name"], *t["aliases"]]:
            hit = _phrase_match(idx, query, query_terms, alias) or _typo_match(words, alias)
            if hit and hit[0] > best[0]:
                best = hit
        if best[0] >= 0.75:
            found[t["id"]] = best
    return found


def _match_doctors(idx: _Index, query: str, query_terms: set, kb: dict, intents: list[str],
                   treatment_hits: dict) -> dict[str, tuple[float, str]]:
    mentions_doctor = bool(re.search(r"\b(dr|doctor|dentist)\b", query))
    wants_doctors = "doctor_info" in intents or "appointment_booking" in intents
    handled = {}
    for tid, (score, _) in treatment_hits.items():
        if score >= 0.9:
            for doctor_id in kb["treatments_by_id"][tid].get("handled_by", []):
                handled.setdefault(doctor_id, kb["treatments_by_id"][tid]["name"])

    found: dict[str, tuple[float, str]] = {}
    for d in kb["doctors"]:
        name_words = [w for w in normalize(d["name"]).split() if w != "dr" and len(w) >= 4]
        if mentions_doctor and any(re.search(rf"\b{w}\b", query) for w in name_words):
            found[d["id"]] = (1.0, f"the question names {d['name']}")
            continue
        keyword = next((k for k in d.get("specialty_keywords", []) if _phrase_match(idx, query, query_terms, k)), None)
        if keyword:
            found[d["id"]] = (0.9, f"the question mentions “{keyword}”")
        elif d["id"] in handled and (wants_doctors or mentions_doctor):
            found[d["id"]] = (0.7, f"{d['name']} performs {handled[d['id']]}, which the question mentions")

    if not found and "doctor_info" in intents:  # "who are your doctors?" -> list everyone
        found = {d["id"]: (0.6, "a general question about the doctors") for d in kb["doctors"]}
    return found


def _is_loose_one_word_match(idx: _Index, query: str, keyword: str) -> bool:
    """A multi-word keyword that is NOT in the question as a phrase and shrinks to one word."""
    kw = normalize(keyword)
    return (len(kw.split()) >= 2 and len(set(idx.terms(keyword))) == 1
            and not re.search(rf"\b{re.escape(kw)}\b", query))


def _match_faqs(idx: _Index, query: str, query_terms: set, kb: dict, focus_terms: set | None = None) -> dict[str, tuple[float, str]]:
    found = {}
    for faq in kb["faqs"]:
        hits = [k for k in faq.get("keywords", []) if _phrase_match(idx, query, query_terms, k, focus_terms)]
        if not hits:
            continue
        if focus_terms is not None and all(_is_loose_one_word_match(idx, query, k) for k in hits):
            # every hit is a whole phrase that boiled down to one word ("what should I bring" -> "bring"). That is trustworthy
            # only if the rest of the question is about the same FAQ: "Can I bring my pet?" shares "bring" and nothing else.
            entry_terms = idx.entry_terms.get(f"faq:{faq['id']}", set())
            stray = [t for t in focus_terms if t not in idx.question_terms and t not in entry_terms]
            if stray:
                continue
        question_terms = set(idx.terms(faq["question"]))
        overlap = len(query_terms & question_terms) / max(1, len(question_terms))
        score = min(1.0, 0.72 + 0.1 * (min(len(hits), 3) - 1) + 0.1 * overlap)
        found[faq["id"]] = (score, f"the question contains the FAQ keyword “{hits[0]}”")
    return found


# --------------------------------------------------------------------------
# 2. Topic matches (what kind of question is it?)
# --------------------------------------------------------------------------
_TOPIC_SOURCES = {   # intent -> [(entry key, score)]
    "clinic_timings": [("timings", 1.0)],
    "location": [("location", 1.0), ("contact", 0.6)],
    "contact_info": [("contact", 1.0)],
    "payment_insurance": [("payment", 1.0)],
    "appointment_booking": [("policy", 1.0), ("timings", 0.6), ("contact", 0.6)],
    "appointment_change": [("policy", 1.0), ("timings", 0.6), ("contact", 0.6)],
    "emergency": [("emergency", 1.0), ("contact", 1.0), ("timings", 0.9)],
    "medical_advice": [("contact", 1.0), ("timings", 0.7)],
    "complaint": [("contact", 1.0), ("timings", 0.7)],
}


def _topic_matches(kb: dict, intents: list[str]) -> dict[str, tuple[float, str]]:
    found: dict[str, tuple[float, str]] = {}
    for intent in intents:
        for key, score in _TOPIC_SOURCES.get(intent, []):
            entry_id = f"clinic:{key}"
            if entry_id in kb["entries_by_id"] and score > found.get(entry_id, (0, ""))[0]:
                found[entry_id] = (score, f"it is the information for the topic “{intent.replace('_', ' ')}”")
    return found


# --------------------------------------------------------------------------
# 3. Word overlap across every entry
# --------------------------------------------------------------------------
def _lexical_matches(idx: _Index, query_terms: set) -> dict[str, tuple[float, str]]:
    subject_terms = query_terms - idx.question_terms   # words about WHAT is asked, not the kind of question
    if not subject_terms:
        return {}
    weight = {t: idx.idf.get(t, idx.unseen_idf) for t in query_terms}
    total = sum(weight.values())
    found = {}
    for entry_id, entry_terms in idx.entry_terms.items():
        shared = query_terms & entry_terms
        if not (shared & subject_terms) or not (shared - idx.name_terms.get(entry_id, set())):
            continue
        coverage = sum(weight[t] for t in shared) / total   # words the entry explains / words in the question
        score = LEXICAL_MAX * coverage
        if score >= MIN_SCORE:
            found[entry_id] = (round(score, 2), f"shares the words {', '.join(sorted(shared))} ({coverage:.0%} of the question)")
    return found


# --------------------------------------------------------------------------
def retrieve(message: str, intents: list[str]) -> list[Source]:
    """Return the knowledge entries that relate to a message, best match first (max 8)."""
    kb = knowledge.load()
    idx = _index(kb)
    query = normalize(message)
    query_terms = set(idx.terms(message))

    treatments = _match_treatments(idx, query, query_terms, kb)
    layers = [
        ("precise", {f"treatment:{k}": v for k, v in treatments.items()}),
        ("precise", {f"doctor:{k}": v for k, v in _match_doctors(idx, query, query_terms, kb, intents, treatments).items()}),
        ("precise", {f"faq:{k}": v for k, v in _match_faqs(idx, query, query_terms, kb, set(idx.terms(question_part(message)))).items()}),
        ("topic", _topic_matches(kb, intents)),
        ("words", _lexical_matches(idx, query_terms)),
    ]

    found: dict[str, Source] = {}
    for method, layer in layers:
        for entry_id, (score, reason) in layer.items():
            entry = kb["entries_by_id"].get(entry_id)
            if entry is None:
                continue
            reason = reason[:1].upper() + reason[1:]
            source = found.get(entry_id)
            if source is None:
                found[entry_id] = Source(id=entry.id, kind=entry.kind, title=entry.title, text=entry.text, score=score,
                                         file=entry.file, reasons=[reason], method=method, dummy=entry.dummy, data=entry.data)
            else:
                source.score = max(source.score, score)
                if _METHOD_RANK[method] < _METHOD_RANK[source.method]:   # precise beats topic beats word overlap
                    source.method = method
                if reason not in source.reasons:
                    source.reasons.append(reason)

    result = [s for s in found.values() if s.score >= MIN_SCORE]
    result.sort(key=lambda s: s.score, reverse=True)
    return result[:8]


def subject_terms(message: str) -> list[str]:
    """The words that say WHAT the question is about (not the kind of question)."""
    idx = _index(knowledge.load())
    return [t for t in dict.fromkeys(idx.terms(message)) if t not in idx.question_terms]


def unexplained_terms(message: str, sources: list[Source]) -> list[str]:
    """Subject words in the question that NONE of the retrieved entries mention.

    "How much is a hair transplant?" -> ["hair", "transplant"]: the clinic has no information
    about that, so the assistant must not guess a price.
    """
    kb = knowledge.load()
    idx = _index(kb)
    known: set = set()
    for source in sources:
        known |= idx.entry_terms.get(source.id, set())
    return [t for t in dict.fromkeys(idx.terms(message)) if t not in known and t not in idx.question_terms]
