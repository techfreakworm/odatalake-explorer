"""General questions about the product ("who is OLake?", "tell me about Ask OLake"), which pass the off-topic gate.

The dense gate scores them below ABSTAIN_THRESHOLD ("what can olake do for me?" 0.6715, "who is olake" 0.6675, "tell
me about olake" 0.6654, "what is ask olake?" 0.6593 and "who is ask olake?" 0.6205 on index 20261016T2259Z, against
0.69), so they got the off-topic decline. The indexed pages (the olake README, the OLake Go and Fusion pages) answer
the OLake, Fusion and Go questions; no indexed page describes Ask OLake itself, so the model answers those from its
own instructions. A lower threshold is no fix: UNK-06, which must abstain, scores 0.6708. is_product_intro() is narrow
on purpose: it fires only when the WHOLE message is one of the intro frames below around a product name, in plain
text (an emoji, a symbol, a mark or an invisible character turns it off), so "tell me about olake pricing" or "write a
poem about olake" stay the gate's to decline. `python -m eval.gate` measures it (eval/results/gate-calibration.json).
"""

from __future__ import annotations

import re
import unicodedata

MAX_CHARS = 80
MAX_WORDS = 12

# Frames over the normalized words of the message: casefolded, apostrophes dropped ("what's" is "whats", "I'd" is
# "id"), punctuation removed. _P is a product name.
_P = r"(?:the )?(?:olake(?: fusion| go)?|ask olake)"
_FRAMES = [
    _P,
    rf"(?:what is|whats|who is|whos) {_P}(?: (?:used for|for|all about))?",
    rf"(?:(?:can|could) you )?(?:please )?tell me (?:(?:more|a bit|a little) )?about {_P}",
    rf"(?:i want|i would like|i ?d like) to know (?:more )?about {_P}",
    rf"about {_P}",
    rf"(?:(?:can|could) you )?(?:please )?(?:explain|describe|introduce|summari[sz]e) {_P}",
    rf"(?:give me )?(?:an? )?(?:overview|intro|introduction|summary) (?:of|to) {_P}",
    rf"{_P} (?:overview|intro)",
    rf"what (?:can|does) {_P} do(?: for (?:me|us))?",
    rf"what can i do with {_P}",
    rf"how does {_P} work",
    rf"why (?:(?:should i|should we|would i|do i) )?use {_P}",
    rf"what are (?:(?:the )?features of {_P}|{_P}s features)",
    rf"what is {_P} and what (?:can|does) it do",
    rf"who (?:makes|made|built|builds|created|develops|developed|maintains|owns|is behind) {_P}",
]
# one frame, with optional greeting or filler words in front and politeness or filler words after it
_INTRO = re.compile(rf"(?:(?:hi|hey|hello|so|ok|okay) )*(?:{'|'.join(_FRAMES)})"
                    rf"(?: (?:please|pls|plz|exactly|briefly|again))*")
_SUBSTITUTE = str.maketrans({"'": "", "\N{LEFT SINGLE QUOTATION MARK}": "", "\N{RIGHT SINGLE QUOTATION MARK}": ""})


def is_product_intro(question: str) -> bool:
    """True when the whole message is one general question about OLake, OLake Fusion, OLake Go or Ask OLake."""
    if len(question.strip()) > MAX_CHARS:
        return False
    text = unicodedata.normalize("NFKC", question)  # fullwidth, circled and math-bold letters fold to plain ones
    # plain text only: letters, digits, punctuation and whitespace; anything else (emoji, symbols, marks, zero-width or
    # tag characters, private-use and unassigned code points) could hide a request, so the gate decides by score
    if any(not c.isspace() and unicodedata.category(c)[0] not in "LNP" for c in text):
        return False
    words = re.findall(r"[^\W_]+", text.casefold().translate(_SUBSTITUTE))
    return 0 < len(words) <= MAX_WORDS and _INTRO.fullmatch(" ".join(words)) is not None
