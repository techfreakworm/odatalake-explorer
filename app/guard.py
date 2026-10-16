"""Output guards: <think> stripping, the NO_ANSWER / OUT_OF_SCOPE markers, and the prompt-leak canary.

The system prompt's first line carries a per-deploy CANARY. Any answer that contains it, or a line of the system
prompt, is scrubbed: the leaked sentences are dropped and the answer becomes "I can't share my instructions." plus
the remaining cited sentences. The stream holds back its last HOLDBACK_CHARS characters, so a canary split across
tokens is never sent, and holds back the start until it cannot be a marker.
"""

from __future__ import annotations

import re

from app.citations import GROUP_RE, segments

MARKERS = ("NO_ANSWER", "OUT_OF_SCOPE")
HOLDBACK_CHARS = 16  # >= len(CANARY) and >= the longest marker
MARKER_RE = re.compile(r"[ \t]*[*_`]*\b(?:NO_ANSWER|OUT_OF_SCOPE)\b[*_`]*[.:!]?")
_THINK_OPEN, _THINK_CLOSE = "<think>", "</think>"
_LEAD_NOISE = " \t\r\n*_`'\">#"
_SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=\S)")


def strip_think(text: str) -> str:
    """Remove reasoning blocks: <think>...</think>, a dangling </think> (reasoning streamed without the opening
    tag) and an unclosed <think> (cut by max_tokens)."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    if _THINK_CLOSE in text:
        text = text.rsplit(_THINK_CLOSE, 1)[1]
    if _THINK_OPEN in text:
        text = text.split(_THINK_OPEN, 1)[0]
    return text.strip()


class ThinkFilter:
    """Streaming version of strip_think for display: drops <think> blocks even when tags are split across deltas.
    (The final answer is always rebuilt from the full raw text with strip_think.)"""

    def __init__(self) -> None:
        self.buf = ""
        self.inside = False

    def feed(self, delta: str) -> str:
        self.buf += delta
        out: list[str] = []
        while self.buf:
            if self.inside:
                i = self.buf.find(_THINK_CLOSE)
                if i < 0:
                    self.buf = self.buf[-(len(_THINK_CLOSE) - 1):]
                    break
                self.buf = self.buf[i + len(_THINK_CLOSE):]
                self.inside = False
                continue
            i = self.buf.find("<")
            if i < 0:
                out.append(self.buf)
                self.buf = ""
                break
            out.append(self.buf[:i])
            self.buf = self.buf[i:]
            if self.buf.startswith(_THINK_OPEN):
                self.buf = self.buf[len(_THINK_OPEN):]
                self.inside = True
            elif self.buf.startswith(_THINK_CLOSE):
                self.buf = self.buf[len(_THINK_CLOSE):]
            elif _THINK_OPEN.startswith(self.buf) or _THINK_CLOSE.startswith(self.buf):
                break  # a tag may be arriving: wait for more text
            else:
                out.append("<")
                self.buf = self.buf[1:]
        return "".join(out)

    def flush(self) -> str:
        out = "" if self.inside else self.buf
        self.buf = ""
        return out


def detect_marker(text: str) -> str | None:
    """The marker the answer starts with (the prompt says to reply with exactly the marker), else None."""
    head = text.lstrip(_LEAD_NOISE)
    for m in MARKERS:
        if head.startswith(m):
            return m
    return None


def remove_markers(text: str) -> str:
    """Drop NO_ANSWER / OUT_OF_SCOPE wherever they appear in prose. Code is never touched (indentation matters)."""
    out = "".join(seg if is_code else MARKER_RE.sub("", seg) for is_code, seg in segments(text))
    return tidy(out)


def tidy(text: str) -> str:
    """Strip trailing spaces and collapse 3+ newlines in prose only; code blocks stay byte for byte."""
    parts = []
    for is_code, seg in segments(text):
        if not is_code:
            seg = re.sub(r"[ \t]+\n", "\n", seg)
            seg = re.sub(r"\n{3,}", "\n\n", seg)
        parts.append(seg)
    return "".join(parts).strip()


def _norm(text: str) -> str:
    text = re.sub(r"[*_`>#]", "", text.lower())
    return re.sub(r"\s+", " ", text).strip()


def _prompt_phrases(rules_text: str, canary: str, min_words: int = 5) -> list[str]:
    """Distinctive pieces of the system prompt: each line and each sentence with at least min_words words.
    Lines are hard-wrapped mid-sentence, so both forms are kept; a verbatim leak matches at least one."""
    pieces: list[str] = []
    lines = [re.sub(r"^\d+\.\s+", "", ln.strip()) for ln in rules_text.replace(canary, " ").splitlines()]
    for ln in lines:
        pieces.append(ln)
        pieces.extend(re.split(r"(?<=[.!?:])\s+", ln))
    pieces.extend(re.split(r"(?<=[.!?:])\s+", " ".join(ln for ln in lines if ln)))
    out: list[str] = []
    for p in pieces:
        n = _norm(p)
        if len(n.split()) >= min_words and n not in out:
            out.append(n)
    return out


class LeakGuard:
    def __init__(self, canary: str, rules_text: str):
        self.canary = canary.lower()
        self.phrases = _prompt_phrases(rules_text, canary)

    def contains_leak(self, text: str) -> bool:
        if not text:
            return False
        if self.canary and self.canary in text.lower():
            return True
        norm = _norm(text)
        return any(p in norm for p in self.phrases)

    def scrub(self, text: str) -> str:
        """Drop every unit (sentence, list line or code block) that leaks; keep only cited prose units and the code
        blocks that follow a kept unit. Returns "" when nothing cited and clean is left."""
        paragraphs: list[str] = []
        prev_kept = False
        for block in re.split(r"\n\s*\n", text.strip()):
            if not block.strip():
                continue
            if block.lstrip().startswith(("```", "~~~")):
                if prev_kept and not self.contains_leak(block):
                    paragraphs.append(block)
                continue
            kept_lines = []
            for line in block.split("\n"):
                kept = [s for s in _SENT_SPLIT_RE.split(line)
                        if s.strip() and not self.contains_leak(s) and _has_citation(s)]
                if kept:
                    kept_lines.append(" ".join(kept))
            prev_kept = bool(kept_lines)
            if kept_lines:
                paragraphs.append("\n".join(kept_lines))
        return "\n\n".join(paragraphs).strip()


def _has_citation(text: str) -> bool:
    return any(not is_code and GROUP_RE.search(seg) for is_code, seg in segments(text))


class StreamSanitizer:
    """Decides which model text may go out as SSE token events.

    - Holds the start back until it cannot be NO_ANSWER / OUT_OF_SCOPE; a start marker stops all token output.
    - Holds back the last HOLDBACK_CHARS characters, so a canary is complete (and detected) before any of it goes out.
    - Stops for good on a leak (canary or a system-prompt line); removes markers that appear mid-text.
    The caller always sends the final, validated answer in `done`, which the UI renders in place of the tokens.
    """

    def __init__(self, guard: LeakGuard, holdback: int = HOLDBACK_CHARS):
        self.guard = guard
        self.hold = holdback
        self.text = ""
        self.emitted = 0
        self.started = False
        self.marker: str | None = None
        self.leak = False
        self.stopped = False

    def feed(self, delta: str) -> str:
        if self.stopped or not delta:
            return ""
        self.text += delta
        if not self._checks(final=False):
            return ""
        return self._emit(len(self.text) - self.hold)

    def finish(self) -> str:
        if self.stopped or not self._checks(final=True):
            return ""
        return self._emit(len(self.text))

    def _checks(self, final: bool) -> bool:
        if self.guard.contains_leak(self.text):
            self.leak = self.stopped = True
            return False
        if not self.started:
            head = self.text.lstrip(_LEAD_NOISE)
            marker = detect_marker(head)
            if marker:
                self.marker = marker
                self.stopped = True
                return False
            if not final and (not head or any(m.startswith(head) for m in MARKERS)):
                return False  # could still turn into a marker
            self.started = True
        return True

    def _emit(self, end: int) -> str:
        if end <= self.emitted:
            return ""
        out, pos = [], self.emitted
        for m in MARKER_RE.finditer(self.text, self.emitted):
            if m.start() >= end:
                break
            out.append(self.text[pos:m.start()])
            pos = max(pos, m.end())
        if pos < end:
            out.append(self.text[pos:end])
            pos = end
        self.emitted = max(self.emitted, pos)
        return "".join(out)
