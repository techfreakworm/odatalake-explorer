"""Small talk and "what can you do" messages, which get a canned intro (prompts.smalltalk_text) before retrieval.

The dense gate scores a bare greeting below ABSTAIN_THRESHOLD ("Howdy" 0.529 and "What can you do for me?" 0.522 on
index 20261016T2259Z, against 0.69), so these messages got the off-topic decline. detect() is narrow on purpose: it
fires only when the WHOLE message is short small talk made of the phrases below. Anything else, a product question
such as "what is OLake?" or a greeting in front of a real question included, goes to retrieval as before.
"""

from __future__ import annotations

import re
import unicodedata

KINDS = ("hello", "thanks", "bye")  # precedence for a mixed message: "hi, thanks" is hello, "thanks, bye" is thanks
MAX_CHARS = 80
MAX_WORDS = 10

# Phrases over the normalized words of the message: casefolded, apostrophes dropped, punctuation and emoji removed.
_PHRASES = {
    "hello": [
        "h+i+", "h+e+y+", "he+l+o+", "howdy", "hiya", "yo", "hola", "namaste", "bonjour", "morning",
        "good (?:morning|afternoon|evening|day)", "how are you(?: doing)?", "hows it going", "whats up",
        "(?:is )?anyone there", "are you there",
        "who are you", "what are you", "whats your name", "what is your name", "are you (?:an? )?(?:bot|human|ai)",
        "what can you do(?: for me)?", "what do you do", "what can you help(?: me)? with", "how can you help(?: me)?",
        "can you help(?: me)?", "help(?: me)?", "what (?:can|should) i ask(?: you)?",
    ],
    "thanks": ["(?:many thanks|thanks+|thank (?:you|u)|thx|ty)(?: (?:so much|a lot|very much))?"
               "(?: for (?:the|your|all your) (?:quick )?(?:help|answer|info)| for that)?",
               "cheers", "much appreciated", "appreciate it"],
    "bye": ["bye+", "bye bye", "good ?bye", "(?:see (?:you|ya)|cya)(?: (?:later|soon))?", "good night", "take care"],
    # filler, addressee, acknowledgement and praise words, the bot's own name included: never small talk on their own
    "extra": ["there", "all", "everyone", "folks", "team", "friends?", "buddy", "mate", "ok", "okay", "again",
              "please", "pls", "plz", "today", "and", "great", "awesome", "perfect", "nice", "got it", "it works now",
              "that helped", "olake", "ask olake"],
}
_ANY = "|".join(p for phrases in _PHRASES.values() for p in phrases)
# A kind fires when the message splits into phrases and one of them is of that kind (the full match tries every
# split), so "thanks for the help" is thanks: no split of it uses the hello phrase "help".
_KIND = {kind: re.compile(rf"(?:(?:{_ANY}) )*(?:{'|'.join(_PHRASES[kind])})(?: (?:{_ANY}))*") for kind in KINDS}
# A lone wave is a greeting (a skin-tone modifier after it goes with the other symbols); "what's" becomes "whats".
_SUBSTITUTE = str.maketrans({"\N{WAVING HAND SIGN}": " hi ", "'": "", "\N{LEFT SINGLE QUOTATION MARK}": "",
                             "\N{RIGHT SINGLE QUOTATION MARK}": ""})


def detect(question: str) -> str | None:
    """The kind of small talk when the whole message is small talk, else None."""
    if len(question.strip()) > MAX_CHARS:
        return None
    words = re.findall(r"[^\W_]+", unicodedata.normalize("NFKC", question).casefold().translate(_SUBSTITUTE))
    if not words or len(words) > MAX_WORDS:
        return None
    text = " ".join(words)
    return next((kind for kind in KINDS if _KIND[kind].fullmatch(text)), None)
