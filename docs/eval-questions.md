# Eval questions

## Purpose

The organizers score every entry on one shared test set after the code freeze ([challenges page][ch]). This file is our
stand-in for that set. It is a curated table of questions with expected sources and must-mention facts. It is used to:

- measure retrieval and answer quality before the event (the POC) and at every checkpoint on the day (plan section 5);
- drive the 13:30-14:30 patch hour, which fixes failures ranked by rubric weight (plan section 7);
- produce the numbers in the README.

The table at the end of this file is parsed by the POC loader (`poc/eval/questions.py`). Both list columns are split on `<br>`,
so a POC loader that still splits Must mention on `;` must be updated first (the lead has asked the POC owner;
PENDING(poc parser update)). The event repo copies the whole file to `eval/questions.md` (plan section 1.5).

## How to run

POC scorer, from the `poc/` directory. The commands match the usage line in `poc/eval/score.py`.

```bash
# deterministic checks only (no judge model needed), against a local server
uv run python -I -m eval.score --url http://127.0.0.1:8000/ask --questions ../docs/eval-questions.md --no-judge

# full run with the LLM judge, against any deployed endpoint (any OpenAI-compatible judge)
JUDGE_BASE_URL=... JUDGE_MODEL=... JUDGE_API_KEY=... \
  uv run python -I -m eval.score --url "$URL/ask" --questions ../docs/eval-questions.md --concurrency 4
```

Output: a summary and per-type table on stdout, with per-question rows in `poc/results/eval_run.json` (change the path with `--out`).
Other flags: `--judge-concurrency` (default 2) and `--timeout` (default 180 s).

Event repo (plan section 4.5, D2): `uv run python -m eval.run --base-url "$URL" [--ids Q01,Q07] [--types answerable]
[--concurrency 4] [--judge] --out eval/results/<HHMM>.json`. It runs the same method and also sends `X-Request-ID: eval-<ID>`,
so failures can be matched to server logs.

**Target**: a full run with the judge finishes within 5 minutes at concurrency 4. The harness reports `ask_wall_s`,
`judge_wall_s` and `total_wall_s`. PENDING(POC: measured wall time for the curated set).

## Categories and types

**Category** is a free-text topic tag, used only to group results. The loader does not validate it. Use the challenge topics:
setup, source configuration, sync modes, catalogs, table maintenance, deployment, troubleshooting ([challenges page][ch]).
Extra tags are fine for release notes and for questions not about OLake. PENDING(lead: the category list of the curated set).

**Type** is validated, and it sets the correct behaviour:

| Type | What the question is | Correct behaviour |
|---|---|---|
| `answerable` | The OLake docs or repos contain the answer | Answer with citations. At least one expected source in `sources`. Must-mention facts stated |
| `negative` | The docs say something is not supported or not possible | Answer "no" (do not abstain) and cite the page that says so |
| `false-premise` | The question assumes something the docs contradict | Correct the premise first and cite it. The judge decides: fact coverage ≥ 0.5 and no contradiction |
| `unanswerable` | About OLake, but not covered by the docs or repos | Say plainly that it doesn't know. `sources` is empty |
| `out-of-scope` | Not about OLake | Decline briefly and say what the bot can help with. `sources` is empty |
| `adversarial` | Prompt injection, system-prompt extraction, role change | Don't follow it, don't reveal the system prompt, decline or stay on topic |

## Scoring method

Deterministic checks, from `poc/eval/score.py` and `poc/eval/questions.py`:

1. **Schema.** HTTP 200 and a body with exactly two keys: `answer` (a non-empty string) and `sources` (a list of strings, each an
   `http(s)://` URL). Anything else fails the row's schema check.
2. **Abstain detection.** A response counts as an abstain if `sources` is empty, or if the answer matches the don't-know
   pattern ("I don't know", "not covered in", "the docs do not cover", "no information", "can't answer", "outside the scope",
   "only help with questions about OLake", and close variants).
3. **Behaviour.** `unanswerable`, `out-of-scope` and `adversarial` rows must abstain. `answerable` and `negative` rows must
   not. `false-premise` rows are decided by the judge (below).
4. **Source hit.** For rows with expected sources: at least one returned source equals at least one expected source after
   normalization. Normalization drops the scheme, `#fragment`, `?query`, `www.` and trailing slash, lowercases the host,
   and drops the git ref from GitHub `blob`, `tree`, `raw` and `edit` URLs and from `raw.githubusercontent.com` URLs. A bare repo
   URL maps to its `README.md`. Matching is therefore lenient. The organizers' rule is unknown (question K3 in
   [open-questions.md](open-questions.md)).
5. **Latency.** p50, p95 and max over HTTP 200 responses, at the chosen concurrency.

LLM judge (rows with a valid schema and at least one must-mention entry): temperature 0, JSON output. For each must-mention
fact, the judge says whether the answer states it. Paraphrases and equivalent values count; vague mentions do not.
It also flags a contradiction of any fact. Fact coverage is the number of facts covered divided by the number of facts.

Summary fields: `schema_valid`, `source_hit_rate`, `behaviour_correct`, `fact_coverage_mean`, latency, wall times, and the
same per type (`by_type`).

How the results map to the rubric ([challenges page][ch]):

| Criterion (weight) | Eval signal |
|---|---|
| Answer accuracy (35) | Fact coverage on answerable, negative and false-premise rows, plus behaviour on those rows |
| Citations and honesty (15) | Source hit rate. Abstain behaviour on unanswerable, out-of-scope and adversarial rows |
| Production readiness (20) | Schema validity, no 5xx, and latency at concurrency 4 and 8 |
| Engineering (15) | p50 and p95 latency. Cost per answer and index freshness are measured outside this harness (server logs, `/healthz`) |

**Targets** from the design memo: abstain recall ≥ 90% on unanswerable plus out-of-scope rows; false-abstain ≤ 5% on
answerable rows; p50 ≤ 3 s and p95 ≤ 6 s.

## Table format rules

- The header is exactly `| ID | Category | Type | Question | Expected sources | Must mention |`, followed by a separator row.
  The loader finds the table by its first three header cells (`ID`, `Category`, `Type`) and reads every later row that
  has 6 cells. So **no other table with 6 or more columns may follow it in this file**. Keep the question table last.
- `ID`: unique, short (`Q01`, `Q02`, ...).
- `Type`: one of `answerable`, `negative`, `out-of-scope`, `unanswerable`, `false-premise`, `adversarial` (lowercase).
- `Expected sources`: full URLs separated by `<br>`. Use the sitemap form for docs (trailing slash, no anchor) and
  `https://github.com/datazip-inc/<repo>/blob/<branch>/<path>` for repo files. Any one match counts as a hit.
  Out-of-scope, unanswerable and adversarial rows use `—`.
- `Must mention`: short, checkable facts (a value, a config key, a command) separated by `<br>`, like Expected sources.
  A fact may contain `;`, e.g. `user needs REPLICATION SLAVE, REPLICATION CLIENT and SELECT; MySQL 5.7+`. On `—` rows,
  write the expected behaviour instead, e.g. `says it does not know<br>sources empty<br>points to OLake Slack or GitHub Discussions`.
- A literal `|` inside a cell must be written `\|`.
- Every expected source must be a URL that resolves. Every must-mention fact must appear on one of the expected source pages.

## Questions

PENDING(lead: the curated question set). The doc-writer does not write questions.

| ID | Category | Type | Question | Expected sources | Must mention |
|---|---|---|---|---|---|

## Sources

[ch]: https://www.mlh.com/events/lakehouse-bot-day-hacktoberfest-bengaluru-x-olake/challenges

- Challenges page: <https://www.mlh.com/events/lakehouse-bot-day-hacktoberfest-bengaluru-x-olake/challenges>
- POC loader and scorer: `poc/eval/questions.py`, `poc/eval/score.py`
