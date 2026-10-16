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
| K3 | How are `sources` matched to the expected sources? Exact string or normalized (trailing slash, `#anchor`, http vs https)? Any one or all of them? Do order and count matter, and are extra sources penalized? For repo files, the branch URL (`/blob/master/...`) or a commit permalink? | Citations and honesty is worth 15 ([challenges page][ch]). The URL form we return must match theirs | Canonical sitemap URLs with a trailing slash and no anchor. For repos, `https://github.com/datazip-inc/<repo>/blob/<default-branch>/<path>`. Only the pages the answer cites, in citation order (decision D10) |
| K4 | What does an acceptable "don't know" look like? Is `sources: []` correct on an abstain? Do partial answers earn credit? | The challenge requires the bot to "say clearly when it doesn't know" ([challenges page][ch]) but gives no format | The first sentence says "I don't know" and points to OLake Slack and GitHub Discussions, with `sources: []`. A partial answer cites what it uses and states what is missing |
| K5 | Submission: where (form or portal), which fields (endpoint URL, repo URL, demo URL, video), and is the deadline exactly 14:30 IST? After the freeze, may we restart, fix or redeploy the endpoint? May the index auto-refresh (freshness)? Must the endpoint stay up until results at 17:30? | The page says only "submit your endpoint and repo" at the 14:30 freeze ([event page][ev]). A missing field, or an endpoint we may not fix, can cost the whole entry | Submit at 14:15. No deploys after 14:20. Restart only if the endpoint is down. Auto-refresh off after the freeze unless they allow it (decision D9). Keep it up until 17:30 |
| K6 | Pre-existing work: may we bring a prepared plan, agent prompts, eval questions and research notes? Must all code be written during the event? Is code from before the event allowed? | Disqualification risk. The Ask OLake challenge states no rule. Only the DigitalOcean side prize has an originality rule ([challenges page][ch]) | Bring documents and configuration only. Write all product code during the event. Disclose the preparation in the README (decision D2) |
| K7 | Which outside sources count as valid citations (e.g. Apache Iceberg, PostgreSQL, MySQL, MongoDB docs)? Do they count the same as OLake sources? | Outside sources are allowed "when the docs fall short" ([challenges page][ch]), but the page does not say which | A small allowlist, used only when no OLake source covers the point, and labelled "outside source" in the answer |
| K8 | Does the test set include recent-release or version-specific questions? From what date is their docs snapshot? | Freshness is part of engineering (15). The docs have 24 release-note pages under `/docs/release/` plus 2 under `/docs/fusion/release/` (`poc/results/corpus.json`, 2026-10-16) | Yes. Index the release notes, and show the build time and docs `lastmod` in `/healthz` and the UI footer |
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
| D1 | Host: primary and fallback | Google Cloud Run in asia-south1 with min instances 1; DigitalOcean App Platform (Bengaluru region if offered; DigitalOcean sponsors a side prize, [challenges page][ch]); Fly.io or Render; a Hugging Face Docker Space (free fallback); a Cloudflare quick tunnel from the laptop (emergency only: no uptime guarantee, no SSE, 200 in-flight requests, [quick tunnels][tunnel]) | Memo: primary is the managed container host the operator already has billing on and which passed the Saturday hello-world (plan section 1.4). Fallback: the free Docker Space. Tunnel only in an emergency. Order of preference PENDING(stack report) | Before Sunday (Saturday dry run) |
| D2 | Reuse code from `poc/` at the event? | (a) No: agents write fresh code from the briefs. (b) Port selected modules (HTML to Markdown, chunker, eval harness) and disclose it. (c) Decide after the kickoff answer to K6 | The memo leaves this to the operator and requires disclosure in the README either way. Provisional: (c), defaulting to (a) when the answer is unclear. The briefs in plan section 4 assume (a). PENDING(lead) | At kickoff (K6) |
| D3 | Answer model | A Flash-class hosted model from the credits; Gemma 4 through the Gemini API (the "Best Use of Gemma 4" prize, [challenges page][ch]); another open-weight model (the DigitalOcean prize asks for open-source or open-weight AI, [challenges page][ch]) | The memo's latency **targets** (p50 ≤ 3 s, p95 ≤ 6 s) assume a Flash-class hosted model. Pick Gemma 4 only if the POC eval shows similar accuracy and latency. PENDING(stack report: availability, price, latency; POC eval) | At kickoff (once K1 is answered). Final at the 12:30 checkpoint |
| D4 | Blog posts in the index | Out; in as a lower tier with a rank penalty; in only when docs score low | Memo: in as a lower-priority tier that never outranks a docs page on configuration facts. Final call after the retrieval eval. PENDING(POC retrieval numbers) | Before Sunday. Revisit in the patch hour |
| D5 | GitHub issues and discussions in the index | Out; in | Memo: out of v1, because of volume, noise, staleness and rate limits. Use them in the patch hour only if the eval shows troubleshooting gaps. PENDING(numbers from the repos report) | During the event (13:30) |
| D6 | Repo license | Apache-2.0; MIT | The DigitalOcean prize requires an open-source license ([challenges page][ch]). Either option qualifies. PENDING(lead) | Before Sunday (it goes into the kit) |
| D7 | Budget cap | A spend cap on the personal fallback key; a billing alert on the host | Set both before Sunday. Size the cap from cost per answer. PENDING(stack report prices) | Before Sunday |
| D8 | Zero valid citations after generation | Full abstain; answer marked "low confidence" | Memo: choose from POC data. PENDING(POC abstain measurements) | Before Sunday |
| D9 | Freshness mechanism, and whether it runs after the freeze | An in-app background refresher with an atomic index swap; a scheduled GitHub Action; both; off after the freeze | Memo: incremental ingest keyed on sitemap `lastmod` plus content hash and `git ls-remote` HEAD SHAs, so no GitHub API rate limit applies. A background refresher and/or a scheduled Action. The manifest shows in `/healthz` and the UI footer. On or off after the freeze follows K5. PENDING(eval-ops report) | Mechanism: before Sunday. After-freeze setting: at kickoff (K5) |
| D10 | URL form in `sources` for repo files | Branch form `https://github.com/datazip-inc/<repo>/blob/<branch>/<path>`; commit permalink with a line range | Memo: the branch form in `sources`, because it is the likeliest to match a test set and always resolves. The commit permalink with `#L<a>-L<b>` is used only in the UI | At kickoff (K3) |

## Sources

[ev]: https://events.mlh.com/events/15468-hacktoberfest-hack-day-bengaluru-x-olake
[ch]: https://www.mlh.com/events/lakehouse-bot-day-hacktoberfest-bengaluru-x-olake/challenges
[tunnel]: https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/trycloudflare/

- Event page: <https://events.mlh.com/events/15468-hacktoberfest-hack-day-bengaluru-x-olake>
- Challenges page: <https://www.mlh.com/events/lakehouse-bot-day-hacktoberfest-bengaluru-x-olake/challenges>
- Cloudflare quick tunnels: <https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/trycloudflare/>
- POC measurements: `poc/results/corpus.json`
