Research agent output, 2026-10-16; evidence for docs/research.md

# docs-site

## Summary
The OLake docs site (olake.io, Docusaurus v3.10.2 on GitHub Pages behind Fastly) is a small corpus that is easy to ingest and cite. Ingest the rendered HTML from the sitemap, not raw MDX and not llms.txt. Snapshot: 2026-10-16, deploy 09:33:35Z, olake-docs commit d0600714.

1. **Inventory.** The sitemap has 275 URLs and 231 with lastmod. 124 are under /docs/: 101 for OLake Go (the ingestion product's current name) and 23 for Fusion. All come from one docs plugin instance (main-docs) with two sidebars. There is no versioning and no i18n. There are 85 blog posts, plus compare (13), learn (3) and customer-stories (6) posts, each under its own blog instance.
2. **Size.**
   - Docs: 11.17 MB HTML, 998K text chars, 145.6K words, about 238K o200k tokens, 830 code blocks, 182 tables.
   - Blog: about 428K tokens.
   - A full gzip refresh of all docs takes 2.2 s and 2.07 MB at 4 concurrent requests.
   - My chunking proof of concept split the docs into 1,119 chunks (about 284K tokens with context prefixes) and the blog into 1,577 chunks (about 474K).
3. **Why rendered HTML.** Raw MDX misses content on 22 key pages (all connector, catalog and CLI pages). That content comes from 92 MDX partials registered globally and used without imports, 12 JSX config-table components, FlagDetail.tsx (the CLI flags) and DateTimeHandling.tsx. Example: the Postgres jsonb → string type mapping exists only in a partial and in the rendered HTML. The rendered HTML is complete: all 202 tab panels are server-rendered, 122 of them hidden.
4. **No shortcuts exist.** llms.txt is a hand-written link index with no page bodies. llms-full.txt, .md URLs and search-index.json all return 404. Search is Algolia DocSearch (appId 1E406NO1AX, index "olake"). The site has no AI assistant; DocSearch's Ask AI is present in the bundle but not configured. robots.txt allows all crawlers and has no AI-bot rules.
5. **URLs and citations.**
   - The canonical form is https://olake.io/<path>/ with a trailing slash. Slashless, http and www forms all 301 to it.
   - Paths are case-sensitive, and one sitemap URL contains uppercase letters, so never lowercase.
   - 305 legacy paths return HTTP 200 with a meta-refresh, not a 3xx.
   - Heading ids use github-slugger: 163/163 matched and 296/296 internal anchors resolve.
   - Every docs page has an edit link back to its source file, so the 124 pages map exactly to 124 files.
   - Caveat: 191 of 1,274 anchors (15%) sit inside hidden tabs. These need ?config-type=…#id style deep links; all 55 tab labels mapped cleanly to their query values.
6. **Freshness.**
   - Sitemap lastmod equals the UTC date of the last git commit to the page's own file (124/124 checked). 100 of the 124 dates come from a 2026-10-06 sitewide redesign commit, so they say nothing about content changes.
   - Changes inside partials do not move lastmod. Live case: /docs/connectors/overview/.
   - ETag and Last-Modified change for every file on every deploy (6 deploys in about 26 h).
   - Plan: poll the sitemap with If-None-Match (304 verified), re-fetch all docs on each deploy, hash the extracted text, and re-embed only chunks that changed.
7. **Traps the bot must handle.**
   - About 15 stub or stale pages. Two contradict live pages: kafka/overview and connectors/overview still call Kafka "WIP".
   - Near-duplicate Go and Fusion pages (0.95–1.00 text similarity) with identical titles.
   - Ten pages have the H1 "Overview".
   - The docs lag GitHub: release notes stop at v0.12.0 while GitHub has v0.12.1, which the Kafka page already requires.

I wrote eval questions and open questions for these traps; they are in the recommendations and open questions below. The harness blocked the report .md file. The full detail is in this output, with a 124-row TSV and the scripts in the scratch directory.

## Recommendations
- **Build the corpus from rendered HTML on olake.io, driven by the sitemap. Extract .theme-doc-markdown for docs and #__blog-post-container for posts. Use the GitHub MDX only as metadata (change trigger, tab value map, frontmatter), and use llms.txt only as a priority hint list.** — Raw MDX misses partial and JSX content on the 22 most important pages, such as type mappings, config tables and CLI flags. The HTML is complete: all tab panels are server-rendered, and the URLs and anchors match what users and judges see. Crawling is cheap (2 MB gzip, 2 s). llms-full.txt and .md endpoints don't exist. [evidence: https://raw.githubusercontent.com/datazip-inc/olake-docs/d06007140994ecbd239a52a9c0acf81fab4ed530/src/theme/MDXComponents/Index.js; https://olake.io/llms-full.txt (404); measured: scripts/hidden_content.py (22 pages / 51 files), scripts/measure_corpus.py]
- **Chunk at h2/h3. Prefix every chunk with 'title | product (OLake Go or Fusion) > breadcrumbs > heading path [tab label]'. Keep tables and code intact, and split oversized code by lines. Target 150–700 tokens. Store the URL, verified anchor id set, product, section, JSON-LD dateModified, lastmod and source file (from the edit link).** — Ten pages have the H1 'Overview'. Go and Fusion twins are 0.80–1.00 similar and some share identical titles. UI and CLI tabs repeat the same headings, so tab labels and product tags are needed to tell chunks apart. The POC produced good chunks (1,119 for docs). [evidence: measured: scripts/chunk_poc.py, scripts/dup_check.py; https://olake.io/docs/connectors/postgres/]
- **Normalize source URLs as follows:
1. Force https and the apex host olake.io.
2. Never change case.
3. Strip index.html and add a trailing slash.
4. Resolve legacy paths through the site's 305-path redirect table, or by detecting meta-refresh.
5. Drop query strings, except one allowlisted tab parameter when the chunk came from a non-default queryString tab (e.g. ?config-type=olake-cli).
6. Keep a #fragment only if the id exists in that page's stored id set.
7. Require the base URL to be in the current sitemap or an approved GitHub allowlist.
8. Dedupe and cap at 3–5.
9. Never cite stub, redirect or 'coming soon' pages.** — Canonical tags equal the sitemap form on 267/267 pages. Paths are case-sensitive and one real URL has uppercase letters. Legacy URLs return 200, not 3xx. 15% of anchors are inside hidden tabs, and the site itself uses ?param=value#hash links for those. [evidence: https://olake.io/customer-stories/lendingkart-improved-data-correctness/ (404); https://olake.io/docs/connectors/postgres/config/ (meta-refresh); https://olake.io/docs/connectors/postgres/?config-type=olake-cli#1-create-configuration-file; measured: scripts/anchors.py, scripts/tab_values.py]
- **Include sections by tier:
- Tier 1: all of /docs/ (OLake Go + Fusion + release notes + docs/community), minus or demoting the ~15 stubs.
- Tier 2: the 85 blog posts, with a lower weight, the publish date shown, and docs winning on conflict.
- Tier 3, opt-in: compare and learn.
- Exclude: customer stories, community meetup recaps, webinars and events.
- Add GitHub releases and READMEs of olake, olake-ui, olake-fusion and olake-helm as outside sources.** — The docs answer the in-scope question types. The blog fills gaps with deep dives but is 1.8× the docs' size and includes 2024/2025 posts that may be stale, plus general Iceberg content. Compare pages are competitor marketing. GitHub releases lead the docs (v0.12.1 vs v0.12.0). [evidence: measured: scripts/measure_corpus.py section totals; gh api repos/datazip-inc/olake/releases?per_page=5; https://olake.io/docs/connectors/kafka/]
- **Detect changes in this order:
1. Every 5–10 min, poll sitemap.xml with If-None-Match. A 304 means no deploy.
2. On a 200, diff the URL set and re-fetch all 124 docs pages, plus new or lastmod-changed posts.
3. Hash the extracted article text per page and per chunk, re-embed only changed chunks, and tombstone removed URLs.
4. Optionally trigger on the GitHub Actions 'Deploy to GitHub Pages' run completing.
5. Separately poll GitHub releases.

Keep lastmod and dateModified for display only.** — ETag and Last-Modified change for every file on every deploy. lastmod is date-only, 100/124 values reflect a non-content redesign, and partial edits don't move it. A full docs refresh is only about 2 MB and 2 s, and deploys happen about 6 times a day. [evidence: https://olake.io/sitemap.xml (304 verified); gh api repos/datazip-inc/olake-docs/actions/runs?branch=master&per_page=6; measured: scripts/lastmod_vs_git.py, scripts/partial_drift.py]
- **Build the eval set around the corpus traps, with the following question → expected answer pairs:
1. Postgres minimum version → 10+ (/docs/connectors/postgres/#version-prerequisites).
2. wal2json → deprecated; use pgoutput.
3. Postgres jsonb → Iceberg string (#data-type-mapping; partial-only content).
4. Year 0000 dates → 1970-01-01 (#date-and-time-handling; JSX-only content).
5. Is Kafka supported? → yes, via /docs/connectors/kafka/. Trap: stubs still say WIP.
6. Kafka upsert requirements → OLake Go 0.12.1+ and OLake UI 0.7.1+ (#upsert-behavior).
7. Latest OLake release → docs v0.12.0 vs GitHub v0.12.1; the answer should say which source says what.
8. Unity Catalog auth types → PAT, OAuth2 M2M, OAuth2 U2M, Token Federation.
9. Fusion compaction types → Lite, Medium, Full (/docs/fusion/compaction/types-of-compaction/).
10. Fusion air-gapped AWS install → cite the Fusion page, not its Go twin.
11. --destination-database-prefix → adds a destination database name prefix (FlagDetail-only content, /docs/install/docker-cli/).
12. Supported catalogs → Glue, REST, Nessie, Polaris, Unity, Lakekeeper, S3 Tables, JDBC, Hive, BigLake, Horizon.
13. Postgres test-connection checks → wal_level, replication privilege, replication slot, publication.
14. Postgres CLI configuration → needs the tab deep link.
15. Resume a sync from state → /docs/install/docker-cli/#sync, not the moved stub.
16. Snowflake as a source → not documented; the bot should say so.
17. Fusion architecture → the page is image-only; answer honestly.
18. 'OLake Go' → synonym for OLake ingestion.** — Each question exercises a measured risk: partial or JSX content, stale stubs, twin pages, hidden-tab anchors, docs lagging GitHub, and honesty about gaps. Every answer was checked against the fetched pages. [evidence: https://olake.io/docs/connectors/postgres/; https://olake.io/docs/connectors/kafka/; https://olake.io/docs/writers/iceberg/catalog/rest/; https://olake.io/docs/fusion/compaction/types-of-compaction/; https://olake.io/docs/understanding/compatibility-catalogs/; https://olake.io/docs/install/docker-cli/; https://olake.io/docs/release/ingestion/v0.12.0/; gh api repos/datazip-inc/olake/releases?per_page=5]
- **Index with hybrid retrieval (BM25 plus embeddings), and filter by product, section and tier in metadata.** — The docs are code- and identifier-heavy: 23% of characters are code, and they contain flags, config keys and error strings like SQLSTATE 28000 and wal_level. Lexical matching matters for these. [evidence: measured: code_chars 233,233 of 998,144 docs chars (scripts/measure_corpus.py)]

## Measurements
- sitemap URLs / with lastmod: **275 / 231 (docs 124/124, blog 85/86, compare 13/14, customer-stories 6/7, learn 3/4, community 0/14, webinar 0/15, event 0/3)** (scripts/parse_sitemap.py on https://olake.io/sitemap.xml)
- docs pages fetched: **124 × HTTP 200; 11,169,120 B uncompressed in 3.9 s; 2,067,045 B gzip in 2.2 s (4 concurrent)** (scripts/fetch_pages.py (urllib, ThreadPoolExecutor 4); xargs -P4 curl --compressed)
- docs extracted text: **998,144 chars; 145,615 words; 249,488 tokens (chars/4); 238,135 tokens (o200k)** (scripts/measure_corpus.py: .theme-doc-markdown, bs4/lxml, tiktoken o200k_base via uv)
- docs structure counts: **830 <pre> (233,233 code chars); 182 tables; 80 tab containers / 202 panels (122 hidden); 45 details; 342 admonitions; 232 img; 4 iframes; 0 mermaid; 1,274 id-bearing headings** (scripts/measure_corpus.py, scripts/hidden_tab_headings.py)
- docs tokens per page: **min 4, median 1,004, p90 4,238, max 25,991 (writers/iceberg/catalog/rest), mean 1,920** (scripts/measure_corpus.py)
- blog posts (85) extracted: **10,783,366 B HTML; 1,927,068 chars; 297,316 words; 428,473 o200k tokens; median 3,750/post; max 22,579** (scripts/measure_corpus.py on all blog post pages (no sampling))
- other sections o200k tokens: **compare 103,707 (14 pages); learn 13,022 (4); community 11,428 (14); customer-stories 10,640 (7); webinar 8,192 (15); event 1,135 (3)** (scripts/measure_corpus.py (#__blog-post-container or <main>))
- non-docs fetch time: **143 pages, 15,700,254 B, 12.36 s wall (mostly CDN MISS)** (scripts/fetch_pages.py)
- POC chunks (docs): **1,119 chunks; 283,759 tokens with context prefix; median 173, p90 537, p99 1,146, max 5,051; 977 with #anchor; 349 in tabs** (scripts/chunk_poc.py (h2/h3 split, merge <60, split >700))
- POC chunks (blog only): **1,577 chunks; 474,155 tokens (all blog-type posts: 1,999 chunks, 636,964 tokens)** (scripts/chunk_poc.py)
- sitemap lastmod vs git: **124/124 equal to the UTC date of the last commit to the page's own file; JSON-LD dateModified exact for 123/124; 100/124 from sitewide commit bc3013d (2026-10-06)** (scripts/lastmod_vs_git.py (git log -1 --format=%ct on blobless history clone))
- pages depending on partials or JSX hidden from raw MDX: **22 of 124 pages; 51 unique files; ~33.7K source tokens; 92 globally registered partials** (scripts/hidden_content.py, scripts/hidden_tokens.py on the d0600714 clone)
- repo docs files: **225 .mdx (125 routable 1,150,560 B; 99 shared partials 148,253 B; 1 draft) + 12 .jsx; blog 85 .mdx 2,153,840 B; compare 13; customer-stories 6; learn 3** (gh api git/trees/master?recursive=1 + scripts/tree_stats.py)
- anchor verification: **163/163 MDX-derived slugs found in HTML (11 pages); 296/296 internal #fragment links resolve; 14/14 redirect fragments resolve** (scripts/anchors.py)
- anchors inside hidden tabs: **191 of 1,274 (15%), on 21 pages; 55/55 tab labels mapped to queryString values** (scripts/hidden_tab_headings.py, scripts/tab_values.py)
- file→URL mapping: **124/124 verified (HTTP 200, canonical==URL, edit link==file)** (scripts/map_verify.py)
- legacy redirects: **285 entries / 305 source paths / 212 docs-related; served as 200 meta-refresh pages** (parsed the client-redirects-slash config in main.js; curl of /docs/connectors/postgres/config/)
- HTTP validators: **Last-Modified identical on 267/267 pages (deploy 2026-10-16 09:33:35Z); ETag prefix 6ad1ef6f = deploy epoch; Cache-Control max-age=600; 304 on If-None-Match/If-Modified-Since** (header Counter over fetch_*.json; curl conditional GETs)
- deploy cadence: **6 successful deploys in ~26 h; 1m14s–2m40s each; commit-to-live ~2 min** (gh api repos/datazip-inc/olake-docs/actions/runs?branch=master&per_page=6)
- docs commit churn: **522 commits touching docs/ since 2025-01-28; 25 in the last 30 days; 7–47 per month** (git log -- docs/ on blobless history clone)
- Go/Fusion twin similarity: **offline-generic 1.00; offline-aws 0.95; quickstart 0.80; install/olake-ui 0.66; kubernetes 0.58** (scripts/dup_check.py (difflib SequenceMatcher on extracted text))
- stub or stale docs pages: **about 15 (9 Fusion 'coming soon' or image-only; kafka/overview; connectors/overview; core/configs state, catalog, source, writer; tutorials/enable-oplogs; core/architecture image-only)** (scripts/stubs.py plus manual reading)
- orphan docs pages (not in sidebars.js): **29 (mostly setup guides linked in-page)** (ids parsed from sidebars.js vs docs-doc-id-* html classes)
- llms.txt: **200, 22,607 B, 152 lines, 32 docs links, 56 blog links; byte-identical to repo static/llms.txt** (curl + cmp with the raw.githubusercontent copy)

## Findings
- [high] *1. Sitemap inventory and counts*: The sitemap is a plain urlset (not an index file) with 275 URLs, all ending in a trailing slash, and 231 with lastmod. changefreq is always weekly and priority always 0.5.

By top-level section:
- docs: 124
- blog: 86 (85 posts + index)
- webinar: 15
- community: 14
- compare: 14
- customer-stories: 7
- learn: 4
- event: 3
- 8 single pages

By /docs/ sub-section: connectors 26, release 24, fusion 23, writers 15, community 7, core 6, getting-started 6, install 5, understanding 4. One page each for api, archive, benchmarks, dmsvsolake, features, monitoring-and-observability and tutorials, plus the /docs/ root. These match the lead's numbers.

robots.txt lists a second sitemap, image-sitemap.xml (207 pages, 1,733 images), which has no value for RAG. [evidence: https://olake.io/sitemap.xml; https://olake.io/robots.txt; https://olake.io/image-sitemap.xml; measured: scripts/parse_sitemap.py (xml.etree) on the fetched sitemap.xml]
- [high] *1. lastmod coverage per section*: lastmod is present for: docs 124/124, blog 85/86, compare 13/14, customer-stories 6/7 and learn 3/4. The section index pages lack it.

It is absent for: community 0/14, webinar 0/15, event 0/3 and the 8 landing/legal pages. These are React pages, not Markdown.

Docs lastmod dates:
- 2026-10-06: 100 pages
- 2026-10-15: 16
- 2026-10-09: 3
- 2026-10-08: 2
- 2026-10-07: 1
- 2026-10-12: 1
- 2025-06-23: 1 (/docs/connectors/overview/)

79 of 85 blog posts are dated 2026-10-06. [evidence: https://olake.io/sitemap.xml; measured: parse_sitemap.py lastmod Counter; https://docusaurus.io/docs/api/plugins/@docusaurus/plugin-sitemap (lastmod only emitted when plugins provide sourceFilePath/lastUpdatedAt)]
- [high] *1. What lastmod means*: Sitemap lastmod is the UTC date of the last git commit to the page's own .mdx file. This holds for 124 of 124 docs pages. The config uses sitemap lastmod:'date' with showLastUpdateTime, and CI checks out with fetch-depth:0.

The JSON-LD TechArticle.dateModified is the exact commit timestamp for 123 of 124 pages. The exception is /docs/, which hard-codes 2025-09-12 while its git date is 2026-10-09.

100 of 124 pages were last touched by commit bc3013d (2026-10-06 16:35Z), "Rebuild the site on a shared design system, with performance, accessibility and SEO fixes (#552)", which changed 926 files. For those pages lastmod is not a content signal.

Five-page cross-check against the GitHub commits API:
- /docs/connectors/overview/: 2025-06-23 = commit bca0f65b
- /docs/connectors/postgres/: 2026-10-15 = d3e4e2ce 18:39:37Z
- /docs/install/kubernetes/: 2026-10-08 = e278b333
- /docs/release/ingestion/v0.12.0/: 2026-10-12 = d5204611
- /docs/writers/iceberg/catalog/rest/: 2026-10-06 = bc3013d4 [evidence: https://raw.githubusercontent.com/datazip-inc/olake-docs/d06007140994ecbd239a52a9c0acf81fab4ed530/docusaurus.config.js; https://raw.githubusercontent.com/datazip-inc/olake-docs/d06007140994ecbd239a52a9c0acf81fab4ed530/.github/workflows/deploy.yml; gh api repos/datazip-inc/olake-docs/commits?path=<file>&per_page=3 (6 files); measured: scripts/lastmod_vs_git.py (git log -1 --format=%ct on a blobless history clone, converted to UTC, vs sitemap and JSON-LD)]
- [high] *1/7. Partial edits do not update lastmod*: lastmod is computed per source file, so edits to imported partials or JSX components don't change it.

Of the 22 pages that depend on partials, 1 currently has a dependency newer than its own lastmod. /docs/connectors/overview/ has lastmod 2025-06-23, yet it renders only <SupportedSources/>, and docs/shared/SupportedSources.mdx was last changed 2026-10-06. The other 21 pages were all reset by the 2026-10-06 sitewide commit, so this drift will build up again over time. [evidence: https://raw.githubusercontent.com/datazip-inc/olake-docs/d06007140994ecbd239a52a9c0acf81fab4ed530/docs/connectors/overview.mdx; https://raw.githubusercontent.com/datazip-inc/olake-docs/d06007140994ecbd239a52a9c0acf81fab4ed530/docs/shared/SupportedSources.mdx; measured: scripts/partial_drift.py (page vs newest dependency commit timestamps, UTC)]
- [high] *2. Generator, plugins, versioning*: The generator meta tag reads "Docusaurus v3.10.2". The site config has url https://olake.io, baseUrl /, trailingSlash:true, onBrokenLinks and onBrokenAnchors both 'warn', i18n locales ['en'] only, and customFields.latestOlakeVersion "0.12.0".

Plugin instances:
- One docs instance (id main-docs, path docs, routeBasePath docs). It excludes **/_*, shared/** and drafts/**.
- Fusion is a subfolder (docs/fusion) inside that instance, with its own sidebar fusionDocSidebar next to docSidebar. There is no /docs/fusion/ index page (404).
- Four blog-plugin instances: olake-blog, customer-stories-blog, learn-blog and compare-blog.

There is no versioning: no versions.json, versioned_docs or i18n folder in the tree, /docs/next/ and /docs/0.12.0/ return 404, and docusaurus_version is 'current'. [evidence: https://olake.io/docs/; https://olake.io/assets/js/main.89bf5ffc.js (embedded siteConfig; the bundle hash changes per deploy, so this URL will go stale); https://raw.githubusercontent.com/datazip-inc/olake-docs/d06007140994ecbd239a52a9c0acf81fab4ed530/sidebars.js; https://olake.io/docs/next/ (404); https://olake.io/docs/fusion/ (404); gh api repos/datazip-inc/olake-docs/git/trees/master?recursive=1 (no versions.json, versioned_docs or i18n)]
- [high] *2. Canonical form and redirect behaviour*: The canonical URL is https://olake.io/<path>/ with a trailing slash. The canonical tag equals the sitemap URL on 267 of 267 fetched pages, and none of them has a meta robots tag.

Redirect behaviour:
- A slashless path returns 301 to the slash form (GitHub Pages behaviour).
- http:// and www. both return 301 to https://olake.io.
- index.html returns 200, with canonical pointing at the slash URL.
- .html returns 404.

Paths are case-sensitive: /docs/Getting-Started/Quickstart/ and the lowercased /customer-stories/lendingkart-improved-data-correctness/ both return 404. The real sitemap URL contains uppercase letters, so never lowercase paths.

Legacy paths return HTTP 200 with a tiny HTML page using meta-refresh and a JS redirect, not a 3xx. Examples:
- /docs/connectors/postgres/config/ → /docs/connectors/postgres/#configuration
- /docs/writers/iceberg/s3-tables/ → /docs/writers/iceberg/catalog/rest/?rest-catalog=s3-tables

These come from the custom client-redirects-slash plugin: 285 entries covering 305 source paths, 212 of them docs-related. That table can serve as a ready-made legacy-to-canonical map.

404 pages return status 404 with a canonical of https://olake.io/404.html/. [evidence: https://olake.io/docs/getting-started/quickstart (301); https://www.olake.io/docs/getting-started/quickstart/ (301); https://olake.io/docs/getting-started/quickstart/index.html (200); https://olake.io/docs/Getting-Started/Quickstart/ (404); https://olake.io/customer-stories/lendingkart-improved-data-correctness/ (404); https://olake.io/docs/connectors/postgres/config/ (200 meta-refresh); https://olake.io/docs/writers/iceberg/s3-tables/ (200 meta-refresh); https://olake.io/docs/release/v0.6.0/ (200 meta-refresh); measured: parsed the redirects array in main.js (285 entries, 305 from-paths, 212 docs-related)]
- [high] *2/6. Heading anchors*: Heading ids follow github-slugger. Text is lowercased, punctuation is dropped, spaces become '-', and duplicates get '-1', '-2' (e.g. '2-provide-configuration-details-1' in the CLI tab). Numbered headings keep their number. h4 headings also get ids. Each heading has an a.hash-link containing a zero-width space (U+200B), which should be stripped.

Verification:
- Slugs recomputed from the MDX headings of 11 pages matched HTML ids 163/163.
- 296/296 internal docs links with a #fragment resolve.
- 14/14 redirect targets that carry a fragment resolve. [evidence: https://olake.io/docs/connectors/postgres/; measured: scripts/anchors.py on the 124 fetched docs pages plus MDX from the d0600714 clone]
- [high] *6. Anchors inside hidden tabs*: 191 of 1,274 heading anchors (15%), on 21 pages, sit inside non-default tab panels that are hidden by default.

The site's hashScroll.ts only scrolls; it does not switch tabs. TOCTabLinker.tsx rewrites TOC links to ?<param>=<value>#<id>. So a bare #anchor lands on hidden content, while for example https://olake.io/docs/connectors/postgres/?config-type=olake-cli#1-create-configuration-file opens the CLI tab (returns 200).

The tab values are not in the HTML, which only carries the labels. The page MDX does have them: 55/55 (page, label) pairs from page-level queryString Tabs matched the HTML labels, e.g. 'Use OLake CLI for Postgres' → config-type=olake-cli.

44 of 100 Tabs groups use queryString: tab 21, config-type 8, rest-auth-type 5, and others. [evidence: https://olake.io/docs/connectors/postgres/?config-type=olake-cli#1-create-configuration-file (200); https://olake.io/docs/benchmarks/ingestion/?tab=mysql (200); read from the sparse clone at d0600714: src/clientModules/hashScroll.ts, src/components/TOCTabLinker.tsx; measured: scripts/hidden_tab_headings.py and scripts/tab_values.py]
- [high] *3. Machine-readable variants*: **Available:**
- llms.txt returns 200 (22,607 B, 152 lines) and is byte-identical to the repo's static/llms.txt, so it is hand-maintained. It is a curated link index with one-line descriptions and no page bodies: 32 /docs/ links (6 are benchmarks ?tab=<db> variants), 56 blog links, 7 customer stories and 14 community links.
- /blog/rss.xml carries the 20 newest posts with full content:encoded HTML. Atom feeds exist for every blog instance.
- opensearch.xml has the template /search?q={searchTerms}.
- Raw MDX is fetchable from raw.githubusercontent.com.

**Not available (all 404):**
- llms-full.txt, /docs/llms.txt, /docs/llms-full.txt, /.well-known/llms.txt and /ai.txt
- .md, .mdx and /index.md variants
- search-index.json and search-index-docs-default-current.json

**Search** is Algolia DocSearch: appId 1E406NO1AX, index 'olake', contextualSearch, searchPagePath 'search', insights on. I did not use its search-only key. SOP.md says the DocSearch crawler re-indexes from the sitemap every 24 h. [evidence: https://olake.io/llms.txt; https://raw.githubusercontent.com/datazip-inc/olake-docs/d06007140994ecbd239a52a9c0acf81fab4ed530/static/llms.txt; https://olake.io/llms-full.txt (404); https://olake.io/docs/getting-started/quickstart.md (404); https://olake.io/search-index.json (404); https://olake.io/blog/rss.xml; https://olake.io/opensearch.xml; https://raw.githubusercontent.com/datazip-inc/olake-docs/master/docs/getting-started/quickstart.mdx (200); https://raw.githubusercontent.com/datazip-inc/olake-docs/d06007140994ecbd239a52a9c0acf81fab4ed530/SOP.md]
- [medium] *3. Prior art and AI crawlers*: No embedded AI assistant was found. I grepped for kapa, Inkeep, DocsBot, Mendable, Chatbase, Intercom, Crisp, Gurubase, RunLLM and Markprompt in the home page, /docs/, the Postgres page, main.js and the runtime chunk map, with no hits.

The only 'AskAi' strings are DocSearch v4 theme translations. The site's algolia config has no askAi or assistantId, so DocSearch Ask AI is not enabled. The baseline the judges will compare against is keyword search.

Third-party scripts on the page: Algolia, HubSpot forms, PostHog, gtag/GTM and Reo.dev. static/message-listener.js lets an iframe parent set a light or dark theme through postMessage.

robots.txt contains only 'User-agent: * / Allow: / / Disallow: /*.json$' plus the two sitemaps. There are no AI-crawler rules. [evidence: https://olake.io/; https://olake.io/docs/; https://olake.io/assets/js/main.89bf5ffc.js; https://olake.io/message-listener.js; https://olake.io/robots.txt]
- [high] *4. Source repo layout and frontmatter*: Repo datazip-inc/olake-docs: Apache-2.0, default branch master, 1,025 commits, first commit 2025-01-28. At d0600714 the tree has 2,118 blobs (82.8 MB; static/ alone is 76.3 MB of images).

docs/ contains 225 .mdx files (1,299,300 B):
- 125 routable pages (1,150,560 B)
- 99 partials in docs/shared/ (148,253 B)
- 1 draft (docs/drafts/faqs.mdx)
- plus 12 .jsx files in docs/shared/config/

Other content: blog/ 85 .mdx (2,153,840 B, filenames date-prefixed: 6 from 2024, 45 from 2025, 34 from 2026), compare/ 13 (560,562 B), customer-stories/ 6 (60,033 B), learn/ 3 (67,170 B). Config: docusaurus.config.js (58,395 B) and sidebars.js (9,678 B, docSidebar + fusionDocSidebar).

Frontmatter on docs pages: title 125, description 123, sidebar_label 73, sidebar_position 68, seo_title 44, slug 1 (intro.mdx → /docs/). No `id` field is used, so doc id = path.

Frontmatter on the blog: slug, title, description, image, authors and tags on all 85; seo_title 49; date 18.

The <title> tag uses seo_title. For example, the Postgres page's title is 'OLake Postgres Connector: Sync Modes and CDC' while its H1 is 'Overview'. [evidence: gh api repos/datazip-inc/olake-docs; gh api repos/datazip-inc/olake-docs/git/trees/master?recursive=1; measured: scripts/tree_stats.py, scripts/mdx_features.py (PyYAML) on the sparse clone at d0600714; https://raw.githubusercontent.com/datazip-inc/olake-docs/d06007140994ecbd239a52a9c0acf81fab4ed530/sidebars.js]
- [high] *4. MDX features*: Counts across the routable docs pages (excluding code fences):
- Tabs: <Tabs> 76 (plus 24 in partials), <TabItem> 192
- Content components: <Figure> 71, <FlagDetail> 24, <TOCTabLinker> 12, <Badge> 11, <DateTimeHandling> 7, <SourceSSLModeDetails> 5, <*IcebergWriter*ConfigDetails> JSX 32 uses, <YouTubeEmbed> 3, <BrowserOnly> 2 (TOC logic only)
- Admonitions: info 95, note 84, warning 39, tip 20, important 17, caution 12, danger 2
- Code fences: 759, of which 60 have title=
- Other: <details> 43, Markdown table rows 884, HTML tables 8, MDX comments 58 (often {/* #anchor */})
- No mermaid and no raw iframes in docs (the blog has 6 mermaid blocks)

Links inside MDX point to file paths, e.g. /docs/connectors/postgres/wal2json_plugin.mdx, so they need route mapping if read raw. [evidence: measured: scripts/mdx_features.py on the d0600714 clone; https://raw.githubusercontent.com/datazip-inc/olake-docs/d06007140994ecbd239a52a9c0acf81fab4ed530/docs/connectors/postgres/index.mdx]
- [high] *4. Content hidden from a raw-MDX reader*: Several kinds of content never appear in the page's own .mdx file:
- src/theme/MDXComponents/Index.js registers 92 docs/shared partials globally. Pages use tags like <PostgresSourceConfig/> and <PostgresToIcebergDatatypes/> with no import line.
- 12 JSX components build config tables from JS arrays, e.g. the Unity Catalog field table for each auth type.
- FlagDetail.tsx (21.7 KB) holds the CLI flag documentation.
- DateTimeHandling.tsx holds the date-clamping rules.

22 of 124 pages depend on 51 such files (about 33.7K source tokens). These are every connector main page, every catalog page, the Parquet writer pages, docker-cli and commands-and-flags.

Example: 'jsonb' appears 0 times in postgres/index.mdx, but it is in PostgresToIcebergDatatypes.mdx and in the rendered HTML (json/jsonb → string).

The rendered HTML is complete. All 202 tab panels are server-rendered, 122 with the hidden attribute. The Unity M2M, U2M and Token Federation fields all appear in the REST catalog HTML. [evidence: https://raw.githubusercontent.com/datazip-inc/olake-docs/d06007140994ecbd239a52a9c0acf81fab4ed530/src/theme/MDXComponents/Index.js; https://raw.githubusercontent.com/datazip-inc/olake-docs/d06007140994ecbd239a52a9c0acf81fab4ed530/docs/shared/config/PostgresToIcebergDatatypes.mdx; https://raw.githubusercontent.com/datazip-inc/olake-docs/d06007140994ecbd239a52a9c0acf81fab4ed530/docs/shared/config/UnityIcebergWriterUIConfigDetails.jsx; https://raw.githubusercontent.com/datazip-inc/olake-docs/d06007140994ecbd239a52a9c0acf81fab4ed530/src/components/cli/FlagDetail.tsx; https://olake.io/docs/writers/iceberg/catalog/rest/; measured: scripts/hidden_content.py, scripts/hidden_tokens.py, grep counts]
- [high] *5. Rendered docs corpus size*: I extracted the .theme-doc-markdown element from all 124 docs pages, dropping hash-links, buttons and svg.

Totals:
- HTML: 11,169,120 bytes
- Text: 998,144 chars, 145,615 words
- Tokens: 249,488 by chars/4, 238,135 by o200k
- 830 <pre> blocks (233K chars, 23% of the text), 182 tables, 80 tab containers with 202 panels, 342 admonitions, 232 images, 4 iframes

Tokens per page: min 4, median 1,004, p90 4,238, max 25,991.

By section (o200k): connectors 72.4K, writers 47.5K, fusion 28.2K, install 20.1K, community 14.4K, release 14.2K, understanding 11.1K, getting-started 10.8K, benchmarks 9.6K.

Top 10 pages by tokens:
- writers/iceberg/catalog/rest: 25,991
- fusion/getting-started/compaction: 11,777
- benchmarks/ingestion: 9,598
- install/kubernetes: 7,675
- community/setting-up-a-dev-env: 6,842
- connectors/s3: 5,738
- writers/iceberg/catalog/hive: 5,201
- understanding/terminologies/general: 4,922
- connectors/mongodb/setup/local: 4,843
- install/docker-cli: 4,734

Fetch wall time: 3.9 s at 4 concurrent without compression; 2.2 s and 2,067,045 B with gzip. [evidence: measured: scripts/fetch_pages.py (ThreadPoolExecutor, 4 workers) + scripts/measure_corpus.py (bs4/lxml, tiktoken o200k_base via uv); measured: xargs -P4 curl --compressed over the 124 docs URLs]
- [high] *5. Blog and other sections size*: All pages in these sections were fetched; nothing was sampled.

| Section | Pages | o200k tokens | Other |
|---|---|---|---|
| Blog posts | 85 | 428,473 | 10,783,366 B HTML, 1,927,068 chars, 297,316 words; median 3,750 tokens/post, max 22,579 (iceberg-compaction-tpch-benchmark) |
| compare | 14 | 103,707 | |
| learn | 4 | 13,022 | |
| community (React pages) | 14 | 11,428 | |
| customer-stories | 7 | 10,640 | |
| webinar | 15 | 8,192 | |
| event | 3 | 1,135 | |

Fetching these 143 pages took 12.4 s, mostly CDN misses.

By a rough H1 heuristic, 37 of 85 posts name OLake or Fusion in the H1 (about 197K tokens). The rest are general Iceberg/CDC education or 'X alternatives' lists. [evidence: measured: scripts/measure_corpus.py on fetch_other.json (143 pages, 200 OK); https://olake.io/blog/iceberg-compaction-tpch-benchmark/]
- [high] *5. Chunking proof of concept*: I tested a converter from Docusaurus HTML to Markdown. It keeps heading ids, renders tables in Markdown, keeps code fences with language and title, marks admonitions, wraps tab panels with their labels, uses details summaries and image alt text, and makes links absolute.

Chunks are split at h2/h3, chunks under 60 tokens are merged, and chunks over 700 tokens are split at paragraph breaks. Each chunk gets a context prefix: 'title | product > breadcrumbs > headings [tab]'.

Results for docs: 1,119 chunks, about 283.8K tokens with prefixes. Chunk tokens: median 173, p90 537, p99 1,146, max 5,051 (a single huge code block). 977 chunks carry an #anchor and 349 are inside a tab.

Results for the blog: 1,577 chunks, about 474K tokens.

The conversion works, and the output quality looks good (sample saved). [evidence: measured: scripts/chunk_poc.py; sample output: (probe script in a deleted scratch dir)]
- [high] *5. Stub, stale and thin pages*: These pages should be filtered out or demoted:
- **/docs/connectors/kafka/overview/** (45 tokens): says 'Coming Soon/Work in Progress', which contradicts the live /docs/connectors/kafka/.
- **/docs/connectors/overview/** (lastmod 2025-06-23): shows S3 as 'check issue' and Kafka as 'WIP'.
- **/docs/core/configs/state/ and /docs/core/configs/catalog/**: 'This page has been moved' stubs.
- **/docs/core/configs/source/ (155 tokens) and /docs/core/configs/writer/ (222 tokens)**: link hubs.
- **/docs/tutorials/enable-oplogs/**: Coming Soon.
- **Fusion core terminologies, query-engines, and all 4 fusion/community pages**: 'Coming soon', 5 to 9 tokens each.
- **/docs/fusion/core/architecture/ and /docs/core/architecture/**: image-only, 4 and 48 tokens.
- **/docs/archive/kubernetes/**: archived CronJob guide.
- **/docs/writers/iceberg/gcp/**: says details will be available soon.

29 sitemap pages are not in any sidebar. Most are legitimate setup guides reached through in-page links, so missing from the sidebar does not mean stale. [evidence: https://olake.io/docs/connectors/kafka/overview/; https://olake.io/docs/connectors/kafka/; https://olake.io/docs/connectors/overview/; https://olake.io/docs/core/configs/state/; https://olake.io/docs/tutorials/enable-oplogs/; https://olake.io/docs/fusion/core/terminologies/; https://olake.io/docs/fusion/core/architecture/; https://olake.io/docs/archive/kubernetes/; measured: scripts/stubs.py; sidebar ids vs page doc ids (orphans.txt)]
- [high] *5. Disambiguation hazards*: Several pages look alike or share names:
- Ten pages have the H1 'Overview'.
- Duplicate <title> tags: 'Offline Environments (AWS)' and 'Offline Environments (Generic)'.
- OLake Go and Fusion twin pages are near-identical by text similarity: offline-environments-generic 1.00, offline-environments-aws 0.95, quickstart 0.80, install/olake-ui 0.66, kubernetes 0.58. Every chunk therefore needs a product field.

Naming: 'OLake Go' appears in the article text of 59 of 124 docs pages and 104 of 107 posts. The rename came with commit 5978892, 'Restructure for OLake Go and Fusion (#430)', on 2026-06-14. Treat OLake, OLake Go and OLake ingestion as synonyms. [evidence: https://olake.io/docs/install/olake-ui/offline-environments-aws/; https://olake.io/docs/fusion/install/olake-ui/offline-environments-aws/; https://olake.io/llms.txt; measured: scripts/dup_check.py (difflib ratio); jq duplicate H1/title counts; git log -S'OLake Go' on the history clone]
- [high] *6. Mapping from repo file to URL*: The rule: strip docs/ and .mdx, map index.mdx to its folder, add a trailing slash, and prefix https://olake.io/docs/. A frontmatter slug overrides this; only intro.mdx has one, mapping to /docs/.

Verified for 124 of 124 pages: each returned HTTP 200, its canonical equals the URL, and its edit link https://github.com/datazip-inc/olake-docs/tree/master/<file> points back to the same file. That edit link is on every docs page.

Ten samples:
- intro.mdx → /docs/
- connectors/postgres/index.mdx → /docs/connectors/postgres/
- connectors/mysql/setup/rds.mdx → /docs/connectors/mysql/setup/rds/
- install/olake-ui/index.mdx → /docs/install/olake-ui/
- install/docker-cli.mdx → /docs/install/docker-cli/
- writers/iceberg/catalog/rest.mdx → /docs/writers/iceberg/catalog/rest/
- fusion/compaction/configuration.mdx → /docs/fusion/compaction/configuration/
- fusion/install/olake-ui/offline-environments-aws.mdx → /docs/fusion/install/olake-ui/offline-environments-aws/
- release/ingestion/v0.12.0.mdx → /docs/release/ingestion/v0.12.0/
- understanding/terminologies/olake.mdx → /docs/understanding/terminologies/olake/

docs/roadmap.mdx → /docs/roadmap/ is a routable page (200, a meta-refresh to GitHub) that the sitemap filter deliberately excludes. [evidence: https://olake.io/docs/connectors/mysql/setup/rds/; https://olake.io/docs/fusion/compaction/configuration/; https://olake.io/docs/roadmap/; measured: scripts/map_verify.py]
- [high] *7. HTTP freshness signals and deploy cadence*: Hosting is GitHub Pages behind Fastly: server GitHub.com, via 1.1 varnish, x-served-by cache-maa. Cache-Control is max-age=600. gzip works (130,332 → 23,867 B for the Postgres page).

Last-Modified is identical on all 267 pages: the deploy time, 2026-10-16 09:33:35Z. The ETag has the form "<hex deploy epoch>-<hex length>", e.g. 6ad1ef6f = 09:33:35Z. Both validators therefore change for every file on every deploy, whether or not the content changed.

Conditional GETs work: If-None-Match and If-Modified-Since return 304 for a docs page and for sitemap.xml.

Deploys: every push to master runs actions/deploy-pages. The last 6 runs, over about 26 h, took 1m14s to 2m40s each; commit d0600714 at 09:31:44Z was live at 09:33:35Z.

Docs churn: 522 commits touched docs/ since 2025-01-28, 25 of them in the last 30 days, and 7 to 47 per month. [evidence: https://olake.io/docs/connectors/postgres/ (headers, 304 test); https://olake.io/sitemap.xml (304 test); gh api repos/datazip-inc/olake-docs/actions/runs?branch=master&per_page=6; https://raw.githubusercontent.com/datazip-inc/olake-docs/d06007140994ecbd239a52a9c0acf81fab4ed530/.github/workflows/deploy.yml; measured: header Counter over fetch_docs.json/fetch_other.json; ETag hex decode; git log -- docs/ on the history clone]
- [high] *7. Docs lag GitHub releases (an outside-source need)*: The newest ingestion release-notes page is v0.12.0, and the site config says latestOlakeVersion 0.12.0. GitHub datazip-inc/olake already has v0.12.1 (2026-10-15).

The Kafka page already says Upsert mode needs OLake Go 0.12.1+ and OLake UI 0.7.1+; olake-ui v0.7.1 was released 2026-10-15.

Fusion is current. Its docs page /docs/fusion/release/maintenance/v0.1.0/ is titled 'OLake Fusion (v0.1.0 - v0.1.4)', which matches GitHub olake-fusion v0.1.4 (2026-08-24).

olake-helm is at v0.4.0, with chart olake-0.0.30 (2026-10-08). [evidence: gh api repos/datazip-inc/olake/releases?per_page=5; gh api repos/datazip-inc/olake-ui/releases?per_page=3; gh api repos/datazip-inc/olake-fusion/releases?per_page=3; gh api repos/datazip-inc/olake-helm/releases?per_page=3; https://olake.io/docs/release/ingestion/v0.12.0/; https://olake.io/docs/connectors/kafka/; https://olake.io/docs/fusion/release/maintenance/v0.1.0/]
- [high] *1. Full /docs/ inventory (URL | <title> minus ' | OLake' | lastmod | o200k tokens | orphan flag)*: Every /docs/ URL with its served title, grouped by section in the evidence below. All 124 returned HTTP 200 on 2026-10-16. The TSV holds the same rows plus source file, JSON-LD date and sidebar flag. [evidence: ROOT/API/ARCHIVE/BENCH: /docs/ | OLake Data Replication: Fastest Open Source Iceberg Lakehouse Tool | 2026-10-09 | 1336; /docs/api/olake-ui-api/ | OLake UI API - API Documentation | 2026-10-06 | 343; /docs/archive/kubernetes/ | Kubernetes Installation - Archive | 2026-10-06 | 1267 | orphan; /docs/benchmarks/ingestion/ | OLake Ingestion Benchmarks: Speed, Cost, Performance | 2026-10-06 | 9598; /docs/dmsvsolake/ | OLake vs AWS DMS: Migration Speed and Cost | 2026-10-06 | 1912; /docs/features/schema/ | Schema Evolution & Data Type Changes | 2026-10-06 | 2153; /docs/monitoring-and-observability/metrics/ | Prometheus Integration - Docs | 2026-10-06 | 1224; /docs/tutorials/enable-oplogs/ | Enable oplogs - Tutorials | 2026-10-06 | 11 | orphan; COMMUNITY: /docs/community/channels/ | OLake Community Channels: Slack and YouTube | 20; /docs/community/code-of-conduct/ | OLake Community Code of Conduct | 1278; /docs/community/commands-and-flags/ | OLake CLI Commands and Flags Reference | 2026-10-15 | 3124; /docs/community/contributing/ | Contributing to OLake Go: Contributor Guide | 1074; /docs/community/issues-and-prs/ | Raise an Issue or Pull Request for OLake | 1107; /docs/community/learning-modules/ | Learning Modules - Development environment | 946; /docs/community/setting-up-a-dev-env/ | Set Up an OLake Development Environment | 6842 (lastmod 2026-10-06 unless noted); CONNECTORS-1: /docs/connectors/db2/ | OLake DB2 Connector | Data Sync & Troubleshooting | 2026-10-15 | 1881; /docs/connectors/kafka/ | OLake Kafka Connector | Data Sync & Troubleshooting | 2026-10-15 | 3700; /docs/connectors/kafka/overview/ | Kafka - Sources | 45 | orphan; /docs/connectors/mongodb/ | OLake MongoDB Connector: Sync Modes and Setup | 2026-10-15 | 3291; /docs/connectors/mongodb/cdc_setup/ | MongoDB and Atlas CDC Setup for OLake | 484 | orphan; /docs/connectors/mongodb/setup/local/ | Local MongoDB Replica Set with Docker Compose | 4843 | orphan; /docs/connectors/mssql/ | MSSQL Source Connector Guide | OLake Data Sync & CDC | 2026-10-15 | 4107; /docs/connectors/mysql/ | OLake MySQL Connector: Setup and Sync Modes | 2026-10-15 | 3962; /docs/connectors/mysql/setup/aurora/ | Aurora MySQL CDC Setup for OLake | 2026-10-15 | 2874 | orphan; /docs/connectors/mysql/setup/azure/ | Azure Database for MySQL CDC Setup for OLake | 2889 | orphan; /docs/connectors/mysql/setup/gcp/ | Cloud SQL for MySQL CDC Setup for OLake | 2755 | orphan; /docs/connectors/mysql/setup/generic/ | Generic MySQL Server CDC Setup for OLake | 3286 | orphan; /docs/connectors/mysql/setup/local/ | Local MySQL with Docker Compose for OLake CDC | 2026-10-15 | 3656 | orphan; /docs/connectors/mysql/setup/rds/ | RDS MySQL CDC Setup for OLake | 2026-10-15 | 3572 | orphan; CONNECTORS-2: /docs/connectors/oracle/ | OLake Oracle Connector: Setup and Sync Modes | 2026-10-15 | 2086; /docs/connectors/oracle/setup/generic/ | Generic Oracle Setup - Sources | 486 | orphan; /docs/connectors/overview/ | Overview - Sources | 2025-06-23 | 86 | orphan; /docs/connectors/postgres/ | OLake Postgres Connector: Sync Modes and CDC | 2026-10-15 | 4115; /docs/connectors/postgres/setup/aurora/ | AWS Aurora PostgreSQL CDC Setup for OLake | 2630 | orphan; /docs/connectors/postgres/setup/azure/ | Azure PostgreSQL CDC Setup for OLake | 2362 | orphan; /docs/connectors/postgres/setup/gcp/ | Google Cloud SQL PostgreSQL CDC Setup for OLake | 2237 | orphan; /docs/connectors/postgres/setup/generic/ | Generic PostgreSQL CDC Setup with pgoutput | 3738 | orphan; /docs/connectors/postgres/setup/local/ | Local PostgreSQL CDC Setup with Docker for OLake | 2026-10-15 | 2774 | orphan; /docs/connectors/postgres/setup/rds/ | AWS RDS PostgreSQL CDC Setup for OLake | 2750 | orphan; /docs/connectors/postgres/wal2json_plugin/ | PostgreSQL CDC Setup with the wal2json Plugin | 2073 | orphan; /docs/connectors/s3/ | OLake S3 Source Connector | Multi-Format Data Sync | 2026-10-15 | 5738; CORE: /docs/core/architecture/ | OLake Go Architecture Overview | 48; /docs/core/configs/catalog/ | Streams config - Core Concepts | 94 | orphan; /docs/core/configs/source/ | Source config - Core Concepts | 155 | orphan; /docs/core/configs/state/ | State config - Core Concepts | 81 | orphan; /docs/core/configs/writer/ | Destination config - Core Concepts | 222 | orphan; /docs/core/use-cases/ | OLake Data Replication Use Cases and Benefits | 1036; FUSION-1: /docs/fusion/community/channels/ | Channels - Fusion Community | 5; /docs/fusion/community/code-of-conduct/ | Code of Conduct - Fusion Community | 7; /docs/fusion/community/contributing/ | Contributing - Fusion Community | 6; /docs/fusion/community/issues-and-prs/ | How to Raise a PR - Fusion Community | 9; /docs/fusion/compaction/configuration/ | Configuration - Fusion Compaction | 428; /docs/fusion/compaction/types-of-compaction/ | Types of Compaction - Fusion Maintenance | 673; /docs/fusion/core/architecture/ | Architecture - Fusion Core Concepts | 4; /docs/fusion/core/compatibility/query-engines/ | Query Engine Compatibility | 7; /docs/fusion/core/terminologies/ | Terminologies - Fusion Core Concepts | 6; /docs/fusion/core/use-cases/ | Use Cases - Fusion Core Concepts | 483; /docs/fusion/getting-started/compaction/ | Compaction Benchmarks - Fusion | 11777; /docs/fusion/getting-started/configure-first-compaction/ | Configure Your First Compaction | 1543; FUSION-2: /docs/fusion/getting-started/overview/ | Overview - Fusion | 369; /docs/fusion/getting-started/quickstart/ | Quickstart - Fusion | 394; /docs/fusion/install/kubernetes-compaction/ | Deploy OLake Maintenance on Kubernetes | 4392; /docs/fusion/install/olake-ui/ | OLake Fusion UI Install with Docker Compose | 2343; /docs/fusion/install/olake-ui/offline-environments-aws/ | Offline Environments (AWS) | 1977; /docs/fusion/install/olake-ui/offline-environments-generic/ | Offline Environments (Generic) | 1526; /docs/fusion/maintenance/catalogs/ | Iceberg Maintenance Catalogs | 642; /docs/fusion/maintenance/metrics/ | Iceberg Maintenance Metrics | 617; /docs/fusion/maintenance/runs-and-logs/ | Runs and Logs - Fusion Maintenance | 494; /docs/fusion/release/maintenance/overview/ | OLake Fusion Release Notes Overview | 201; /docs/fusion/release/maintenance/v0.1.0/ | OLake Fusion (v0.1.0 - v0.1.4) | 315 (all fusion lastmod 2026-10-06); GETTING-STARTED/INSTALL: /docs/getting-started/alerts-and-notifications/ | Alerts and Notifications - Move and Manage Data | 464; /docs/getting-started/creating-first-pipeline/ | Create Your First OLake Data Pipeline | 2026-10-15 | 1993; /docs/getting-started/job-level-properties/ | Job Level Features - Move and Manage Data | 3198; /docs/getting-started/olake-ui/ | OLake UI Quickstart with Docker Compose | 421 | orphan; /docs/getting-started/playground/ | Playground - Get Started | 2026-10-15 | 4238; /docs/getting-started/quickstart/ | Quickstart - OLake - Get Started | 453; /docs/install/docker-cli/ | OLake Docker CLI Setup: Source, Destination, Sync | 2026-10-09 | 4734; /docs/install/kubernetes/ | Deploy OLake UI on Kubernetes with Helm | 2026-10-08 | 7675; /docs/install/olake-ui/ | OLake UI Install with Docker Compose | 2026-10-08 | 4086; /docs/install/olake-ui/offline-environments-aws/ | Offline Environments (AWS) | 2044; /docs/install/olake-ui/offline-environments-generic/ | Offline Environments (Generic) | 1529; RELEASE (titles 'OLake Go (vX - vY)'): /docs/release/ingestion/28-04-2025/ (413, orphan); /overview/ OLake Ingestion Release Notes Overview (230); v0.1.0-v0.1.1 (549); v0.1.2-v0.1.5 (243); v0.1.6-v0.1.8 (502); v0.1.9-v0.1.11 (414); v0.10.0 'v0.10.0 - v0.10.1' (353); v0.11.0 'v0.11.0 - v0.11.3' 2026-10-07 (494); v0.12.0 'OLake Go (v0.12.0) - Versions' 2026-10-12 (84); v0.2.0-v0.2.1 (471); v0.2.10 'v0.2.10 - v0.3.4' (379); v0.2.2-v0.2.4 (228); v0.2.5-v0.2.7 (652); v0.2.8 'v0.2.8 - v0.2.9' (785); v0.3.14 'v0.3.14 - v0.3.16' (917); v0.3.17 'v0.3.17 - v0.3.18' (477); v0.3.5 'v0.3.5 - v0.3.8' (625); v0.3.9-v0.3.11 'v0.3.9 - v0.3.13' (511); v0.4.0 'v0.4.0 - v0.4.2' (213); v0.5.0 'v0.5.0 - v0.5.2' (466); v0.6.0 'v0.6.0 - v0.6.5' (965); v0.7.0 'v0.7.0 - v0.7.8' (1757); v0.8.0 'v0.8.0 - v0.8.2' (552); v0.9.0 'v0.9.0 - v0.9.5' (1932); UNDERSTANDING/WRITERS: /docs/understanding/compatibility-catalogs/ | Iceberg Catalog Compatibility for OLake | 129; /docs/understanding/compatibility-engines/ | Query Engine Compatibility with OLake Iceberg Tables | 1320; /docs/understanding/terminologies/general/ | Data Engineering Glossary of Key Terms | 2026-10-15 | 4922; /docs/understanding/terminologies/olake/ | OLake Terminologies - Move and Manage Data | 2026-10-09 | 4729; /docs/writers/iceberg/azure/ | Iceberg Lakehouse on Azure Setup Guide | 1575; /docs/writers/iceberg/catalog/glue/ | AWS Glue Iceberg Catalog Setup for OLake Go | 2533; /docs/writers/iceberg/catalog/hive/ | OLake Iceberg Hive Catalog Setup and Configuration | 5201; /docs/writers/iceberg/catalog/jdbc/ | OLake Iceberg JDBC Catalog Setup and Configuration | 2701; /docs/writers/iceberg/catalog/rest/ | OLake Iceberg REST Catalog Setup and Configuration | 25991; /docs/writers/iceberg/gcp/ | Iceberg Lakehouse on Google Cloud with OLake | 107; /docs/writers/iceberg/partitioning/ | OLake Iceberg Partitioning for Faster Queries | 2836; /docs/writers/iceberg/polaris-iam-setup/ | How to Attach IAM Role to EC2 Instance | 1004 | orphan; /docs/writers/iceberg/troubleshooting-local/ | OLake Iceberg Troubleshooting & Local Testing Guide | 664; /docs/writers/parquet/config/ | OLake Parquet S3 Writer Setup & Configuration Guide | 1100; /docs/writers/parquet/gcs/ | Google Cloud Storage - Destinations | 278 | orphan; /docs/writers/parquet/local/ | Local System - Destinations | 268 | orphan; /docs/writers/parquet/partitioning/ | Parquet Data Partitioning for S3 in OLake | 2250; /docs/writers/parquet/permission/ | IAM Permissions - Parquet Writer | 678; /docs/writers/parquet/troubleshoot/ | Troubleshooting - Parquet Writer | 293 (lastmod 2026-10-06 unless noted); full TSV: (probe script in a deleted scratch dir)]

## Open questions
- Should `sources` carry #anchors and ?tab params (precise and verified) or only page-level canonical URLs? This depends on whether the hidden-set grader does exact string matching.
- The canonical form has a trailing slash. If graders expect slashless URLs, should we emit those, or rely on the grader normalizing?
- Does adding the blog (about 428K tokens, 1.8× the docs, some posts from 2024/2025) raise or lower accuracy? This needs an A/B run on the eval set; my default is tier 2 with lower weight.
- Should stub and 'coming soon' pages be hard-excluded, or kept with a flag so the bot can honestly say 'the docs mark this as coming soon'?
- Does GitHub Pages purge the Fastly cache on deploy, or can max-age=600 serve old HTML for up to 10 min? I did not test this; a post-deploy probe of x-cache and age would answer it.
- For 'latest version' questions, which is the source of truth: GitHub releases (OLake Go v0.12.1) or the docs (v0.12.0)?
- For 'last updated' in the UI, which date should be used? JSON-LD dateModified is hard-coded wrong on /docs/ (2025-09-12); git and lastmod are correct.
- The tab value map covered only page-level Tabs (55 pairs). The 24 Tabs groups inside shared partials need a second pass before tab deep links are complete.
- Report file: the harness blocked writing report.md for subagents (Write tool refused), so the full report is in this structured output. Small artifacts were kept in the scratch dir (TSV, chunk sample, scripts, metrics JSON). Clones and HTML were deleted.

## Report path note
NOT WRITTEN: the harness refused subagent report .md files, so the full report is in this structured output. Per-page table: (probe script in a deleted scratch dir); scripts: (probe script in a deleted scratch dir); metrics JSON: (probe script in a deleted scratch dir)
