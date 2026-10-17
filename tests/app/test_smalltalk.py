"""Small talk and capability questions (app/smalltalk.py, prompts.smalltalk_text): only a whole message of short small
talk gets the canned intro; anything with OLake or technical content, "what is OLake?" included, reaches retrieval."""

import re

import pytest

from app import guard, prompts, smalltalk
from eval.questions import load_questions

WAVE = "\N{WAVING HAND SIGN}"
SKIN_TONE = "\N{EMOJI MODIFIER FITZPATRICK TYPE-4}"
CURLY_APOSTROPHE = "\N{RIGHT SINGLE QUOTATION MARK}"
OPENERS = {"hello": "Hi!", "thanks": "You're welcome!", "bye": "Bye for now!"}
TOPICS = ("setup", "sources", "sync modes", "catalogs", "fusion", "deployment", "troubleshooting")

HELLO = [
    "Howdy", "What can you do for me?",  # the two live-demo reports
    "hi", "Hi!", "HI", "hello", "Hello.", "hey", "hey there", "HEY THERE!!!", "hello there", f"hi there {WAVE}", WAVE,
    f"hi {WAVE}{SKIN_TONE}", "hiii", "heyyy", "hellooo", "hiya", "yo", "good morning", "Good evening!", "morning!",
    "how are you?", "how's it going?", f"how{CURLY_APOSTROPHE}s it going", "what's up",
    "who are you?", "Who are you", "what are you?", "what's your name?", "what is your name",
    "what can you do", "What can you do?", "what can you help me with?", "how can you help?", "how can you help me",
    "help", "Help!", "help me", "help please", "can you help me?",
    "hi, what can you do?", "hello there, who are you?", "Hey! What can you do for me?",
    "hi olake", "Hey Ask OLake!", f"hello OLake {WAVE}",
]
THANKS = ["thanks", "Thanks!", "thank you", "Thank you so much!", "thx", "ty", "cheers", "ok thanks", "thanks a lot",
          "many thanks", "thanks olake"]
BYE = ["bye", "Bye!", "goodbye", "good bye", "see you", "see you later", "good night"]

NOT_SMALL_TALK = [
    # a greeting or a thank-you in front of a real question or problem
    "hi, how do I install OLake UI?", "hello, does OLake support Oracle CDC?", "hi, my sync job failed",
    "thanks, but the sync still fails",
    # off-topic requests stay the retrieval gate's job
    "what is the weather in Paris", "write me a poem",
    # questions about the product are questions for the docs
    "what is olake?", "What is OLake", "what's olake", "who is olake", "what can olake do?", "what does olake do",
    "tell me about olake", "olake?", "olake", "hi, what is olake?", "what is ask olake?", "help me install olake",
    "can you help me set up MySQL?",
    # context-dependent follow-ups must reach retrieval with their history
    "how does this work?", "how does it work", "what about MySQL?",
    # not small talk at all
    "hello world", "ok", "yes", "cool", "?", "!!!", "\N{SLIGHTLY SMILING FACE}",
    pytest.param("", id="empty"), pytest.param("   ", id="blank"),
    "hi hi hi hi hi hi hi hi hi hi hi hi",  # 12 words
]


def examples(text: str) -> list[str]:
    return [ln for ln in text.splitlines() if ln.startswith("- ")]


def shared_suffix(texts: list[str]) -> str:
    n = 0
    while all(len(t) > n for t in texts) and len({t[-1 - n] for t in texts}) == 1:
        n += 1
    return texts[0][len(texts[0]) - n:]


def test_kinds():
    assert smalltalk.KINDS == ("hello", "thanks", "bye")


@pytest.mark.parametrize("q,kind", [(q, "hello") for q in HELLO] + [(q, "thanks") for q in THANKS]
                         + [(q, "bye") for q in BYE])
def test_small_talk_is_detected(q, kind):
    assert smalltalk.detect(q) == kind


@pytest.mark.parametrize("q", NOT_SMALL_TALK)
def test_everything_else_is_not_small_talk(q):
    assert smalltalk.detect(q) is None


def test_no_eval_question_is_small_talk():
    rows = load_questions()
    assert len(rows) == 94
    fired = {r["id"]: kind for r in rows if (kind := smalltalk.detect(r["question"])) is not None}
    assert fired == {}


@pytest.mark.parametrize("q,kind", [
    ("hi, thanks", "hello"),
    ("thanks, bye!", "thanks"),
    ("thanks! what can you do?", "hello"),
    ("bye, thanks!", "thanks"),
    ("thank you, goodbye", "thanks"),
])
def test_mixed_small_talk_is_hello_then_thanks_then_bye(q, kind):
    assert smalltalk.detect(q) == kind


def test_more_than_80_characters_is_not_small_talk():
    q = "Thank you so much" + "!" * 64
    assert len(q) == 81
    assert smalltalk.detect(q) is None


def test_more_than_10_words_is_not_small_talk():
    q = "hello there, who are you? what can you do for me?"
    assert len(re.findall(r"[a-z]+", q)) == 11
    assert smalltalk.detect(q) is None


@pytest.mark.parametrize("kind,opener", list(OPENERS.items()))
def test_reply_text(kind, opener):
    text = prompts.smalltalk_text(kind)
    assert text.startswith(opener)
    assert "Ask OLake" in text
    low = text.lower()
    for topic in TOPICS:
        assert topic in low, topic
    assert "docs" in low and "github" in low
    lines = examples(text)
    assert len(lines) == 3, lines
    assert [ln.rstrip() for ln in text.strip().splitlines()[-3:]] == [ln.rstrip() for ln in lines]  # ends with them
    for ln in lines:
        q = ln[2:].strip()
        assert q.endswith("?"), ln
        assert smalltalk.detect(q) is None, q  # a real question, which goes to retrieval
    assert re.search(r"\[\d+\]", text) is None
    assert guard.detect_marker(text) is None and "NO_ANSWER" not in text and "OUT_OF_SCOPE" not in text
    assert text != prompts.SHORT_CIRCUIT_TEXT and "couldn't find" not in low


def test_the_three_replies_share_one_body_and_its_examples():
    texts = [prompts.smalltalk_text(kind) for kind in OPENERS]
    assert len(set(texts)) == 3
    body = shared_suffix(texts)  # everything after the kind-specific openers
    for topic in TOPICS:
        assert topic in body.lower(), topic
    assert len(examples(body)) == 3
    assert all(examples(t) == examples(body) for t in texts)
