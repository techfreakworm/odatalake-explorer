"""The product-intro override (app/product_intro.py): is_product_intro is true only when the whole message is one
general intro question about the product ("tell me about olake", "who is ask olake?"). The product name around an
off-topic request, inside a real docs question, or in a message over 80 characters or 12 words never fires it."""

import re

import pytest

from app import product_intro, smalltalk
from eval.gate_probes import GUARD_PROBES, INTRO_PROBES, OFF_TOPIC_PROBES
from eval.questions import load_questions

CURLY_APOSTROPHE = "\N{RIGHT SINGLE QUOTATION MARK}"
WIDE_OLAKE = "".join(chr(ord(c) + 0xFEE0) for c in "OLake")  # fullwidth letters, which NFKC folds to "OLake"

# one or more messages per frame of the contract, beyond the intro probes
FRAMES = [
    # what is / whats / who is P, optionally followed by "used for", "for" or "all about"
    "what is olake for?", "what's olake all about?", "who is olake fusion?",
    # (can you / could you / please) tell me (more / a bit / a little) about P
    "could you tell me about olake?", "please tell me about ask olake", "tell me more about olake",
    "tell me a bit about olake go", "can you tell me a little about olake fusion?",
    # i want / would like / d like to know (more) about P
    "I would like to know about OLake", "I'd like to know more about OLake",
    f"I{CURLY_APOSTROPHE}d like to know about olake", "i want to know more about olake fusion",
    # about P
    "about olake fusion",
    # (can you / could you / please) explain / describe / introduce / summarize P
    "can you explain olake fusion?", "could you describe olake?", "please introduce ask olake", "introduce olake",
    "summarize olake",
    # (give me) (an) overview / intro / introduction / summary of / to P
    "overview of olake", "give me an intro to olake", "an introduction to olake fusion", "summary of olake go",
    # P overview / intro
    "olake overview", "olake fusion intro",
    # what can / does P do (for me / for us)
    "what does olake fusion do for us?",
    # what can i do with P
    "what can i do with olake?",
    # how does P work, with the optional leading "the"
    "how does olake fusion work?", "how does the olake fusion work?",
    # why (should i / should we / would i / do i) use P
    "why should we use olake fusion?", "why would i use olake?", "why use olake?",
    # what are (the) features of P, or what are Ps features
    "what are the features of olake?", "what are olake fusion's features?",
    # what is P and what can / does it do
    "what is olake and what can it do?", "what is olake fusion and what does it do?",
    # who makes / made / built / builds / created / develops / developed / maintains / owns / is behind P
    "who made olake?", "who created olake?", "who develops olake?", "who developed olake fusion?",
    "who maintains olake?", "who owns olake?", "who is behind ask olake?",
    # a head word (hi, hey, hello, so, ok, okay) or a tail word (please, pls, plz, exactly, briefly, again)
    "hello, what is olake?", "ok, tell me about olake", "okay explain olake fusion", "so who makes olake?",
    "explain olake briefly", "what is olake again?", "tell me about olake pls", "describe olake plz",
]

# normalized like app/smalltalk.py: NFKC, casefold, apostrophes, punctuation and emoji dropped, whitespace collapsed
NORMALIZED = [
    "OLAKE", "olake?", "  Tell me about   OLake  ", "tell me about olake \N{SLIGHTLY SMILING FACE}", "whats olake",
    "what's olake", f"what are OLake{CURLY_APOSTROPHE}s features?", f"what is {WIDE_OLAKE}?",
    "Tell me about OLake!!!",
]

SMALL_TALK = ["hi", "thanks", "hello there", "thank you so much!", "bye", "what can you do?", "who are you?", "help me",
              "ok", "please", "thanks, olake"]

# the product name inside a longer, real question, or a frame with more words after it
REAL_QUESTIONS = [
    "what is olake's default batch size?", "how do I install olake?", "does olake support oracle cdc?",
    "what is olake fusion compaction?", "tell me about olake's kafka connector", "what can olake do with kafka?",
    "how does olake work with postgres cdc?", "why should i use olake instead of airbyte?",
    "who maintains the olake helm chart?", "give me an overview of olake connectors", "explain olake's architecture",
    "summarize olake release notes", "what are the features of olake ui?", "olake install",
]


def words(text: str) -> list[str]:
    return re.findall(r"[^\W_]+", text)


@pytest.mark.parametrize("q", INTRO_PROBES)
def test_every_intro_probe_is_a_product_intro(q):
    assert product_intro.is_product_intro(q) is True


@pytest.mark.parametrize("q", OFF_TOPIC_PROBES)
def test_no_off_topic_probe_is_a_product_intro(q):
    assert product_intro.is_product_intro(q) is False


@pytest.mark.parametrize("q", GUARD_PROBES)
def test_no_guard_probe_is_a_product_intro(q):
    assert product_intro.is_product_intro(q) is False


def test_no_eval_question_is_a_product_intro():
    rows = load_questions()
    assert len(rows) == 94
    fired = {r["id"]: r["question"] for r in rows if product_intro.is_product_intro(r["question"])}
    assert fired == {}


@pytest.mark.parametrize("q", INTRO_PROBES)
def test_no_intro_probe_is_small_talk(q):
    # small talk runs first in the pipeline: an intro probe it answered would never reach the override or the LLM
    assert smalltalk.detect(q) is None


@pytest.mark.parametrize("q", FRAMES)
def test_every_frame_of_the_contract_is_a_product_intro(q):
    assert product_intro.is_product_intro(q) is True


@pytest.mark.parametrize("q", NORMALIZED)
def test_case_apostrophes_punctuation_emoji_and_width_are_normalized(q):
    assert product_intro.is_product_intro(q) is True


@pytest.mark.parametrize("q", ["", "   ", "\n\t "])
def test_empty_and_blank_messages_are_not_a_product_intro(q):
    assert product_intro.is_product_intro(q) is False


@pytest.mark.parametrize("q", SMALL_TALK)
def test_small_talk_alone_is_not_a_product_intro(q):
    assert product_intro.is_product_intro(q) is False


@pytest.mark.parametrize("q", REAL_QUESTIONS)
def test_the_product_name_inside_a_real_question_is_not_a_product_intro(q):
    assert product_intro.is_product_intro(q) is False


def test_at_most_80_characters_after_stripping():
    fits = "tell me about olake" + "!" * 61
    assert len(fits) == 80
    assert product_intro.is_product_intro(fits) is True
    assert product_intro.is_product_intro("   " + fits + "   ") is True  # surrounding whitespace does not count
    too_long = fits + "!"
    assert len(too_long) == 81 and words(too_long) == ["tell", "me", "about", "olake"]
    assert product_intro.is_product_intro(too_long) is False


def test_at_most_12_words():
    fits = "hey, could you tell me a little about the OLake Fusion please?"
    assert len(words(fits)) == 12
    assert product_intro.is_product_intro(fits) is True
    # one more head or tail word, under 80 characters: never an intro, however head and tail words may combine
    for too_many in ("so hey, could you tell me a little about the OLake Fusion please?",
                     "hey, could you tell me a little about the OLake Fusion please, please?"):
        assert len(words(too_many)) == 13 and len(too_many) <= 80
        assert product_intro.is_product_intro(too_many) is False, too_many
