# Open questions and operator decisions

Two lists. A: questions to put to the organizers at kickoff (10:00-10:30 IST, Sunday 2026-10-18). B: decisions the operator
makes, each with a deadline. The runbook is [plan.md](plan.md), and the reasons are in [research.md](research.md).

Neither public page answers the questions below. Both pages specify the deliverables, the rubric and the schedule. They do
not specify latency or timeout limits, scorer concurrency, how sources are matched, the "don't know" format, submission
mechanics, whether the endpoint must stay live during scoring, or a policy on pre-existing code ([event page][ev],
[challenges page][ch]).

## A. Questions for the organizers at kickoff

Ordered by impact on the score. K1-K6 are the short list in [plan.md section 2](plan.md#2-event-morning-before-1030).
Write each answer into the event repo's `CLAUDE.md` under "Kickoff answers" before the teammates are spawned.

| ID | Question | Why it matters | Default if there is no answer |
|---|---|---|---|
| K1 | LLM credits: which provider, which models, what rate limits (requests and tokens per minute), what budget? Do the keys keep working after the 14:30 freeze, through scoring and the demos (until 17:30)? | Every answer needs the LLM, and scoring happens after the freeze. The pages say credits are provided but name no provider or amount ([event page][ev], [challenges page][ch]) | Assume the credits may throttle or stop after the freeze. Keep the personal fallback trio `LLM_FALLBACK_*` set and the degraded mode on (plan sections 4.3 and 11). Size `MAX_CONCURRENCY` from the smoke test (plan section 2) |
| K2 | How is the test set run: when, from where, at what concurrency, with what per-request timeout, retries and auth? Is it exactly `POST <URL>/ask` with `Content-Type: application/json`? | Production readiness (20) and accuracy (35) are measured on live calls ([challenges page][ch]). A timeout or a 429 from us loses the row | Scoring runs between 14:30 and the 15:30 top-10 announcement ([event page][ev]). Keep the p95 **target** of 6 s, queue instead of rejecting, and keep the rate limit very high |
| K3 | How are `sources` matched to the expected sources? Exact string or normalized (trailing slash, `#anchor`, http vs https)? Any one or all of them? Do order and count matter, and are extra sources penalized? For repo files, the branch URL (`/blob/master/...`) or a commit permalink? Do GitHub release notes and issues count as acceptable citations? | Citations and honesty is worth 15 ([challenges page][ch]). The URL form we return must match theirs | Canonical sitemap URLs with a trailing slash and no anchor. For repos, `https://github.com/datazip-inc/<repo>/blob/<default-branch>/<path>`. Only the pages the answer cites, in citation order (decision D10) |
| K4 | What does an acceptable "don't know" look like? Is `sources: []` correct on an abstain? Do partial answers earn credit? | The challenge requires the bot to "say clearly when it doesn't know" ([challenges page][ch]) but gives no format | The first sentence says "I don't know" and points to OLake Slack and GitHub Discussions, with `sources: []`. A partial answer cites what it uses and states what is missing |
| K5 | Submission: where (form or portal), which fields (endpoint URL, repo URL, demo URL, video), and is the deadline exactly 14:30 IST? After the freeze, may we restart the service, or make a few-line fix if the endpoint breaks? May the index auto-refresh (freshness)? Must the endpoint stay up until results at 17:30? | The page says only "submit your endpoint and repo" at the 14:30 freeze ([event page][ev]). MLH's standard rules say to stop at time-up: small fixes are allowed, large changes and new features are not ([MLH rules][mlh]). A missing field, or an endpoint we may not fix, can cost the whole entry | Submit at 14:15. No deploys after 14:20. After 14:30, only a restart or a few-line fix, and only if the endpoint is broken. Auto-refresh off after the freeze unless they allow it (decision D9). Keep it up until 17:30 |
| K6 | Pre-existing work: may we bring a prepared plan, agent prompts, eval questions and research notes? Is code written before the event (the `poc/` measurement scripts) allowed? Also tell them whether the operator is competing for prizes (it decides D2) | Disqualification risk. The Ask OLake pages state no rule ([challenges page][ch]). MLH's standard rules say all project work happens during the hackathon, and that an earlier idea is fine as long as its code and other project materials are not re-used ([MLH rules][mlh]) | Bring documents and configuration only. Build all code fresh at the event (decision D2). Disclose the preparation in the README |
| K7 | Which outside sources count as valid citations (e.g. Apache Iceberg, PostgreSQL, MySQL, MongoDB docs)? Do they count the same as OLake sources? | Outside sources are allowed "when the docs fall short" ([challenges page][ch]), but the page does not say which | A small allowlist, used only when no OLake source covers the point, and labelled "outside source" in the answer |
| K8 | Does the test set include recent-release or version-specific questions? From what date is their docs snapshot? For "latest version" questions, which is the source of truth: the docs release notes or GitHub releases? | Freshness is part of engineering (15). The docs release notes stop at v0.12.0, while GitHub already has olake v0.12.1 and olake-ui v0.7.1 (2026-10-15; [docs v0.12.0 notes][rel-0120], [GitHub releases][olake-rel]) | Yes. Index the docs release notes and the GitHub releases. Answers say "Docs as of <date>; latest GitHub release <tag>", and `/healthz` and the UI footer show the build time |
| K9 | How is "UX and easy embedding" judged: on their docs site, on our demo page, or from the README snippet? Do they prefer a script tag or an iframe? | UX and easy embedding is worth 15 ([challenges page][ch]) | Our live demo page, a one-line script tag, a plain iframe fallback and a Docusaurus snippet |
| K10 | Single-turn only? Does the scorer send any field besides `question`? | It decides whether `/ask` needs history handling | Single-turn. Unknown fields are ignored |
| K11 | Any constraints on `answer`: Markdown allowed, maximum length, language? | It decides formatting and length | Markdown with fenced code, concise, English |
| K12 | Is a license required for the Ask OLake repo? Can one project also enter the "Best Use of Gemma 4" and "Best Open-Source AI Project" side prizes? | The DigitalOcean prize requires a public GitHub repo under an open-source license and meaningful use of open-source or open-weight AI. The Gemma prize is about Gemma 4 through the Gemini API ([challenges page][ch]) | Add an open-source license (decision D6). Enter a side prize only if the answer-model choice qualifies (decision D3) |
| K13 | Finalist demo format: how long, HDMI or screen share, is there internet at the stage? | Finalist demos run 15:45-17:00 ([event page][ev]). The length per demo is not published | 3 minutes on our own laptop over HDMI, with a screen recording as backup |
| K14 | Will the judges probe adversarial inputs (prompt injection, abuse, very long inputs)? | Production readiness is worth 20, and the bot "will run on a public website" ([challenges page][ch]) | Yes. Inputs over 2000 characters are rejected with 422, injected instructions are ignored, and the system prompt is never revealed (plan section 4.3) |

## B. Operator decisions

"Memo" is the lead's design memo. Its reasons are carried into [research.md](research.md). `PENDING(x)` means the
recommendation waits for a research report or a POC number.

| ID | Decision | Options | Recommendation | Deadline |
|---|---|---|---|---|
| D1 | Host: primary and fallback | Google Cloud Run in asia-south1 with min instances 1; DigitalOcean App Platform (Bengaluru region if offered; DigitalOcean sponsors a side prize, [challenges page][ch]); a free-tier container host (candidates PENDING(stack report)); a Hugging Face Docker Space, which now needs a paid PRO plan to create and whose free CPU Basic hardware sleeps when unused ([HF Spaces overview][hf]); a Cloudflare quick tunnel from the laptop (emergency only: no uptime guarantee, no SSE, 200 in-flight requests, [quick tunnels][tunnel]) | Memo: the primary is the managed container host the operator already has billing on, once it has passed the Saturday hello-world (plan section 1.4). Lead: the fallback is a Hugging Face Docker Space only if the operator already has HF PRO (**question for the operator: do you?**). Otherwise use a free-tier host from the stack report, plus a keep-warm probe during scoring if it sleeps. Tunnel only in an emergency. Order of preference PENDING(stack report) | Before Sunday (Saturday dry run) |
| D2 | Reuse code from `poc/` at the event? | (a) Build fresh from the briefs. `poc/` serves only as a reference for measured parameters (chunk sizes, model IDs, thresholds); nothing is copied. (b) Port `poc/` modules (ingest, chunker), but only after telling the organizers at kickoff (K6) that the operator is not competing for prizes. The lead estimates this saves about 45 minutes, to spend on stretch goals: a low-confidence agentic escalation, translating non-English questions, more outside sources | Lead: **(a), build fresh**. MLH's standard rules put all work inside the event and forbid re-using code or other project materials ([MLH rules][mlh]). The plan section 3 timeline fits a fresh build, and the real experiment is how far agents get in 4 hours. Disclose in the README either way. The Saturday rehearsal code is thrown away (plan section 1.6) | At kickoff (K6) |
| D3 | Answer model | The fast tier of whatever provider the credits cover (K1): a Gemini Flash-class model if the credits are Gemini; an open-weight instruct model on [DigitalOcean's AI platform][do-ai] if they are DigitalOcean; Gemma 4 (largest API size) only if the operator wants the "Best Use of Gemma 4" prize ([challenges page][ch]) | Lead: choose by measurement at 11:30-12:30, not by brand. On a fixed 20-row eval subset, pick the highest must-mention coverage among models with citation-format adherence ≥ 95% and p50 ≤ 3 s (**targets**). Ties go to the cheaper model. Model IDs and prices PENDING(stack report) | At kickoff (once K1 is answered). Final at the 12:30 checkpoint |
| D4 | Blog posts in the index | Out; in as tier 3, down-weighted and dated | Lead: **decided by an A/B run on the eval set at the event** (`BLOG=on` vs `off`, plan section 3 at 13:00). Off until measured. The blog is about 1.8x the docs' size and includes stale 2024-25 posts ([docs-site report][r-docs-site]) | During the event (13:00) |
| D5 | GitHub issues and discussions in the index | Out; bulk; curated | Lead: **curated**. Index 10 troubleshooting answers checked absent from the docs, as tier 2, each cited as "known issue #N". No bulk issues: about a third are bot TODOs, and Discussions has 7 threads with one unanswered Q&A ([repos report][r-repos]) | Decided |
| D6 | Repo license | Apache-2.0; MIT | Lead: **Apache-2.0**. The GitHub API lists all five datazip-inc repos (olake, olake-ui, olake-helm, olake-fusion, olake-docs) as Apache-2.0 (checked 2026-10-16). It meets the DigitalOcean prize's open-source requirement ([challenges page][ch]) and grants a patent license explicitly (section 3 of the [license text][apache]) | Before Sunday (it goes into the kit) |
| D7 | Budget cap | A spend cap on the personal fallback key; a billing alert on the host | Set both before Sunday. Size the cap from cost per answer. PENDING(stack report prices) | Before Sunday |
| D8 | Zero valid citations after generation | Full abstain; answer marked "low confidence" | Memo: choose from POC data. PENDING(POC abstain measurements) | Before Sunday |
| D9 | Freshness mechanism, and whether it runs after the freeze | An in-app poller; a scheduled GitHub Action; both; off after the freeze | Lead: **an in-app poller**. Poll the sitemap every 5-10 minutes with `If-None-Match`; on a deploy, re-fetch the docs and re-embed changed chunks. For repos, `git ls-remote` plus the compare API (research.md §3.6). A scheduled Action is not the primary path: schedules run at most every 5 minutes and can be delayed ([repos report][r-repos]). Whether it runs after the freeze follows K5. PENDING(stack report: whether the host keeps CPU for background work) | Mechanism: decided. After-freeze setting: at kickoff (K5) |
| D10 | URL form in `sources` for repo files | Branch form `https://github.com/datazip-inc/<repo>/blob/master/<path>`; full-SHA permalink with `#La-Lb` (`?plain=1#La-Lb` for Markdown) | Lead: a config switch `SOURCE_URL_STYLE`, **default `branch`**: it is the likelier string match for an unknown grader, and it shows current content. The [repos report][r-repos] recommends SHA links instead, because they are immutable and [GitHub documents][gh-perma] that branch links change. The UI card always shows the SHA permalink | At kickoff (K3) |
| D11 | Index the olake-fusion repo's `docs/` folder (upstream Apache Amoro docs)? | Out; in as a down-weighted `fusion-upstream` tier | Lead: **out**. [olake-fusion][fusion-repo] is a modified hard fork of Apache Amoro, and the upstream docs contradict Fusion's defaults: snapshot expiry is off in Fusion but on upstream, and the target file size is 512 MB vs 128 MB ([repos][r-repos] and [olake-domain][r-olake-domain] reports; [Amoro configurations][amoro-conf]). Use Amoro concepts only through labelled outside pages ("upstream; Fusion may differ"). The Fusion gaps (7 of 23 Fusion pages under 100 tokens, `poc/results/corpus.json`) are covered by fact cards and release notes | Decided |
| D12 | Stub and stale docs pages | Hard-exclude (denylist, logged); keep them with a "stale" flag | Lead: **denylist**, kept in config so it can be reversed. 16 pages (plan Appendix A), including `/docs/core/configs/source/` and `/docs/core/configs/writer/`. Both are short link hubs (1,231 and 1,540 characters of article text when the doc-writer fetched them on 2026-10-16), and source/ still mentions an Oracle "LogMiner setup" although Oracle has no CDC ([olake-domain report][r-olake-domain]). They would compete with the real connector and writer pages | Decided |

## Sources

[ev]: https://events.mlh.com/events/15468-hacktoberfest-hack-day-bengaluru-x-olake
[ch]: https://www.mlh.com/events/lakehouse-bot-day-hacktoberfest-bengaluru-x-olake/challenges
[r-docs-site]: reports/docs-site.md
[r-repos]: reports/repos.md
[r-olake-domain]: reports/olake-domain.md
[tunnel]: https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/trycloudflare/
[hf]: https://huggingface.co/docs/hub/spaces-overview
[mlh]: https://github.com/MLH/mlh-policies/blob/main/standard-hackathon-rules.md
[apache]: https://www.apache.org/licenses/LICENSE-2.0
[do-ai]: https://docs.digitalocean.com/products/gradient-ai-platform/
[fusion-repo]: https://github.com/datazip-inc/olake-fusion
[rel-0120]: https://olake.io/docs/release/ingestion/v0.12.0/
[olake-rel]: https://github.com/datazip-inc/olake/releases
[gh-perma]: https://docs.github.com/en/repositories/working-with-files/using-files/getting-permanent-links-to-files
[amoro-conf]: https://amoro.apache.org/docs/latest/configurations/

- Event page: <https://events.mlh.com/events/15468-hacktoberfest-hack-day-bengaluru-x-olake>
- Challenges page: <https://www.mlh.com/events/lakehouse-bot-day-hacktoberfest-bengaluru-x-olake/challenges>
- Cloudflare quick tunnels: <https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/trycloudflare/>
- Hugging Face Spaces overview (plans, hardware, sleep): <https://huggingface.co/docs/hub/spaces-overview>
- MLH standard hackathon rules: <https://github.com/MLH/mlh-policies/blob/main/standard-hackathon-rules.md>
- Apache License 2.0: <https://www.apache.org/licenses/LICENSE-2.0>
- DigitalOcean Gradient AI platform docs: <https://docs.digitalocean.com/products/gradient-ai-platform/>
- olake-fusion repo: <https://github.com/datazip-inc/olake-fusion>
- OLake docs release notes v0.12.0: <https://olake.io/docs/release/ingestion/v0.12.0/>
- OLake GitHub releases: <https://github.com/datazip-inc/olake/releases>
- GitHub, permanent links to files: <https://docs.github.com/en/repositories/working-with-files/using-files/getting-permanent-links-to-files>
- Apache Amoro configurations: <https://amoro.apache.org/docs/latest/configurations/>
- Research reports (docs-site, repos, olake-domain), 2026-10-16: summarized with their evidence URLs in [research.md §3](research.md#3-corpus)
- Repo licenses: GitHub API `repos/datazip-inc/<repo>`, field `license.spdx_id`, checked 2026-10-16
- POC measurements: `poc/results/corpus.json`
