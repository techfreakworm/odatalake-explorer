"""Gate decisions on the real index (marker e2e, but no server and no ollama).

Every eval question and every probe in eval/gate_probes.py goes once through AskService with the index in
data/index/CURRENT, its real query embedder, the default ABSTAIN_THRESHOLD of 0.69 and a fake LLM. What is measured is
which messages the dense gate declines now that the product-intro override (app/product_intro.py) lifts the decline
for a general intro question:

- the eval set's gate declines stay exactly those in eval/results/final.json: UNK-06, OOS-01, OOS-02, OOS-04, OOS-06;
- every intro probe reaches the LLM;
- every off-topic probe keeps the decline;
- a guard probe never fires the override, so it is declined exactly when its gate score is below the threshold.

A missing index or embedding model skips these tests, or fails them when E2E_REQUIRED=1 (conftest.py).
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from pathlib import Path

import pytest

from app import product_intro
from app.config import Settings
from app.embedder import FastEmbedQueryEmbedder
from app.index_store import IndexHolder, IndexLoadError, load_snapshot
from app.limits import DailyTokenBudget, TokenBucket
from app.pipeline import AskOutcome, AskRequest, AskService
from eval.gate_probes import GUARD_PROBES, INTRO_PROBES, OFF_TOPIC_PROBES
from eval.questions import load_questions
from tests.app.fakes import FakeLLM
from tests.e2e.conftest import _missing

pytestmark = pytest.mark.e2e

REPO = Path(__file__).resolve().parents[2]
INDEX_DIR = REPO / "data" / "index"
FINAL = REPO / "eval" / "results" / "final.json"
THRESHOLD = 0.69  # the default ABSTAIN_THRESHOLD, which every expectation here is calibrated at
EVAL_DECLINES = {"UNK-06", "OOS-01", "OOS-02", "OOS-04", "OOS-06"}  # reason retrieval_gate in final.json


@dataclass(frozen=True)
class Run:
    version: str
    outcomes: dict[str, AskOutcome]
    llm_calls: dict[str, int]

    def label(self, q: str) -> str:
        out = self.outcomes[q]
        score = "none" if out.gate_score is None else f"{out.gate_score:.4f}"
        return f"{q!r} (gate score {score}, reason {out.reason})"


@pytest.fixture(scope="module")
def run() -> Run:
    """Every eval question and probe through the real index and embedder once, with no cache and no limits."""
    if not (INDEX_DIR / "CURRENT").is_file():
        _missing(f"no index: build one first (uv run python -m index.build); looked in {INDEX_DIR}")
    try:
        snap = load_snapshot(INDEX_DIR, blog=False)
    except IndexLoadError as e:
        _missing(f"the index in {INDEX_DIR} does not load: {e}")
    cache_dir = Path(os.environ.get("FASTEMBED_CACHE_PATH", ".cache/models"))
    if not cache_dir.is_absolute():
        cache_dir = REPO / cache_dir
    try:
        embedder = FastEmbedQueryEmbedder(snap.embed_model, threads=1, cache_dir=cache_dir)
    except Exception as e:  # noqa: BLE001 - not cached and no way to download it
        _missing(f"query embedder {snap.embed_model} unavailable (cache {cache_dir}): {type(e).__name__}: {e}")
    settings = Settings(index_dir=INDEX_DIR)
    assert settings.abstain_threshold == THRESHOLD
    llm = FakeLLM("NO_ANSWER")
    svc = AskService(settings, IndexHolder(snap), llm, embedder=embedder,
                     bucket=TokenBucket(rate_per_min=1e6, burst=10**6), budget=DailyTokenBudget(0))
    questions = [r["question"] for r in load_questions()] + INTRO_PROBES + OFF_TOPIC_PROBES + GUARD_PROBES

    async def go() -> tuple[dict[str, AskOutcome], dict[str, int]]:
        outcomes, calls = {}, {}
        for q in dict.fromkeys(questions):
            before = len(llm.calls)
            outcomes[q] = await svc.answer(AskRequest(question=q, request_id="gate-calibration", no_cache=True))
            calls[q] = len(llm.calls) - before
        return outcomes, calls

    outcomes, calls = asyncio.run(go())
    return Run(snap.version, outcomes, calls)


def test_the_eval_set_gate_declines_are_exactly_those_of_the_final_eval(run):
    pinned = {r["id"] for r in json.loads(FINAL.read_text())["rows"] if r.get("reason") == "retrieval_gate"}
    assert pinned == EVAL_DECLINES, f"eval/results/final.json declines {sorted(pinned)}"
    rows = load_questions()
    assert len(rows) == 94
    declined = {r["id"] for r in rows if run.outcomes[r["question"]].reason == "retrieval_gate"}
    wrong = [f"{r['id']} {'declined' if r['id'] in declined else 'not declined'}: {run.label(r['question'])}"
             for r in rows if (r["id"] in declined) != (r["id"] in pinned)]
    assert not wrong, f"gate declines on index {run.version} differ from eval/results/final.json: " + "; ".join(wrong)


def test_every_intro_probe_reaches_the_llm(run):
    wrong = [run.label(q) for q in INTRO_PROBES
             if run.outcomes[q].reason in ("retrieval_gate", "smalltalk") or run.llm_calls[q] == 0]
    assert not wrong, f"intro probes that never reached the LLM on index {run.version}: " + "; ".join(wrong)


def test_every_off_topic_probe_keeps_the_gate_decline(run):
    wrong = [run.label(q) for q in OFF_TOPIC_PROBES
             if run.outcomes[q].reason != "retrieval_gate" or run.llm_calls[q] != 0]
    assert not wrong, f"off-topic probes that got past the gate on index {run.version}: " + "; ".join(wrong)


def test_a_guard_probe_gets_what_the_gate_alone_gives(run):
    wrong = []
    for q in GUARD_PROBES:
        out = run.outcomes[q]
        if product_intro.is_product_intro(q):
            wrong.append(f"{run.label(q)} fires the override")
        elif out.gate_score is None or (out.reason == "retrieval_gate") != (out.gate_score < THRESHOLD):
            wrong.append(run.label(q))
    assert not wrong, (f"guard probes not declined exactly when their gate score is below {THRESHOLD} on index "
                       f"{run.version}: " + "; ".join(wrong))
