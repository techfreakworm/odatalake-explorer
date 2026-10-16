from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from eval.questions import QUESTIONS_FILE, load_questions, normalize_url, parse_table

ROOT = Path(__file__).resolve().parents[2]


def test_questions_md_is_a_byte_copy_of_the_docs_table():
    assert QUESTIONS_FILE.read_bytes() == (ROOT / "docs" / "eval-questions.md").read_bytes()


def test_real_table_counts():
    qs = load_questions()
    assert len(qs) == 94
    assert Counter(q["type"] for q in qs) == {"answerable": 69, "negative": 5, "false-premise": 4, "adversarial": 4,
                                              "out-of-scope": 6, "unanswerable": 6}
    assert sum(q["must_abstain"] for q in qs) == 12
    assert sum(bool(q["expected_sources"]) for q in qs) == 82
    assert len({q["id"] for q in qs}) == 94
    oos = next(q for q in qs if q["type"] == "out-of-scope")
    assert oos["expected_sources"] == [] and oos["behavior"] and oos["behavior"][0].startswith("BEHAVIOR:")
    for q in qs:
        assert all(not f.upper().startswith("BEHAVIOR:") for f in q["must_mention"])


SYNTH = """# Intro

| Not | the | table |
|---|---|---|
| a | b | c |

| ID | Category | Type | Question | Expected sources | Must mention |
|---|---|---|---|---|---|
| T-01 | setup | answerable | Does `a \\| b` work? | https://olake.io/docs/a/<br>https://olake.io/docs/b/ | uses `x \\| y`; and z<br>second fact |
| T-02 | out-of-scope | out-of-scope | Weather? | — | BEHAVIOR: decline. Script: sources non-empty. |
| T-03 | setup | adversarial | Q? | [link](https://olake.io/docs/c/) | — |
| short | row |
"""


def test_synthetic_table_rules():
    rows = parse_table(SYNTH)
    assert [r["id"] for r in rows] == ["T-01", "T-02", "T-03"]
    t1, t2, t3 = rows
    assert t1["question"] == "Does `a | b` work?"  # \\| unescapes, and does not split the cell
    assert t1["expected_sources"] == ["https://olake.io/docs/a/", "https://olake.io/docs/b/"]
    assert t1["must_mention"] == ["uses `x | y`; and z", "second fact"]  # <br> splits, ';' does not
    assert t2["expected_sources"] == [] and t2["must_mention"] == []  # — means none
    assert t2["behavior"] == ["BEHAVIOR: decline. Script: sources non-empty."]
    assert t3["expected_sources"] == ["https://olake.io/docs/c/"] and t3["must_mention"] == []


@pytest.mark.parametrize("raw,norm", [
    ("https://olake.io/docs/connectors/postgres/", "olake.io/docs/connectors/postgres"),
    ("http://www.OLake.io/docs/connectors/postgres#cdc", "olake.io/docs/connectors/postgres"),
    ("https://olake.io/docs/connectors/postgres/?tab=cli", "olake.io/docs/connectors/postgres"),
    ("olake.io/docs/x/", "olake.io/docs/x"),
    ("https://github.com/datazip-inc/olake/blob/master/README.md", "github.com/datazip-inc/olake/README.md"),
    ("https://github.com/datazip-inc/olake/blob/d20c68e/README.md?plain=1#L1-L9", "github.com/datazip-inc/olake/README.md"),
    ("https://github.com/datazip-inc/olake/tree/main/drivers", "github.com/datazip-inc/olake/drivers"),
    ("https://raw.githubusercontent.com/datazip-inc/olake/master/README.md", "github.com/datazip-inc/olake/README.md"),
    ("https://github.com/datazip-inc/olake", "github.com/datazip-inc/olake/README.md"),
    ("https://github.com/datazip-inc/olake/releases/tag/v0.12.1", "github.com/datazip-inc/olake/releases/tag/v0.12.1"),
    ("<https://olake.io/docs/>", "olake.io/docs"),
    ("", ""),
])
def test_normalize_url(raw, norm):
    assert normalize_url(raw) == norm
