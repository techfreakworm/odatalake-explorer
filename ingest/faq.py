"""Product FAQs: the FAQPage JSON-LD on https://olake.io/olake-go/ and https://olake.io/olake-fusion/.

One record per question: {page_url, label, n, question, answer}. Answers may hold HTML, which is
reduced to plain text.
"""

from __future__ import annotations

import json
import logging
import re

from bs4 import BeautifulSoup

from ingest import config
from ingest.fetch import fetch_many

log = logging.getLogger("ingest.faq")


def _text(html_or_text: str) -> str:
    text = BeautifulSoup(str(html_or_text), "lxml").get_text(" ")
    return re.sub(r"\s+", " ", text.replace("​", "")).strip()


def _nodes(data) -> list[dict]:
    if isinstance(data, list):
        return [n for d in data for n in _nodes(d)]
    if isinstance(data, dict):
        if "@graph" in data:
            return _nodes(data["@graph"])
        return [data]
    return []


def parse_faq(html: str) -> list[dict]:
    """[{question, answer}] from every FAQPage JSON-LD block on the page, in page order."""
    soup = BeautifulSoup(html, "lxml")
    out = []
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or script.get_text())
        except (json.JSONDecodeError, TypeError):
            continue
        for node in _nodes(data):
            types = node.get("@type")
            if "FAQPage" not in (types if isinstance(types, list) else [types]):
                continue
            for q in node.get("mainEntity") or []:
                question = _text(q.get("name", ""))
                ans = q.get("acceptedAnswer") or {}
                if isinstance(ans, list):
                    ans = ans[0] if ans else {}
                answer = _text(ans.get("text", ""))
                if question and answer:
                    out.append({"question": question, "answer": answer})
    return out


def fetch_faqs(*, offline: bool = False) -> tuple[list[dict], list[dict]]:
    """Returns (faq records, errors)."""
    urls = [u for u, _ in config.FAQ_PAGES]
    results = fetch_many(urls, offline=offline)
    recs, errors = [], []
    for url, label in config.FAQ_PAGES:
        res = results[url]
        if not res.ok:
            errors.append({"url": url, "status": res.status, "error": res.error})
            log.warning("faq page skipped: %s (%s)", url, res.error or res.status)
            continue
        qas = parse_faq(res.text)
        if not qas:
            errors.append({"url": url, "status": res.status, "error": "no FAQPage JSON-LD"})
            log.warning("faq page has no FAQPage JSON-LD: %s", url)
        for n, qa in enumerate(qas):
            recs.append({"page_url": url, "label": label, "n": n, **qa})
    return recs, errors
