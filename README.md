# odatalake-explorer

Research and planning for the "Ask OLake" challenge at Hacktoberfest Hack Day Bengaluru x OLake, Sunday 2026-10-18
([event page](https://events.mlh.com/events/15468-hacktoberfest-hack-day-bengaluru-x-olake),
[challenges page](https://www.mlh.com/events/lakehouse-bot-day-hacktoberfest-bengaluru-x-olake/challenges)).
The product is a cited docs assistant with a public `POST /ask` and an embeddable chat UI. It is built at the event, in a
separate repo. This repo holds the research, the event runbook, and the measurement code that checks the plan.

## Docs

| Doc | Contents |
|---|---|
| [docs/plan.md](docs/plan.md) | The event runbook: architecture, fixed interfaces, preparation before Sunday, the 10:30-14:30 timeline, agent-team prompts and briefs, checkpoints, cut lines, the patch loop, the freeze checklist, the demo script and contingencies |
| [docs/open-questions.md](docs/open-questions.md) | Questions for the organizers at kickoff, ordered by impact, and the operator's decisions with deadlines |
| [docs/research.md](docs/research.md) | Findings, comparisons, and the decisions with their reasons, plus the measurement table |
| [docs/eval-questions.md](docs/eval-questions.md) | The eval question table and how it is scored |

## POC

`poc/` holds measurement scripts, not the product. They measure the corpus, chunking, freshness signals, retrieval and the
eval scorer, and write their numbers to `poc/results/*.json`. The docs cite those files. To run them you need uv and
Python 3.12. Set `ASK_OLAKE_CACHE` to a scratch directory outside the repo, then follow [poc/README.md](poc/README.md) for
the steps and commands.
