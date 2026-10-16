#!/usr/bin/env bash
# verify_docs.sh: the verifier's gate for the Ask OLake research docs.
#
# Usage (run from anywhere inside the repo):
#   bash poc/verify_docs.sh              all checks; (c) needs the network
#   bash poc/verify_docs.sh --offline    skip the URL and sitemap checks in (c)
#   bash poc/verify_docs.sh --final      PENDING/TODO markers in the four docs FAIL instead of WARN
#   bash poc/verify_docs.sh --jobs 4     URL-check parallelism (default 6; github.com URLs use half)
#   bash poc/verify_docs.sh -v           also print one PASS line per URL and per number
#   VERIFY_BASE=<ref>                    base of the branch commits (default origin/main)
#
# Checks:
#   (a) the four docs exist and are non-empty; PENDING/TODO markers are listed
#   (b) the docs/eval-questions.md question table: row count, 6 cells per row (\| honoured), unique IDs,
#       Type values, sources per Type, '—' rows, <br> separators, BEHAVIOR items, the counts the docs
#       state, and agreement with docs/reports/eval-curated.json
#   (c) every http(s) URL in docs/*.md and README.md resolves (browser User-Agent, retries, status < 400);
#       relative links, #anchors and reference-style labels resolve; every olake.io/docs eval source is
#       in the live sitemap
#   (d) hygiene: personal paths and secret patterns in tracked files (working tree and branch history),
#       AI attribution lines in the branch commit messages, and the author of every branch commit
#   (e) key POC numbers quoted in docs/research.md (and a few in docs/plan.md) match poc/results/*.json
#
# Output: PASS / WARN / FAIL / INFO lines, then a summary. Exit status 1 if any check FAILs.
# Needs bash, git, curl, jq, awk, grep, sed, sort, tr, xargs. No credentials.

set -u
set -o pipefail

OFFLINE=0
FINAL=0
VERBOSE=0
JOBS=6
while [ $# -gt 0 ]; do
  case "$1" in
    --offline) OFFLINE=1 ;;
    --final) FINAL=1 ;;
    -v|--verbose) VERBOSE=1 ;;
    --jobs) JOBS="${2:-6}"; shift ;;
    -h|--help) sed -n '2,27p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
  shift
done

ROOT="$(cd "$(dirname "$0")/.." && pwd -P)" || exit 2
cd "$ROOT" || exit 2

NPASS=0; NWARN=0; NFAIL=0
pass() { NPASS=$((NPASS + 1)); printf 'PASS  %s\n' "$*"; }
warn() { NWARN=$((NWARN + 1)); printf 'WARN  %s\n' "$*"; }
fail() { NFAIL=$((NFAIL + 1)); printf 'FAIL  %s\n' "$*"; }
info() { printf 'INFO  %s\n' "$*"; }
detail() { sed 's/^/        /'; }
section() { printf '\n== %s\n' "$*"; }
TAB="$(printf '\t')"

for tool in git curl jq awk grep sed sort tr xargs; do
  command -v "$tool" >/dev/null 2>&1 || { echo "FAIL  missing tool: $tool"; exit 1; }
done

TMP="$(mktemp -d 2>/dev/null || mktemp -d -t verify_docs)" || exit 2
trap 'rm -rf "$TMP"' EXIT

UA='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36'
DOCS="docs/research.md docs/plan.md docs/eval-questions.md docs/open-questions.md"
EVAL=docs/eval-questions.md
RESEARCH=docs/research.md
PLAN=docs/plan.md
RES=poc/results
BASE="${VERIFY_BASE:-origin/main}"
TYPES="answerable negative out-of-scope unanswerable false-premise adversarial"
DASH="—"

printf 'verify_docs.sh at %s, HEAD %s, base %s\n' "$(date -u +%Y-%m-%dT%H:%MZ)" \
  "$(git rev-parse --short HEAD 2>/dev/null)" "$BASE"
if [ -n "$(git status --porcelain 2>/dev/null)" ]; then
  info "the working tree is not clean; the tracked-file checks read the working tree:"
  git status --porcelain | detail
fi

# Snapshot the docs and results first: the checks below read the snapshot, so edits made while the
# URL checks run cannot mix two versions of a file. Git checks run in the repo.
SNAP="$TMP/snap"
mkdir -p "$SNAP/poc" && cp -R docs "$SNAP/" && cp README.md "$SNAP/" && cp -R "$RES" "$SNAP/poc/" || {
  echo "FAIL  could not snapshot docs/, README.md and $RES"; exit 1; }
cd "$SNAP" || exit 2

# Whitespace-normalised copy of a doc, so that a quoted phrase matches across line wraps.
norm() { tr -s '[:space:]' ' ' <"$1"; }
for f in $DOCS README.md; do [ -f "$f" ] && norm "$f" >"$TMP/norm.$(basename "$f")"; done

# ---------------------------------------------------------------------------------------------------------
section "(a) the four docs"
for f in $DOCS; do
  if [ -s "$f" ]; then pass "a: $f exists ($(wc -l <"$f" | tr -d ' ') lines)"; else fail "a: $f is missing or empty"; fi
done

: >"$TMP/markers"
for f in $DOCS; do
  [ -f "$f" ] || continue
  # The legend tokens `PENDING(x)` and `TODO(cite)` only explain the markers; every other marker counts.
  sed -e 's/`PENDING(x)`//g' -e 's/`TODO(cite)`//g' "$f" \
    | grep -nE 'PENDING[(:]|[|] *PENDING *[|]|TODO\(|(^|[^A-Za-z])(TBD|FIXME)([^A-Za-z]|$)' \
    | sed "s|^|$f:|" | cut -c1-170 >>"$TMP/markers"
done
nmark=$(wc -l <"$TMP/markers" | tr -d ' ')
if [ "$nmark" -eq 0 ]; then
  pass "a: no PENDING/TODO/TBD/FIXME markers in the four docs"
elif [ "$FINAL" -eq 1 ]; then
  fail "a: $nmark lines with PENDING/TODO markers remain in the four docs:"; detail <"$TMP/markers"
else
  warn "a: $nmark lines with PENDING/TODO markers remain in the four docs (FAIL under --final):"; detail <"$TMP/markers"
fi

# ---------------------------------------------------------------------------------------------------------
section "(b) eval question table ($EVAL)"
HEADER='| ID | Category | Type | Question | Expected sources | Must mention |'
nhdr=$(grep -cFx -- "$HEADER" "$EVAL")
if [ "$nhdr" -eq 1 ]; then pass "b: exactly one question-table header"; else fail "b: $nhdr exact question-table headers (expected 1)"; fi

# One TSV line per question-table row: file line, cell count, cells (\| restored to |). '#' lines are problems.
cat >"$TMP/table.awk" <<'AWK'
BEGIN { state = 0; OFS = "\t" }
{
  sub(/\r$/, "")
  if (state == 0) {
    if ($0 == "| ID | Category | Type | Question | Expected sources | Must mention |") state = 1
    next
  }
  if (state == 1) {
    if ($0 !~ /^\|( *:?-+:? *\|)+ *$/) print "#NOSEP", NR, "no separator row under the header"
    state = 2; next
  }
  if (state == 2 && $0 !~ /^\|/) { state = 3; next }
  line = $0
  gsub(/\\\|/, "\001", line)
  sub(/[ \t]+$/, "", line)
  if (state == 3) {
    if (line ~ /^\|/) { n = split(line, c, "|"); if (n - 2 >= 6) print "#LATER", NR, "a table with 6+ columns follows the question table (the loader reads it)" }
    next
  }
  if (index(line, "\t") > 0) print "#TAB", NR, "a tab character inside a row"
  if (line !~ /\|$/) { print "#NOEND", NR, "the row does not end with |"; line = line "|" }
  line = substr(line, 2, length(line) - 2)
  n = split(line, c, "|")
  out = NR OFS n
  for (i = 1; i <= n; i++) {
    x = c[i]; gsub(/\001/, "|", x); sub(/^[ \t]+/, "", x); sub(/[ \t]+$/, "", x)
    out = out OFS x
  }
  print out
}
AWK
awk -f "$TMP/table.awk" "$EVAL" >"$TMP/table.raw"
grep -v '^#' "$TMP/table.raw" >"$TMP/rows.tsv"
while IFS="$TAB" read -r _ l msg; do fail "b: $EVAL:$l: $msg"; done < <(grep '^#' "$TMP/table.raw")
nrows=$(wc -l <"$TMP/rows.tsv" | tr -d ' ')
if [ "$nrows" -ge 60 ]; then pass "b: $nrows data rows (>= 60)"; else fail "b: $nrows data rows (need >= 60)"; fi

cat >"$TMP/rows.awk" <<'AWK'
BEGIN {
  FS = "\t"
  nt = split(TYPES, t, " "); for (i = 1; i <= nt; i++) ok[t[i]] = 1
}
{
  ln = $1; n = $2; id = $3; cat = $4; typ = $5; q = $6; src = $7; mm = $8
  where = "line " ln " " id
  if (n != 6) { print "FAIL\tcells\tline " ln ": " n " cells (expected 6; write a literal | as \\|)"; next }
  print "OK\tcells"
  if (id !~ /^[A-Z]+-[0-9][0-9]$/) print "FAIL\tid\t" where ": the ID is not PREFIX-NN"
  if (id in seen) print "FAIL\tid\t" where ": duplicate ID (first at line " seen[id] ")"
  else seen[id] = ln
  if (!(typ in ok)) { print "FAIL\ttype\t" where ": Type '" typ "' is not one of " TYPES; next }
  print "COUNT\ttype\t" typ; print "COUNT\tcat\t" cat
  if (q == "") print "FAIL\tquestion\t" where ": empty Question"
  if (cat == "") print "FAIL\tcategory\t" where ": empty Category"
  # Expected sources: the dash, or <br>-separated items that are each exactly one http(s) URL.
  nsrc = 0; gh = 0
  if (src != DASH) {
    ns = split(src, s, "<br>")
    for (i = 1; i <= ns; i++) {
      x = s[i]; sub(/^ +/, "", x); sub(/ +$/, "", x)
      if (x ~ /^https?:\/\/[^ \t<>|;,`]+$/) {
        nsrc++
        if (x ~ /^https:\/\/github\.com\//) gh = 1
        if (x ~ /^https:\/\/github\.com\/[^\/]+\/[^\/]+\/blob\/[0-9a-f]+\// && x !~ /\/blob\/(master|main)\//)
          print "FAIL\tsrcfmt\t" where ": the GitHub source is not in the /blob/<branch>/ form: " x
        print "SRC\t" id "\t" x
      } else print "FAIL\tsep\t" where ": Expected sources item " i " is not exactly one URL (separate items with <br>): '" x "'"
    }
  }
  if (gh) print "COUNT\tgh\trows"
  if (typ == "answerable" || typ == "negative" || typ == "false-premise") {
    if (nsrc < 1) print "FAIL\tsrc\t" where ": a " typ " row needs at least one http(s) source"
    else print "OK\tsrc"
  }
  if (typ == "out-of-scope" || typ == "unanswerable") {
    if (src != DASH) print "FAIL\tdash\t" where ": a " typ " row must have " DASH " as Expected sources"
    else print "OK\tdash"
  }
  # <br> is the only separator form, and there are no empty items.
  t2 = src mm; gsub(/<br>/, "", t2)
  if (t2 ~ /<[bB][rR]/) print "FAIL\tsep\t" where ": a <br/>, <br /> or <BR> variant; use <br>"
  if (mm == "") print "FAIL\tmust\t" where ": empty Must mention"
  nm = split(mm, m, "<br>"); empty = 0
  for (i = 1; i <= nm; i++) { x = m[i]; gsub(/ /, "", x); if (x == "") empty = 1 }
  if (empty) print "FAIL\tsep\t" where ": an empty Must mention item (a stray <br>)"
  last = m[nm]; sub(/^ +/, "", last)
  if (typ == "out-of-scope" || typ == "unanswerable" || typ == "false-premise" || typ == "adversarial") {
    if (last !~ /^BEHAVIOR:/) print "FAIL\tbehavior\t" where ": a " typ " row must end with a BEHAVIOR: item"
    else print "OK\tbehavior"
  }
}
AWK
awk -v TYPES="$TYPES" -v DASH="$DASH" -f "$TMP/rows.awk" "$TMP/rows.tsv" >"$TMP/rowcheck"
for rule in cells id type question category sep srcfmt src dash must behavior; do
  nf=$(awk -F'\t' -v r="$rule" '$1 == "FAIL" && $2 == r' "$TMP/rowcheck" | wc -l | tr -d ' ')
  nok=$(awk -F'\t' -v r="$rule" '$1 == "OK" && $2 == r' "$TMP/rowcheck" | wc -l | tr -d ' ')
  if [ "$nf" -gt 0 ]; then
    while IFS= read -r m; do fail "b: $m"; done < <(awk -F'\t' -v r="$rule" '$1 == "FAIL" && $2 == r { print $3 }' "$TMP/rowcheck")
  else
    case "$rule" in
      cells) pass "b: every row has exactly 6 cells ($nok rows)" ;;
      id) pass "b: IDs are unique and PREFIX-NN" ;;
      type) pass "b: every Type is one of: $TYPES" ;;
      sep) pass "b: Expected sources and Must mention items are separated by <br> only; each source item is one URL" ;;
      srcfmt) pass "b: GitHub file sources use the /blob/<branch>/ form" ;;
      src) pass "b: every answerable / negative / false-premise row has >= 1 http(s) source ($nok rows)" ;;
      dash) pass "b: every out-of-scope / unanswerable row uses $DASH ($nok rows)" ;;
      behavior) pass "b: every out-of-scope / unanswerable / false-premise / adversarial row ends with BEHAVIOR: ($nok rows)" ;;
    esac
  fi
done

# The counts the docs state must match the table.
cnt() { awk -F'\t' -v k="$1" -v v="$2" '$1 == "COUNT" && $2 == k && $3 == v' "$TMP/rowcheck" | wc -l | tr -d ' '; }
stated=$(sed -n 's/.*The set has \([0-9][0-9]*\) rows.*/\1/p' "$EVAL" | head -1)
if [ "$stated" = "$nrows" ]; then pass "b: $EVAL states $stated rows, matching the table"
else fail "b: $EVAL states '${stated:-no}' rows; the table has $nrows"; fi
# A two-column "| <key> | <n> |" summary table under the given header line.
summary_table() { awk -v h="$1" '
  $0 == h { on = 1; getline; next }
  on && /^\|/ { line = $0; gsub(/^\| *| *\|$/, "", line); split(line, c, / *\| */); print c[1] "\t" c[2]; next }
  on { exit }' "$EVAL"; }
for kind in type cat; do
  if [ "$kind" = type ]; then hdr='| Type | Rows |'; else hdr='| Category | Rows |'; fi
  summary_table "$hdr" >"$TMP/sum_$kind"
  if [ ! -s "$TMP/sum_$kind" ]; then fail "b: no '$hdr' summary table in $EVAL"; continue; fi
  awk -F'\t' -v k="$kind" '$1 == "COUNT" && $2 == k { print $3 }' "$TMP/rowcheck" | sort | uniq -c \
    | awk '{ print $2 "\t" $1 }' >"$TMP/act_$kind"
  bad=0
  while IFS="$TAB" read -r key n; do
    a=$(awk -F'\t' -v k="$key" '$1 == k { print $2 }' "$TMP/act_$kind"); a=${a:-0}
    [ "$a" = "$n" ] || { fail "b: the '$hdr' table says $key = $n; the question table has $a"; bad=1; }
  done <"$TMP/sum_$kind"
  while IFS="$TAB" read -r key n; do
    awk -F'\t' -v k="$key" '$1 == k { f = 1 } END { exit !f }' "$TMP/sum_$kind" \
      || { fail "b: the question table has $n rows of $key, missing from the '$hdr' table"; bad=1; }
  done <"$TMP/act_$kind"
  [ "$bad" -eq 0 ] && pass "b: the '$hdr' table matches the rows ($(tr '\t\n' '= ' <"$TMP/act_$kind"))"
done
# research.md section 6 repeats the per-type counts.
bytype=$(grep -m1 'by type:' "$RESEARCH" || true)
if [ -z "$bytype" ]; then
  warn "b: no 'by type:' line in $RESEARCH to compare"
else
  bad=0
  for t in $TYPES; do
    n=$(cnt type "$t")
    printf '%s' "$bytype" | grep -qE "(^|[^0-9])$n $t" || { fail "b: the 'by type:' line in $RESEARCH does not say '$n $t'"; bad=1; }
  done
  [ "$bad" -eq 0 ] && pass "b: the 'by type:' counts in $RESEARCH match the table"
fi
ngh=$(cnt gh rows)
for f in "$EVAL" "$RESEARCH"; do
  if grep -qF "$ngh rows cite repo files or GitHub" "$TMP/norm.$(basename "$f")"; then pass "b: $f says $ngh rows cite GitHub, matching the table"
  else fail "b: $f does not say '$ngh rows cite repo files or GitHub ...' (the table has $ngh rows with a github.com source)"; fi
done

# docs/reports/eval-curated.json is cited as the full record of the same rows.
CUR=docs/reports/eval-curated.json
if [ -f "$CUR" ]; then
  cut -f3,5 "$TMP/rows.tsv" | sort >"$TMP/ids_table"
  jq -r '.[] | "\(.id)\t\(.type)"' "$CUR" | sort >"$TMP/ids_cur"
  if cmp -s "$TMP/ids_table" "$TMP/ids_cur"; then pass "b: $CUR has the same $nrows IDs and Types as the table"
  else fail "b: the IDs or Types in $CUR differ from the table (< table, > json):"; diff "$TMP/ids_table" "$TMP/ids_cur" | grep '^[<>]' | head -20 | detail; fi
  awk -F'\t' '$1 == "SRC" { print $2 "\t" $3 }' "$TMP/rowcheck" | sort >"$TMP/src_table"
  jq -r '.[] | .id as $i | (.expected_sources // [])[] | "\($i)\t\(.)"' "$CUR" | sort >"$TMP/src_cur"
  if cmp -s "$TMP/src_table" "$TMP/src_cur"; then pass "b: $CUR has the same expected sources as the table"
  else warn "b: the expected sources in $CUR differ from the table (< table, > json):"; diff "$TMP/src_table" "$TMP/src_cur" | grep '^[<>]' | head -20 | detail; fi
  dif=$(jq -r '[group_by(.difficulty)[] | "\(length) \(.[0].difficulty)"] | join(", ")' "$CUR")
  bad=0
  for d in easy medium hard; do
    n=$(jq --arg d "$d" '[.[] | select(.difficulty == $d)] | length' "$CUR")
    for f in "$EVAL" "$RESEARCH"; do
      grep -qE "(^|[^0-9])$n $d" "$TMP/norm.$(basename "$f")" || { fail "b: $f does not state '$n $d' ($CUR: $dif)"; bad=1; }
    done
  done
  [ "$bad" -eq 0 ] && pass "b: the difficulty counts in $EVAL and $RESEARCH match $CUR ($dif)"
else
  fail "b: $CUR is missing"
fi

# ---------------------------------------------------------------------------------------------------------
section "(c) links"
FENCE='/^ *(```|~~~)/ { f = $0; sub(/^ */, "", f); f = substr(f, 1, 3); if (fence == "") fence = f; else if (f == fence) fence = ""; next }
fence != "" { next }'
cat >"$TMP/urls.awk" <<'AWK'
# file <TAB> line <TAB> url <TAB> kind (check | placeholder | local | example)
{
  s = $0
  gsub(/<br>/, " ", s)
  while (match(s, /https?:\/\/[^] \t<>"'`|(){}[\\]+/)) {
    u = substr(s, RSTART, RLENGTH); nx = substr(s, RSTART + RLENGTH, 1)
    s = substr(s, RSTART + RLENGTH)
    while (u ~ /[.,;:!?*_']$/) u = substr(u, 1, length(u) - 1)
    host = u; sub(/^https?:\/\//, "", host); sub(/[\/:?#].*$/, "", host)
    kind = "check"
    if (nx == "<" || nx == "{" || u ~ /HOST|\$|\.\.\./) kind = "placeholder"
    else if (host ~ /^(localhost|127\.|0\.0\.0\.0|host\.docker\.internal)/ || host !~ /\./) kind = "local"
    else if (host ~ /(^|\.)example\.(com|org|net)$/) kind = "example"
    print FILENAME "\t" FNR "\t" u "\t" kind
  }
}
AWK
# shellcheck disable=SC2086
awk -f "$TMP/urls.awk" docs/*.md README.md >"$TMP/urls.tsv"
awk -F'\t' '$4 == "check" { print $3 }' "$TMP/urls.tsv" | sort -u >"$TMP/url_list"
nurl=$(wc -l <"$TMP/url_list" | tr -d ' ')
nskip=$(awk -F'\t' '$4 != "check" { print $3 }' "$TMP/urls.tsv" | sort -u | wc -l | tr -d ' ')
info "c: $nurl unique http(s) URLs to check in docs/*.md and README.md; $nskip skipped (templates, local or example hosts):"
awk -F'\t' '$4 != "check" { print $4 ": " $3 }' "$TMP/urls.tsv" | sort -u | tr '\n' ' ' | fold -w 150 | detail; echo

# Relative links and #anchors outside fenced code. GitHub slugs: lowercase, drop punctuation, spaces to '-'.
cat >"$TMP/slugs.awk" <<AWK
$FENCE
/^#+ / {
  h = \$0; sub(/^#+ +/, "", h); sub(/ +#+ *\$/, "", h)
  h = tolower(h); gsub(/[^a-z0-9 _-]/, "", h); gsub(/ /, "-", h)
  if (h in seen) { seen[h]++; h = h "-" seen[h] - 1 } else seen[h] = 1
  print h
}
AWK
cat >"$TMP/links.awk" <<AWK
FNR == 1 { fence = "" }
$FENCE
{
  s = \$0
  while (match(s, /\]\([^) ]+\)/)) { t = substr(s, RSTART + 2, RLENGTH - 3); s = substr(s, RSTART + RLENGTH); emit(t) }
  if (\$0 ~ /^\[[^]]+\]: /) { t = \$0; sub(/^\[[^]]+\]: */, "", t); sub(/ .*\$/, "", t); emit(t) }
}
function emit(t) { if (t !~ /^(https?:|mailto:)/) print FILENAME "\t" FNR "\t" t }
AWK
awk -f "$TMP/links.awk" docs/*.md README.md >"$TMP/rel.tsv"
nrel=0; nrelbad=0
while IFS="$TAB" read -r file line target; do
  nrel=$((nrel + 1))
  path=${target%%#*}; anchor=""
  case "$target" in *'#'*) anchor=${target#*#} ;; esac
  if [ -z "$path" ]; then tf="$file"; else tf="$(dirname "$file")/$path"; fi
  # Targets outside the snapshot (for example poc/README.md) are read from the repo.
  [ -e "$tf" ] || [ ! -e "$ROOT/$tf" ] || tf="$ROOT/$tf"
  if [ ! -e "$tf" ]; then fail "c: $file:$line: the link target '$target' does not exist"; nrelbad=$((nrelbad + 1)); continue; fi
  if [ -n "$anchor" ]; then
    case "$tf" in
      *.md) awk -f "$TMP/slugs.awk" "$tf" | grep -qxF -- "$anchor" \
              || { fail "c: $file:$line: the anchor '#$anchor' is not a heading in $tf"; nrelbad=$((nrelbad + 1)); } ;;
      *) warn "c: $file:$line: the anchor in '$target' was not checked (not Markdown)" ;;
    esac
  fi
done <"$TMP/rel.tsv"
[ "$nrelbad" -eq 0 ] && pass "c: all $nrel relative links and #anchors resolve"

# Reference-style links: every [text][label] and [[label]] has a "[label]: ..." definition in the same file.
cat >"$TMP/refs.awk" <<AWK
FNR == 1 { fence = "" }
$FENCE
/^\[[^]]+\]: / { lab = \$0; sub(/^\[/, "", lab); sub(/\]: .*\$/, "", lab); def[FILENAME SUBSEP tolower(lab)] = 1; next }
{
  s = \$0; gsub(/\`[^\`]*\`/, "", s); r = s
  while (match(r, /\]\[[^]]+\]/)) { use[++nu] = FILENAME "\t" FNR "\t" substr(r, RSTART + 2, RLENGTH - 3); r = substr(r, RSTART + RLENGTH) }
  r = s
  while (match(r, /\[\[[^]]+\]\]/)) { use[++nu] = FILENAME "\t" FNR "\t" substr(r, RSTART + 2, RLENGTH - 4); r = substr(r, RSTART + RLENGTH) }
}
END { for (i = 1; i <= nu; i++) { split(use[i], p, "\t"); if (!((p[1] SUBSEP tolower(p[3])) in def)) print use[i] } }
AWK
awk -f "$TMP/refs.awk" docs/*.md README.md >"$TMP/undef.tsv"
if [ -s "$TMP/undef.tsv" ]; then
  while IFS="$TAB" read -r file line lab; do fail "c: $file:$line: the reference [$lab] has no definition (renders as plain text)"; done <"$TMP/undef.tsv"
else
  pass "c: every reference-style citation label has a definition"
fi

if [ "$OFFLINE" -eq 1 ]; then
  warn "c: --offline: the URL and sitemap checks were skipped"
else
  cat >"$TMP/probe.sh" <<'SH'
#!/usr/bin/env bash
# probe.sh <url>: prints code <TAB> tries <TAB> url <TAB> final url
[ -n "${1:-}" ] || exit 0
u=$1; code=000; final=$u; tries=0
while [ "$tries" -lt 4 ]; do
  tries=$((tries + 1))
  out=$(curl -sL -o /dev/null --max-time 40 --connect-timeout 15 --max-redirs 10 -A "$UA" \
        -H 'Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8' \
        -H 'Accept-Language: en-US,en;q=0.9' -w '%{http_code} %{url_effective}' "$u" 2>/dev/null)
  code=${out%% *}; final=${out#* }
  case "$code" in 2??|3??) break ;; 404|410) [ "$tries" -ge 2 ] && break ;; esac
  case "$code" in 429) sleep $((tries * 15)) ;; *) sleep $((tries * 3)) ;; esac
done
printf '%s\t%s\t%s\t%s\n' "${code:-000}" "$tries" "$u" "$final"
SH
  export UA
  : >"$TMP/url_results"
  grep -v '^https://github\.com/' "$TMP/url_list" | tr '\n' '\0' \
    | xargs -0 -n 1 -P "$JOBS" bash "$TMP/probe.sh" >>"$TMP/url_results"
  ghjobs=$((JOBS / 2)); [ "$ghjobs" -lt 1 ] && ghjobs=1
  grep '^https://github\.com/' "$TMP/url_list" | tr '\n' '\0' \
    | xargs -0 -n 1 -P "$ghjobs" bash "$TMP/probe.sh" >>"$TMP/url_results"

  # A failing URL is only a WARN when every occurrence is labelled as such on its line or a neighbouring line:
  #   bot-blocking hosts (403/429/503): the line mentions 403, User-Agent or bot;
  #   API base URLs and endpoints (400/401/404/405): the line says "base URL", BASE_URL, "API base" or endpoint.
  nok=0
  while IFS="$TAB" read -r code tries url final; do
    case "$code" in
      2??|3??)
        nok=$((nok + 1))
        [ "$VERBOSE" -eq 1 ] && pass "c: $code $url"
        a=$(printf '%s' "$url" | sed -E 's#^https?://(www\.)?##; s/[#?].*$//; s#/$##')
        b=$(printf '%s' "$final" | sed -E 's#^https?://(www\.)?##; s/[#?].*$//; s#/$##')
        [ "$a" = "$b" ] || info "c: $url redirects to $final"
        continue ;;
    esac
    case "$code" in
      403|429|503) lab='403|User-Agent|bot' ;;
      400|401|404|405) lab='base URL|BASE_URL|API base|[Ee]ndpoint' ;;
      *) lab='' ;;
    esac
    occ=$(awk -F'\t' -v u="$url" '$3 == u { print $1 ":" $2 }' "$TMP/urls.tsv" | sort -u)
    unl=""
    for o in $occ; do
      of=${o%%:*}; ol=${o#*:}
      if [ -z "$lab" ] || ! sed -n "$((ol > 1 ? ol - 1 : 1)),$((ol + 1))p" "$of" | grep -qE "$lab"; then unl="$unl $o"; fi
    done
    if [ -z "$unl" ]; then
      warn "c: $code $url (labelled in the doc as a bot-blocking host or API base URL; at: $(echo $occ))"
    else
      fail "c: $code after $tries tries: $url (unlabelled at:$unl)"
    fi
  done < <(sort "$TMP/url_results")
  nres=$(wc -l <"$TMP/url_results" | tr -d ' ')
  [ "$nres" -eq "$nurl" ] || fail "c: probed only $nres of $nurl URLs"
  pass "c: $nok of $nurl URLs resolved with status < 400"

  # Every olake.io/docs URL used as an eval expected source must be in the live sitemap.
  if curl -sL --max-time 40 -A "$UA" -o "$TMP/sitemap.xml" https://olake.io/sitemap.xml \
     && grep -q '<loc>' "$TMP/sitemap.xml"; then
    grep -oE '<loc>[^<]+</loc>' "$TMP/sitemap.xml" | sed -e 's/<loc>//' -e 's#</loc>##' | sort -u >"$TMP/locs"
    nloc=$(wc -l <"$TMP/locs" | tr -d ' ')
    ndocs=$(grep -c '^https://olake.io/docs/' "$TMP/locs")
    nblog=$(grep -c '^https://olake.io/blog/' "$TMP/locs")
    nlm=$(grep -o '<lastmod>' "$TMP/sitemap.xml" | wc -l | tr -d ' ')
    info "c: live sitemap: $nloc URLs, $ndocs under /docs/, $nblog under /blog/, $nlm with lastmod"
    if [ "$nloc" = 275 ] && [ "$ndocs" = 124 ] && [ "$nblog" = 86 ] && [ "$nlm" = 231 ]; then
      pass "c: the live sitemap still matches the counts in $RESEARCH (275 / 124 / 86 / 231 lastmod)"
    else
      warn "c: the live sitemap differs from the counts in $RESEARCH (275 / 124 / 86 / 231 lastmod on 2026-10-16)"
    fi
    awk -F'\t' '$1 == "SRC" && $3 ~ /^https:\/\/olake\.io\// { print $2 "\t" $3 }' "$TMP/rowcheck" >"$TMP/olake_src"
    nsrc=0; nbad=0
    while IFS="$TAB" read -r id u; do
      nsrc=$((nsrc + 1))
      grep -qxF -- "$u" "$TMP/locs" && continue
      case "$u" in
        https://olake.io/docs/*) fail "c: the eval source of $id is not in the sitemap: $u"; nbad=$((nbad + 1)) ;;
        *) warn "c: the eval source of $id (outside /docs/) is not in the sitemap: $u" ;;
      esac
    done <"$TMP/olake_src"
    [ "$nbad" -eq 0 ] && pass "c: all $nsrc olake.io eval-source cells are sitemap URLs"
    # Other olake.io/docs links in the docs should be sitemap URLs too (query and fragment ignored).
    while IFS= read -r u; do
      grep -qxF -- "$u" "$TMP/locs" || warn "c: a linked docs URL is not a sitemap URL: $u"
    done < <(grep '^https://olake.io/docs/' "$TMP/url_list" | sed -E 's/[?#].*$//' | sort -u)
    # plan.md: all 16 denylisted pages must be live /docs/ URLs for "124 - 16 = 108" to hold.
    deny=$(awk '/DENYLIST \(stub or stale pages/ { on = 1 } on { print } on && /16 pages;/ { exit }' "$PLAN" \
           | grep -oE '/docs/[a-z0-9/_-]+/' | sort -u)
    ndeny=$(printf '%s\n' "$deny" | grep -c '^/docs/')
    dbad=0
    for p in $deny; do
      grep -qxF "https://olake.io$p" "$TMP/locs" || { fail "c: the denylisted path $p is not in the sitemap"; dbad=1; }
    done
    if [ "$ndeny" -ne 16 ]; then fail "c: the $PLAN denylist has $ndeny paths; the plan says 16"
    elif [ "$dbad" -eq 0 ]; then pass "c: all 16 denylisted paths are live sitemap URLs ($ndocs - 16 = $((ndocs - 16)) indexable /docs/ pages)"; fi
  else
    fail "c: could not fetch https://olake.io/sitemap.xml"
  fi
fi

# ---------------------------------------------------------------------------------------------------------
section "(d) hygiene"
cd "$ROOT" || exit 2
# The patterns are split so that this file does not match itself.
PERSONAL_RE='/Use''rs/|/priv''ate/tmp|/ho''me/|/var/fol''ders/|techfreak''worm'
SECRET_RE='(^|[^A-Za-z0-9])sk-[A-Za-z0-9_-]{20,}|AI''za[0-9A-Za-z_-]{35}|gh''p_[A-Za-z0-9]{36}|github_''pat_[A-Za-z0-9_]{22,}|xox[abps]''-[A-Za-z0-9-]{10,}|AK''IA[0-9A-Z]{16}|(^|[^A-Za-z0-9])hf_[A-Za-z0-9]{30,}|-----BEGIN [A-Z ]*PRIVATE'' KEY-----'
for pair in "personal paths|$PERSONAL_RE" "secret patterns|$SECRET_RE"; do
  name=${pair%%|*}; re=${pair#*|}
  hits=$(git grep -nIE -e "$re" -- . 2>/dev/null | cut -c1-200)
  if [ -z "$hits" ]; then pass "d: no $name in the tracked files (working tree)"
  else fail "d: $name in tracked files:"; printf '%s\n' "$hits" | head -30 | detail; fi
done
if git rev-parse --verify -q "$BASE" >/dev/null; then
  revs=$(git rev-list "$BASE"..HEAD)
  nrev=$(printf '%s\n' "$revs" | grep -c . || true)
  for pair in "personal paths|$PERSONAL_RE" "secret patterns|$SECRET_RE"; do
    name=${pair%%|*}; re=${pair#*|}
    hits=""
    # shellcheck disable=SC2086
    [ -n "$revs" ] && hits=$(git grep -nIE -e "$re" $revs -- . 2>/dev/null | cut -c1-200)
    if [ -z "$hits" ]; then pass "d: no $name in any of the $nrev branch commits ($BASE..HEAD)"
    else fail "d: $name in the branch history (pushed with the branch):"; printf '%s\n' "$hits" | head -20 | detail; fi
  done
  attr=$(git log --format='%h %B' "$BASE"..HEAD | grep -inE 'co-authored-by|claude-session|generated with|noreply@anthropic\.com|claude\.com/claude-code' || true)
  if [ -z "$attr" ]; then pass "d: no AI attribution lines in the $nrev branch commit messages"
  else fail "d: AI attribution lines in branch commit messages:"; printf '%s\n' "$attr" | detail; fi
  me=$(git config user.name); mymail=$(git config user.email)
  if [ -z "$me" ]; then
    fail "d: git user.name is not configured"
  else
    others=$(git log --format='%h%x09%an' "$BASE"..HEAD | awk -F'\t' -v me="$me" '$2 != me { print $1 " " $2 }')
    if [ -z "$others" ]; then pass "d: all $nrev branch commits are authored by the configured user.name"
    else fail "d: branch commits not authored by the configured user.name:"; printf '%s\n' "$others" | detail; fi
    om=$(git log --format='%h%x09%ae%x09%cn' "$BASE"..HEAD \
         | awk -F'\t' -v m="$mymail" -v me="$me" '$2 != m { print $1 " author email differs" } $3 != me { print $1 " committer " $3 }')
    [ -z "$om" ] || { warn "d: the author email or committer differs from the configured identity:"; printf '%s\n' "$om" | detail; }
  fi
else
  fail "d: the base ref $BASE was not found, so the branch commits were not checked"
fi
tracked=$(git ls-files -- .env '*.env' '.claude/*' 2>/dev/null)
if [ -z "$tracked" ]; then pass "d: no .env files or .claude/ local settings are tracked"
else fail "d: tracked local files:"; printf '%s\n' "$tracked" | detail; fi

# ---------------------------------------------------------------------------------------------------------
section "(e) POC numbers in the docs vs $RES/*.json"
cd "$SNAP" || exit 2
# jq helpers: fmt(d) rounds to d decimals; commas adds thousands separators to a digit string;
# fmtc(d) does both; pct is a percentage with one decimal and no trailing ".0".
JQDEF='
def fmt(d): . as $x | (if $x < 0 then "-" else "" end) as $s | (if $x < 0 then -$x else $x end) as $a
  | pow(10; d) as $p | ($a * $p | round) as $n
  | if d == 0 then $s + ($n | tostring)
    else $s + (($n / $p | floor) | tostring) + "." + (("0" * d) + (($n % $p) | tostring))[-d:] end;
def commas: if length <= 3 then . else (.[0:length-3] | commas) + "," + .[length-3:] end;
def fmtc(d): fmt(d) | split(".") as $p
  | ($p[0] | if startswith("-") then "-" + (.[1:] | commas) else commas end)
    + (if ($p | length) > 1 then "." + $p[1] else "" end);
def pct: . * 100 | fmt(1) | sub("\\.0$"; "");
'
# num <doc> <label> <jq expression over the slurped files .[0], .[1], ...> <json files...>
# The jq expression builds the exact text the doc must contain (compared with whitespace normalised).
NUM_OK=0
num() {
  local doc="$1" label="$2" expr="$3"; shift 3
  local want
  if ! want=$(jq -r -s "$JQDEF $expr" "$@" 2>"$TMP/jqerr"); then
    fail "e: $label: jq failed on $*: $(head -1 "$TMP/jqerr")"; return
  fi
  want=$(printf '%s' "$want" | tr -s '[:space:]' ' ')
  if [ -z "$want" ] || [ "$want" = null ]; then fail "e: $label: no value in $*"; return; fi
  if grep -qF -- "$want" "$TMP/norm.$(basename "$doc")"; then
    NUM_OK=$((NUM_OK + 1)); [ "$VERBOSE" -eq 1 ] && pass "e: $label: '$want' ($*)"
  else
    fail "e: $label: $doc does not contain '$want' (from $*)"
  fi
  return 0
}
C=$RES/corpus.json; K=$RES/chunks.json; R=$RES/retrieval.json; L=$RES/latency_threads.json
A=$RES/answer.json; G=$RES/gate-canonical.json; E=$RES/embed_probe.json; F=$RES/freshness.json
for j in $C $K $R $L $A $G $E $F; do [ -s "$j" ] || fail "e: $j is missing"; done

# corpus.json
num $RESEARCH "sitemap and docs page count" '.[0].docs_fetch | "\(.sitemap_urls) URLs: \(.per_section.docs) under `/docs/`"' $C
num $RESEARCH "sitemap split (blog = 85 posts + the index)" '.[0].docs_fetch | "| \(.sitemap_urls), \(.per_section.docs), \(.per_section.blog + 1), \(.sitemap_urls - .per_section.docs - .per_section.blog - 1) |"' $C
num $RESEARCH "docs tokens" '"or \(.[0].docs.total.tokens | tostring | commas) from the POC'"'"'s Markdown"' $C
num $RESEARCH "docs tokens (table)" '"| Docs tokens (o200k_base) | \(.[0].docs.total.tokens | tostring | commas) |"' $C
num $RESEARCH "docs structure" '.[0].docs.total | "\(.code_blocks) code blocks, \(.tables) tables, \(.tabs) tab groups"' $C
num $RESEARCH "admonitions" '"\(.[0].docs.total.admonitions) admonitions"' $C
num $RESEARCH "thin pages" '.[0].docs.total.pages_under_100_tokens as $t | "\($t | length) pages under 100 tokens (\([$t[] | select(contains("/docs/fusion/"))] | length) of them among the 23 Fusion pages)"' $C
num $RESEARCH "docs fetch time" '.[0].docs_fetch | "The POC took \(.fetch_wall_s_by_section.docs) s at concurrency \(.concurrency)"' $C
num $RESEARCH "blog tokens" '"or \(.[0].blog.total.tokens | tostring | commas) from the POC'"'"'s Markdown"' $C
num $RESEARCH "release-note pages" '"\(.[0].docs.by_section.release.pages) pages under `/docs/release/`"' $C
num $RESEARCH "tokens per page" '.[0].docs.total | "| \(.tokens_per_page_p50 | tostring | commas); \(.tokens_per_page_max | tostring | commas) |"' $C
num $RESEARCH "repo allowlist" '.[0].repos.total | "\(.files) files, \(.tokens | tostring | commas) tokens"' $C
num $RESEARCH "docs plus repos" '.[0].combined_docs_plus_repos | "\(.documents) documents, \(.tokens | tostring | commas) tokens"' $C
num $RESEARCH "209-page fetch" '.[0].docs_fetch | "Fetch of \(.fetched_ok) pages at concurrency \(.concurrency) | \(.fetch_wall_s) s (per page p50 \(.per_page_fetch_s_p50) s)"' $C
for repo in olake olake-ui olake-helm olake-fusion; do
  num $RESEARCH "repo row $repo" ".[0].repos.per_repo[\"$repo\"] | \"| $repo | \(.sha[0:7]) (\(.commit_date[0:10])) | \(.tracked_files | tostring | commas) |\"" $C
done
num $PLAN "plan: 209 pages in 12.77 s" '.[0].docs_fetch | "fetched \(.fetched_ok) pages in \(.fetch_wall_s) s at concurrency \(.concurrency)"' $C
num $PLAN "plan: 124 - 16 = 108" '"(\(.[0].docs.total.pages) - 16 = \(.[0].docs.total.pages - 16) on 2026-10-16"' $C

# chunks.json
for i in 0 1; do
  num $RESEARCH "chunks config $i" ".[0].configs[$i] | \"| Chunks at target \(.target) / hard max \(.hard_max) (no blog) | \(.chunks | tostring | commas) (docs \(.by_source_type.docs.n | tostring | commas), repo \(.by_source_type.repo.n)); tokens p50 \(.tokens.p50), p95 \(.tokens.p95), max \(.tokens.max); \(.over_hard_max) over hard max |\"" $K
done
num $RESEARCH "vector count range" '"\(.[0].configs | map(.chunks) | min | tostring | commas)-\(.[0].configs | map(.chunks) | max | tostring | commas) chunks without the blog"' $K

# retrieval.json (seed set)
num $RESEARCH "WordPiece truncation at 600" '.[0].per_target["600"] | "\(.embedding["BAAI/bge-small-en-v1.5"].wordpiece_over_512) of \(.chunks) chunks exceed"' $R
num $RESEARCH "WordPiece truncation at 300" '.[0].per_target["300"] | "At 300 only \(.embedding["BAAI/bge-small-en-v1.5"].wordpiece_over_512) of \(.chunks | tostring | commas) do"' $R
rrow() { # <label as in the doc table> <config key in retrieval.json>
  num $RESEARCH "retrieval row: $1" ".[0].per_target[\"300\"].configs[\"$2\"] | \"| $1 | \(.\"hit@1\" | fmt(3)) | \(.\"hit@5\" | fmt(3)) | \(.\"hit@10\" | fmt(3)) | \(.\"mrr@10\" | fmt(3)) | \(.latency_ms.total_ms.p50 | fmt(2)) |\"" $R
}
rrow "BM25" "bm25"
rrow "Dense bge-small-en-v1.5" "dense:BAAI/bge-small-en-v1.5"
rrow "Dense bge-base-en-v1.5" "dense:BAAI/bge-base-en-v1.5"
rrow "Hybrid (RRF) bge-small" "hybrid:BAAI/bge-small-en-v1.5"
rrow "Hybrid (RRF) bge-base" "hybrid:BAAI/bge-base-en-v1.5"
rrow "Hybrid bge-base + rerank ms-marco-MiniLM-L-6-v2" "hybrid:BAAI/bge-base-en-v1.5+rerank:Xenova/ms-marco-MiniLM-L-6-v2"
rrow "Hybrid bge-base + rerank bge-reranker-base" "hybrid:BAAI/bge-base-en-v1.5+rerank:BAAI/bge-reranker-base"
rrow "BM25 + rerank ms-marco-MiniLM-L-6-v2" "bm25+rerank:Xenova/ms-marco-MiniLM-L-6-v2"
num $RESEARCH "embedding speed ratio" '.[0].per_target["300"].embedding as $e | "embeds the corpus \($e["BAAI/bge-base-en-v1.5"].embed_full_corpus_s / $e["BAAI/bge-small-en-v1.5"].embed_full_corpus_s | fmt(1))x faster"' $R
num $RESEARCH "embedding times" '.[0].per_target["300"].embedding as $e | "(\($e["BAAI/bge-small-en-v1.5"].embed_full_corpus_s) s vs \($e["BAAI/bge-base-en-v1.5"].embed_full_corpus_s) s"' $R
num $RESEARCH "seed MRR / hit@5 (section 9)" '.[0].per_target["300"].configs as $c | "BM25 \($c.bm25."mrr@10" | fmt(3)) / \($c.bm25."hit@5" | fmt(3)); hybrid bge-base \($c["hybrid:BAAI/bge-base-en-v1.5"]."mrr@10" | fmt(3)) / \($c["hybrid:BAAI/bge-base-en-v1.5"]."hit@5" | fmt(3)); + MiniLM-L6 rerank \($c["hybrid:BAAI/bge-base-en-v1.5+rerank:Xenova/ms-marco-MiniLM-L-6-v2"]."mrr@10" | fmt(3)) / \($c["hybrid:BAAI/bge-base-en-v1.5+rerank:Xenova/ms-marco-MiniLM-L-6-v2"]."hit@5" | fmt(3)); + bge-reranker-base \($c["hybrid:BAAI/bge-base-en-v1.5+rerank:BAAI/bge-reranker-base"]."mrr@10" | fmt(3)) / \($c["hybrid:BAAI/bge-base-en-v1.5+rerank:BAAI/bge-reranker-base"]."hit@5" | fmt(3))"' $R
num $RESEARCH "retrieval p50 (section 9)" '.[0].per_target["300"].configs as $c | "hybrid bge-base \($c["hybrid:BAAI/bge-base-en-v1.5"].latency_ms.total_ms.p50 | fmt(2)) ms; + MiniLM-L6 rerank \($c["hybrid:BAAI/bge-base-en-v1.5+rerank:Xenova/ms-marco-MiniLM-L-6-v2"].latency_ms.total_ms.p50 | fmtc(2)) ms; + bge-reranker-base \($c["hybrid:BAAI/bge-base-en-v1.5+rerank:BAAI/bge-reranker-base"].latency_ms.total_ms.p50 | fmtc(2)) ms"' $R
num $PLAN "plan: full-corpus embedding" '.[0].per_target["300"].embedding as $e | "the full-corpus embedding took \($e["BAAI/bge-small-en-v1.5"].embed_full_corpus_s | fmt(0)) s (bge-small) or \($e["BAAI/bge-base-en-v1.5"].embed_full_corpus_s | fmt(0)) s (bge-base)"' $R
num $PLAN "plan: embedding speed ratio" '.[0].per_target["300"].embedding as $e | ($e["BAAI/bge-small-en-v1.5"].embed_full_corpus_s) as $s | ($e["BAAI/bge-base-en-v1.5"].embed_full_corpus_s) as $b | "It embeds \($b / $s | fmt(1))x faster (\($s | fmt(0)) s vs \($b | fmt(0)) s for the corpus"' $R
num $PLAN "plan: seed hit@5 of the rerankers" '.[0].per_target["300"].configs as $c | "seed-set hit@5 \($c["hybrid:BAAI/bge-base-en-v1.5+rerank:BAAI/bge-reranker-base"]."hit@5" | fmt(3)) vs \($c["hybrid:BAAI/bge-base-en-v1.5+rerank:Xenova/ms-marco-MiniLM-L-6-v2"]."hit@5" | fmt(3))"' $R

# latency_threads.json (+ dims and corpus embedding times from retrieval.json)
num $RESEARCH "embed table: bge-small" '"| BAAI/bge-small-en-v1.5 | \(.[1].per_target["300"].embedding["BAAI/bge-small-en-v1.5"].dim) | \(.[0].by_threads["2"].query_embed_bge_small_ms.p50) ms | | \(.[1].per_target["300"].embedding["BAAI/bge-small-en-v1.5"].embed_full_corpus_s) s |"' $L $R
num $RESEARCH "embed table: bge-base" '"| BAAI/bge-base-en-v1.5 | \(.[1].per_target["300"].embedding["BAAI/bge-base-en-v1.5"].dim) | \(.[0].by_threads["2"].query_embed_bge_base_ms.p50) ms | | \(.[1].per_target["300"].embedding["BAAI/bge-base-en-v1.5"].embed_full_corpus_s) s |"' $L $R
num $RESEARCH "MiniLM rerank at 2 threads" '.[0].by_threads["2"] | "\(."rerank_ms-marco-MiniLM-L-6-v2_top10_ms".p50) / \(."rerank_ms-marco-MiniLM-L-6-v2_top20_ms".p50) ms (\(."rerank_ms-marco-MiniLM-L-6-v2_top20_trunc1000chars_ms".p50) ms for top 20 with passages cut to 1,000 chars)"' $L
num $RESEARCH "bge-reranker-base at 2 threads" '.[0].by_threads["2"] | "\(."rerank_bge-reranker-base_top10_ms".p50 | fmtc(1)) / \(."rerank_bge-reranker-base_top20_ms".p50 | fmtc(1)) ms"' $L
num $RESEARCH "rerank p50 (section 9)" '.[0].by_threads["2"] | "| MiniLM-L6 \(."rerank_ms-marco-MiniLM-L-6-v2_top10_ms".p50) ms; bge-reranker-base \(."rerank_bge-reranker-base_top10_ms".p50) ms |"' $L
num $RESEARCH "query embed p50 (section 9)" '.[0].by_threads["2"] | "| bge-small \(.query_embed_bge_small_ms.p50) ms; bge-base \(.query_embed_bge_base_ms.p50) ms |"' $L
num $RESEARCH "MiniLM top-10 rerank (5.8)" '"MiniLM-L6 takes \(.[0].by_threads["2"]."rerank_ms-marco-MiniLM-L-6-v2_top10_ms".p50) ms for the top 10 at 2 threads"' $L
num $RESEARCH "bge-reranker-base top 10 (5.3)" '"bge-reranker-base: \(.[0].by_threads["2"]."rerank_bge-reranker-base_top10_ms".p50) ms for the top 10 at 2 threads"' $L
num $RESEARCH "query embed at 2 threads (5.3)" '"\(.[0].by_threads["2"].query_embed_bge_small_ms.p50) ms at 2 threads in the POC"' $L
num $PLAN "plan: MiniLM top 10 at 2 threads" '"Xenova/ms-marco-MiniLM-L-6-v2: \(.[0].by_threads["2"]."rerank_ms-marco-MiniLM-L-6-v2_top10_ms".p50) ms for the top 10 at 2 threads"' $L
num $PLAN "plan: bge-reranker-base top 10 at 2 threads" '"BAAI/bge-reranker-base: \(.[0].by_threads["2"]."rerank_bge-reranker-base_top10_ms".p50) ms for the top 10 at 2 threads"' $L

# embed_probe.json
num $RESEARCH "API memory (section 9)" '.[0].api_rss_mb | "| \(.after_one_query | tostring | commas) MB RSS after one query; \(.after_scorer_run_concurrency_4 | tostring | commas) MB after a scorer run at concurrency 4 |"' $E
if jq -e '.strict_csp_page | .widget_rendered == true and .ask_blocked == true and .violation.directive == "connect-src"' $E >/dev/null 2>&1 \
   && grep -qF 'blocked by a `connect-src` violation' "$TMP/norm.research.md"; then
  NUM_OK=$((NUM_OK + 1))
else
  fail "e: strict-CSP probe: $E or $RESEARCH no longer says that the widget rendered and /ask was blocked by connect-src"
fi

# answer.json (seed set, local model)
num $RESEARCH "tokens per answer (section 9)" '.[0].tokens_per_answer | "| prompt mean \(.prompt_mean | fmtc(0)) (max \(.prompt_max | tostring | commas)); completion mean \(.completion_mean) (max \(.completion_max)) |"' $A
num $RESEARCH "tokens per answer (5.2)" '.[0].tokens_per_answer | "averaged \(.prompt_mean | fmtc(0)) input and \(.completion_mean) output tokens"' $A
num $RESEARCH "answered source hit" '"hit an expected source \(.[0].answered_source_hit_rate | pct)% of the time"' $A
num $RESEARCH "answer-run retrieval p50" '"Retrieval took \(.[0].latency_ms.retrieval_ms.p50) ms p50"' $A
num $RESEARCH "answer-run rerank p50" '"rerank \(.[0].latency_ms.rerank_ms.p50) ms p50"' $A
num $RESEARCH "think probe" '.[0].think_probe | "from \(.default.llm_ttft_ms | fmtc(0)) ms to \(.reasoning_none.llm_ttft_ms | fmtc(0)) ms"' $A
num $RESEARCH "seed gate (section 9)" '.[0].policy_a_gate | "threshold \(.threshold): precision \(.precision | fmt(1)), recall \(.recall | fmt(1)), false-abstain \(.false_abstain_rate | fmt(1)) (\(.n_should_abstain) should abstain, \(.n_should_answer) should answer)"' $A
num $RESEARCH "model flag (section 9)" '.[0].policy_b_model | "precision \(.precision), recall \(.recall | fmt(1)), false-abstain \(.false_abstain_rate)"' $A
num $RESEARCH "model flag (4.3)" '.[0].policy_b_model | "(precision \(.precision), false-abstain \(.false_abstain_rate))"' $A
num $RESEARCH "answered hit (section 9)" '"| Answered questions that hit an expected source | \(.[0].answered_source_hit_rate) |"' $A

# gate-canonical.json (curated set)
num $RESEARCH "curated gate rows" '.[0].policy_a_gate | "\(.n_should_abstain) rows should abstain, the 6 unanswerable and 6 out-of-scope; \(.n_should_answer) should answer"' $G
num $RESEARCH "best threshold" '.[0].policy_a_gate | "The best single threshold, \(.threshold | fmt(2)), reached recall \(.recall), but with precision \(.precision), false abstains on \(.false_abstain_rate_answerable | pct)% of answerable rows and \(.false_abstain_rate | pct)% of all must-answer rows"' $G
num $RESEARCH "-0.891 recall" '.[0].per_question as $q | [$q[] | select(.must_abstain)] as $m | [$m[] | select(.top_score < -0.891)] as $c | "caught only \($c | length) of the \($m | length) (recall \(($c | length) / ($m | length) | fmt(1)))"' $G
num $RESEARCH "-0.891 false abstains" '.[0].per_question as $q | [$q[] | select(.type == "answerable")] as $a | [$a[] | select(.top_score < -0.891)] as $fa | "on \($fa | length) of \($a | length) answerable rows (\(($fa | length) / ($a | length) | pct)%)"' $G
num $RESEARCH "score ranges (section 9)" '.[0].by_type as $b | "answerable \($b.answerable.top_score_min | fmt(2)) to \($b.answerable.top_score_max | fmt(2)); unanswerable \($b.unanswerable.top_score_min | fmt(2)) to \($b.unanswerable.top_score_max | fmt(2)); out-of-scope \($b["out-of-scope"].top_score_min | fmt(2)) to \($b["out-of-scope"].top_score_max | fmt(2)); adversarial \($b.adversarial.top_score_min | fmt(2)) to \($b.adversarial.top_score_max | fmt(2))"' $G
num $RESEARCH "answerable score range (4.3)" '.[0].by_type.answerable | "Answerable rows range from \(.top_score_min | fmt(2)) to \(.top_score_max | fmt(2))"' $G
num $RESEARCH "UNK-01 score" '"(UNK-01: \([.[0].per_question[] | select(.id == "UNK-01")][0].top_score | fmt(2)))"' $G
num $RESEARCH "ADV-03 score" '"(ADV-03: \([.[0].per_question[] | select(.id == "ADV-03")][0].top_score | fmt(2)))"' $G
num $RESEARCH "context hit rate" '"\(.[0].context_hit_rate_top_passages | pct)%"' $G
num $PLAN "plan: best threshold" '.[0].policy_a_gate | "threshold (\(.threshold | fmt(2))) false-abstained on \(.false_abstain_rate_answerable | pct)% of answerable rows"' $G
# The context hit rate is over the rows that have expected sources; any denominator the doc gives must match.
den=$(jq '[.per_question[] | select(.context_hit != null)] | length' $G)
hits=$(jq '[.per_question[] | select(.context_hit == true)] | length' $G)
rate=$(jq -r "$JQDEF"' .context_hit_rate_top_passages | pct' $G)
for d in $(grep -oE "$rate% of (the )?[0-9]+ rows" "$TMP/norm.research.md" | grep -oE '[0-9]+ rows' | grep -oE '[0-9]+'); do
  if [ "$d" = "$den" ]; then NUM_OK=$((NUM_OK + 1))
  else fail "e: $RESEARCH says '$rate% of $d rows', but $G computes it over the $den rows with expected sources ($hits of $den; context_hit is null on the other rows)"; fi
done

# freshness.json
num $RESEARCH "conditional GET" '"| Conditional GET to olake.io (304) | ≈ \(.[0].docs_page.if_none_match.ms | fmt(0)) ms |"' $F
num $RESEARCH "git ls-remote range" '[.[0].git_ls_remote[].ms] | "| `git ls-remote` per repo | \(min | fmt(0))-\(max | fmt(0)) ms |"' $F
num $RESEARCH "GitHub limits" '"| \(.[0].github_unauthenticated.rate_before.limit) per hour, \(.[0].github_authenticated.rate_before.limit | tostring | commas) per hour |"' $F
num $RESEARCH "lastmod redesign commit" '"\(.[0].observations.docs_pages_by_sitemap_lastmod["2026-10-06"]) of the \(.[0].observations.docs_pages_by_http_last_modified | add) dates come from one site-wide redesign commit on 2026-10-06"' $F

[ "$NUM_OK" -gt 0 ] && pass "e: $NUM_OK number checks agree between the docs and $RES/*.json"
info "e: not checkable (no JSON in $RES): the canonical-set retrieval table in $RESEARCH (MRR 0.68 ... 0.745)"

# ---------------------------------------------------------------------------------------------------------
printf '\n== Summary: %d PASS, %d WARN, %d FAIL\n' "$NPASS" "$NWARN" "$NFAIL"
[ "$NFAIL" -eq 0 ]
