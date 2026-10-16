"""Check that fact cards only state what their cited pages say.

    uv run python -m index.factcheck     (offline: uses the cached HTML)

For every section of every card in index/factcards/, the version numbers (0.11.0, v0.3.5, 2.4.0)
and `backticked` tokens it contains must appear in the extracted text of at least one page the
section cites (the docs pages, or the FAQ answers for the two product pages). A miss does not
prove a fact wrong, and a hit does not prove it right: this catches typos and facts from the wrong
page, so a human re-reads the flagged lines. The build runs it and records the result.
"""

from __future__ import annotations

import re
import sys

from index.sources import CITE_COMMENT, load_factcards

VERSION = re.compile(r"\bv?(\d+\.\d+(?:\.\d+)?)\b")
CODE = re.compile(r"`([^`]+)`")


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("`", "")).lower()


def tokens_of(line: str) -> set[str]:
    toks = {m.group(1) for m in VERSION.finditer(line)}
    for m in CODE.finditer(line):
        t = m.group(1).strip()
        if len(t) >= 3:
            toks.add(t)
    return toks


def sections(card: dict) -> list[tuple[list[str], list[str]]]:
    """[(cite_urls, fact lines)] per cite-comment scope of the card body."""
    out: list[tuple[list[str], list[str]]] = []
    cites, lines = list(card["cite_urls"]), []
    for line in card["body"].split("\n"):
        m = CITE_COMMENT.match(line)
        if m:
            if lines:
                out.append((cites, lines))
            cites, lines = m.group(1).split(), []
        elif line.strip() and not line.startswith("#"):
            lines.append(line)
    if lines:
        out.append((cites, lines))
    return out


def check_cards(cards: list[dict], page_text: dict[str, str]) -> list[dict]:
    """Missing tokens: [{card, token, line, cites}]. page_text maps a URL to its extracted text."""
    misses = []
    for card in cards:
        if card["name"] == "latest-versions":  # generated from the releases API, not from pages
            continue
        for cites, lines in sections(card):
            corpus = _norm(" ".join(page_text.get(u, "") for u in cites))
            unknown = [u for u in cites if u not in page_text]
            for u in unknown:
                misses.append({"card": card["name"], "token": None, "line": f"cite_url not in corpus: {u}",
                               "cites": cites})
            for line in lines:
                for tok in tokens_of(line):
                    if _norm(tok) not in corpus:
                        misses.append({"card": card["name"], "token": tok, "line": line.strip()[:160],
                                       "cites": cites})
    return misses


def page_texts(corpus) -> dict[str, str]:
    """URL -> searchable text from a build Corpus (docs pages and FAQ answers)."""
    texts = {p["url"]: p["markdown"] for p in corpus.pages}
    for q in corpus.faqs:
        texts[q["page_url"]] = texts.get(q["page_url"], "") + "\n" + q["question"] + "\n" + q["answer"]
    return texts


def main() -> None:
    from index.build import collect_docs, Corpus
    from ingest.faq import fetch_faqs

    corpus = Corpus()
    collect_docs(corpus, offline=True)
    corpus.faqs, _ = fetch_faqs(offline=True)
    misses = check_cards(load_factcards(), page_texts(corpus))
    for m in misses:
        print(f"{m['card']}: {m['token']!r} not on {' '.join(m['cites'])}\n    {m['line']}")
    print(f"{len(misses)} unmatched tokens")
    sys.exit(1 if misses else 0)


if __name__ == "__main__":
    main()
