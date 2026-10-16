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
#   (e) key POC numbers quoted in docs/research.md (and a few in docs/plan.md) match poc/results/*.json;
#       numbers are matched in any common formatting, so the wording around them is free
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
# research.md cites corpus v1 numbers "at POC commit 20b4bac"; keep that file for the (e) checks.
git show 20b4bac:poc/results/corpus.json >"$SNAP/poc/results/.corpus-v1.json" 2>/dev/null || rm -f "$SNAP/poc/results/.corpus-v1.json"
cd "$SNAP" || exit 2

# Whitespace-normalised copy of a doc, so that a quoted phrase matches across line wraps.
norm() { LC_ALL=C tr -s '[:space:]' ' ' <"$1"; }
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
  # Trailers and the "Generated with" footer only: "regenerated with" in a commit body is not attribution.
  attr=$(git log --format='%h %B' "$BASE"..HEAD \
    | grep -nE '(^|[^[:alnum:]])[Gg]enerated with|[Cc]o-[Aa]uthored-[Bb]y:|[Cc]laude-[Ss]ession:|noreply@anthropic\.com|claude\.com/claude-code' || true)
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
# Each check takes numbers from the result JSON with jq and looks for each number in the doc, in any common
# formatting: with or without thousands separators, rounded to any precision that keeps at least 2 significant
# digits, and as a percentage with -p. The wording around a number is free. Small or common numbers take a
# context pattern (-c ERE, lowercase): the number must then sit within 300 characters of a match.
cat >"$TMP/numfind.awk" <<'AWK'
function sig(s,   t) { t = s; gsub(/[^0-9]/, "", t); sub(/^0+/, "", t); return length(t) }
function commas(s,   ip, fp, out) {
  ip = s; fp = ""
  if (index(s, ".")) { fp = substr(s, index(s, ".")); ip = substr(s, 1, index(s, ".") - 1) }
  out = ""
  while (length(ip) > 3) { out = "," substr(ip, length(ip) - 2) out; ip = substr(ip, 1, length(ip) - 3) }
  return ip out fp
}
function isdig(c) { return c ~ /^[0-9]$/ }
function nearctx(pos,   i) { if (ctx == "") return 1; for (i = 1; i <= nc; i++) if (pos >= cp[i] - win && pos <= cp[i] + win) return 1; return 0 }
function found(f, neg,   start, p, pos, b, b2, a, a2, ok) {
  start = 1
  while ((p = index(substr(T, start), f)) > 0) {
    pos = start + p - 1; start = pos + 1
    b = substr(T, pos - 1, 1); b2 = substr(T, pos - 2, 1)
    a = substr(T, pos + length(f), 1); a2 = substr(T, pos + length(f) + 1, 1)
    ok = 1
    if (pos > 1 && (isdig(b) || b == "." || (b == "," && isdig(b2)))) ok = 0
    if (!neg && pos > 1 && b == "-" && !isdig(b2)) ok = 0
    if (isdig(a) || ((a == "." || a == ",") && isdig(a2))) ok = 0
    if (pct && a != "%" && !(a == " " && a2 == "%")) ok = 0
    if (ok && nearctx(pos)) return 1
  }
  return 0
}
{ T = T $0 " " }
END {
  if (ctx != "") { L = tolower(T); s = 1; while (match(substr(L, s), ctx)) { cp[++nc] = s + RSTART - 1; s = s + RSTART + RLENGTH - 1; if (RLENGTH == 0) s++ } }
  n = split(vals, V, " ")
  for (i = 1; i <= n; i++) {
    v = V[i]; neg = substr(v, 1, 1) == "-"; a = neg ? substr(v, 2) : v; x = a + 0
    delete F; nf = 0; F[++nf] = a
    for (d = 0; d <= 4; d++) for (e = -1; e <= 1; e++) {
      s = sprintf("%." d "f", x + e * 1e-9); if (sig(s) >= 2 || sig(s) >= sig(a)) F[++nf] = s
    }
    hit = 0; list = ""
    for (k = 1; k <= nf && !hit; k++) {
      f = F[k]; g = commas(f)
      if (neg) { hit = found("-" f, 1) || found("-" g, 1) || found("\342\210\222" f, 1) || found("\342\210\222" g, 1) }
      else hit = found(f, 0) || found(g, 0)
      list = list " " (neg ? "-" : "") g
    }
    if (!hit) print "MISSING\t" v "\t" list
  }
}
AWK
NUM_OK=0; NUM_VALS=0
# num <doc> <label> [-c <context ERE>] [-p] <jq expression over the slurped files .[0], .[1], ...> <json files...>
num() {
  local doc="$1" label="$2" ctx="" pct=0 expr vals miss
  shift 2
  while :; do
    case "${1:-}" in
      -c) ctx="$2"; shift 2 ;;
      -p) pct=1; shift ;;
      *) break ;;
    esac
  done
  expr="$1"; shift
  if ! vals=$(jq -r -s "$expr" "$@" 2>"$TMP/jqerr"); then fail "e: $label: jq failed on $*: $(head -1 "$TMP/jqerr")"; return 0; fi
  vals=$(printf '%s\n' "$vals" | tr -s ' \n' '  ')
  if [ -z "${vals// /}" ] || printf '%s' "$vals" | grep -q null; then fail "e: $label: no value in $* ($expr)"; return 0; fi
  # Byte semantics (LC_ALL=C): the matcher compares raw bytes, and a failed awk run must not count as a pass.
  if ! miss=$(LC_ALL=C awk -v vals="$vals" -v ctx="$ctx" -v pct="$pct" -v win=300 -f "$TMP/numfind.awk" \
                "$TMP/norm.$(basename "$doc")" 2>"$TMP/awkerr") || [ -s "$TMP/awkerr" ]; then
    fail "e: $label: the number matcher failed: $(head -1 "$TMP/awkerr")"; return 0
  fi
  NUM_VALS=$((NUM_VALS + $(printf '%s\n' $vals | grep -c .)))
  if [ -z "$miss" ]; then
    NUM_OK=$((NUM_OK + 1)); [ "$VERBOSE" -eq 1 ] && pass "e: $label: [$vals ] found in $doc"
  else
    fail "e: $label: $doc does not quote $(printf '%s\n' "$miss" | awk -F'\t' '{ printf "%s%s (tried%s)", sep, $2, $3; sep = "; " }') ($*${ctx:+, near /$ctx/})"
  fi
  return 0
}
C=$RES/corpus.json; C1=$RES/.corpus-v1.json; K=$RES/chunks.json; R=$RES/retrieval.json; L=$RES/latency_threads.json
A=$RES/answer.json; G=$RES/gate-canonical.json; E=$RES/embed_probe.json; F=$RES/freshness.json
RC=$RES/retrieval-canonical.json; RB=$RES/retrieval-canonical-bge-reranker.json; V=$RES/retrieval-v2.json
GS=$RES/gate-signals.json; GR=$RES/gate-rewrite.json; EC=$RES/eval_run-canonical.json; E2=$RES/eval_run-canonical-v2-subset.json
for j in $C $K $R $L $A $G $E $F $RC $RB $V $GS $GR $EC $E2; do [ -s "$j" ] || fail "e: $j is missing"; done
D=$RESEARCH

# corpus.json (corpus v2) and the corpus v1 file the measurements used (git show of POC commit 20b4bac)
num $D "sitemap and fetch counts" '.[0].docs_fetch | .sitemap_urls, .per_section.docs, .per_section.blog, .fetched_ok, .fetch_wall_s, .per_page_fetch_s_p50, .fetch_wall_s_by_section.docs' $C
num $D "docs size" '.[0].docs.total | .tokens, .code_blocks, .tables, .admonitions, .tokens_per_page_p50, .tokens_per_page_max' $C
num $D "tab groups" -c 'tab group' '.[0].docs.total.tabs' $C
num $D "thin pages" -c 'under 100 tokens' '.[0].docs.total.pages_under_100_tokens as $t | ($t | length), ([$t[] | select(contains("/docs/fusion/"))] | length)' $C
num $D "release-note pages" -c 'docs/release' '.[0].docs.by_section.release.pages' $C
num $D "blog tokens" '.[0].blog.total.tokens' $C
num $D "Fusion pages" -c 'fusion' '.[0].fusion_pages | .pages, .stubs, .content_tokens' $C
num $D "corpus v2 Tier A repos" '.[0].repos.total | .files, .tokens' $C
num $D "release notes indexed" '.[0].releases.total | .releases, .tokens' $C
num $D "core index (combined_core_index)" '.[0].combined_core_index | .documents, .tokens' $C
num $D "repo table" '.[0].repos.per_repo[] | .tracked_files' $C
[ -s "$C1" ] && num $D "corpus v1 allowlist (POC commit 20b4bac)" '.[0].repos.total | .files, .tokens' $C1
for repo in olake olake-ui olake-helm olake-fusion; do
  sha=$(jq -r --arg r "$repo" '.repos.per_repo[$r].sha[0:7]' $C)
  if grep -q -- "$sha" "$TMP/norm.research.md"; then NUM_OK=$((NUM_OK + 1)); else fail "e: $RESEARCH does not quote the $repo SHA $sha from $C"; fi
done
for t in $(jq -r '.releases.per_repo[].newest' $C); do
  grep -q -- "$t" "$TMP/norm.research.md" || fail "e: $RESEARCH does not quote the newest release $t from $C"
done

# chunks.json (corpus v2)
num $D "chunks at 300" '.[0].configs[0] | .chunks, .by_source_type.docs.n, .by_source_type.repo.n, .by_source_type.release.n, .tokens.p50, .tokens.p95, .tokens.max' $K
num $D "chunks at 600" '.[0].configs[1] | .chunks, .by_source_type.docs.n, .by_source_type.repo.n, .by_source_type.release.n, .tokens.p50, .tokens.p95, .tokens.max' $K
num $D "chunks over hard max" -c 'over hard max' '.[0].configs[] | .over_hard_max' $K
num $D "blog-tier chunks" '.[0].configs[] | .blog_tier.chunks' $K

# retrieval.json (seed set, corpus v1)
num $D "seed retrieval table" '.[0].per_target["300"].configs as $c | ["bm25", "dense:BAAI/bge-small-en-v1.5", "dense:BAAI/bge-base-en-v1.5", "hybrid:BAAI/bge-small-en-v1.5", "hybrid:BAAI/bge-base-en-v1.5", "hybrid:BAAI/bge-base-en-v1.5+rerank:Xenova/ms-marco-MiniLM-L-6-v2", "hybrid:BAAI/bge-base-en-v1.5+rerank:BAAI/bge-reranker-base", "bm25+rerank:Xenova/ms-marco-MiniLM-L-6-v2"][] as $k | $c[$k] | ."hit@1", ."hit@5", ."hit@10", ."mrr@10", .latency_ms.total_ms.p50' $R
num $D "WordPiece truncation (corpus v1)" '.[0].per_target | ."300".embedding["BAAI/bge-small-en-v1.5"].wordpiece_over_512, ."300".chunks, ."600".embedding["BAAI/bge-small-en-v1.5"].wordpiece_over_512, ."600".chunks' $R
num $D "full-corpus embedding" '.[0].per_target["300"].embedding | .["BAAI/bge-small-en-v1.5"].embed_full_corpus_s, .["BAAI/bge-base-en-v1.5"].embed_full_corpus_s, .["BAAI/bge-small-en-v1.5"].dim, .["BAAI/bge-base-en-v1.5"].dim' $R
num $D "bge-small speed ratio" -c 'faster' '.[0].per_target["300"].embedding | (.["BAAI/bge-base-en-v1.5"].embed_full_corpus_s / .["BAAI/bge-small-en-v1.5"].embed_full_corpus_s * 10 | round / 10)' $R

# latency_threads.json and embed_probe.json
num $D "2-thread latencies" '.[0].by_threads["2"] | .query_embed_bge_small_ms.p50, .query_embed_bge_base_ms.p50, ."rerank_ms-marco-MiniLM-L-6-v2_top10_ms".p50, ."rerank_ms-marco-MiniLM-L-6-v2_top20_ms".p50, ."rerank_ms-marco-MiniLM-L-6-v2_top20_trunc1000chars_ms".p50, ."rerank_bge-reranker-base_top10_ms".p50, ."rerank_bge-reranker-base_top20_ms".p50' $L
num $D "API memory" '.[0].api_rss_mb | .after_one_query, .after_scorer_run_concurrency_4' $E
if jq -e '.strict_csp_page | .widget_rendered == true and .ask_blocked == true and .violation.directive == "connect-src"' $E >/dev/null 2>&1 \
   && grep -qF 'connect-src' "$TMP/norm.research.md"; then NUM_OK=$((NUM_OK + 1))
else fail "e: strict-CSP probe: $E no longer shows the widget rendered and /ask blocked by connect-src"; fi

# answer.json (seed set, local model)
num $D "tokens per answer" '.[0].tokens_per_answer | .prompt_mean, .prompt_max, .completion_mean, .completion_max' $A
num $D "seed answer latencies" '.[0].latency_ms | .retrieval_ms.p50, .rerank_ms.p50' $A
num $D "think probe TTFT" '.[0].think_probe | .default.llm_ttft_ms, .reasoning_none.llm_ttft_ms' $A
num $D "answered source hit" -p '.[0].answered_source_hit_rate * 100' $A
num $D "seed gate" -c 'seed' '.[0].policy_a_gate | .threshold, .precision, .recall, .false_abstain_rate, .n_should_abstain, .n_should_answer' $A
num $D "model's own flag (seed)" -c 'model' '.[0].policy_b_model | .precision, .false_abstain_rate' $A

# gate-canonical.json (curated set, MiniLM-L6 rerank score)
num $D "rerank-score gate, curated set" '.[0].policy_a_gate | .threshold, .recall, .precision' $G
num $D "rerank-score gate rates" -p '.[0].policy_a_gate | .false_abstain_rate_answerable * 100, .false_abstain_rate * 100' $G
num $D "rerank-score gate at -0.891" -c 'recall|answerable' '.[0].per_question as $q | [$q[] | select(.must_abstain)] as $m | [$m[] | select(.top_score < -0.891)] as $c | [$q[] | select(.type == "answerable")] as $a | [$a[] | select(.top_score < -0.891)] as $fa | ($c | length), ($m | length), ($c | length) / ($m | length), ($fa | length), ($a | length)' $G
num $D "rerank-score gate at -0.891 (rate)" -p '.[0].per_question as $q | [$q[] | select(.type == "answerable")] as $a | ([$a[] | select(.top_score < -0.891)] | length) / ($a | length) * 100' $G
num $D "rerank score ranges" '.[0].by_type | .answerable.top_score_min, .answerable.top_score_max, .unanswerable.top_score_min, .unanswerable.top_score_max, ."out-of-scope".top_score_min, ."out-of-scope".top_score_max, .adversarial.top_score_min, .adversarial.top_score_max' $G
num $D "context hit rate" -p '.[0].context_hit_rate_top_passages * 100' $G
num $D "context hit count" -c 'context' '.[0].per_question | ([.[] | select(.context_hit == true)] | length), ([.[] | select(.context_hit != null)] | length)' $G
# Any "N% of [the] M rows" the doc gives for the context hit rate must use the rows that have expected sources.
den=$(jq '[.per_question[] | select(.context_hit != null)] | length' $G)
rate=$(jq -r '.context_hit_rate_top_passages * 1000 | round / 10' $G)
for d in $(grep -oE "$rate% of (the )?[0-9]+ rows" "$TMP/norm.research.md" | grep -oE '[0-9]+ rows' | grep -oE '[0-9]+'); do
  [ "$d" = "$den" ] || fail "e: $RESEARCH says '$rate% of $d rows'; $G computes it over the $den rows with expected sources"
done

# retrieval-canonical.json (82 rows, corpus v1) and the bge-reranker-base log transcription
num $D "canonical retrieval" '.[0].per_target["300"].configs as $c | (["bm25", "dense:BAAI/bge-small-en-v1.5", "dense:BAAI/bge-base-en-v1.5", "hybrid:BAAI/bge-small-en-v1.5", "hybrid:BAAI/bge-base-en-v1.5", "hybrid:BAAI/bge-small-en-v1.5+rerank:Xenova/ms-marco-MiniLM-L-6-v2", "hybrid:BAAI/bge-base-en-v1.5+rerank:Xenova/ms-marco-MiniLM-L-6-v2", "bm25+rerank:Xenova/ms-marco-MiniLM-L-6-v2"][] as $k | $c[$k] | ."mrr@10", ."hit@5")' $RC
num $D "canonical retrieval, other ranks" '.[0].per_target["300"].configs as $c | (["hybrid:BAAI/bge-small-en-v1.5", "hybrid:BAAI/bge-base-en-v1.5", "hybrid:BAAI/bge-small-en-v1.5+rerank:Xenova/ms-marco-MiniLM-L-6-v2", "bm25"][] as $k | $c[$k] | ."hit@1", ."hit@3", ."hit@10")' $RC
num $D "canonical retrieval at 600" -c '600' '.[0].per_target["600"].configs["hybrid:BAAI/bge-small-en-v1.5"]."mrr@10"' $RC
num $D "bge-reranker-base (log transcription)" '.[0].configs[] | ."mrr@10", ."hit@1", ."hit@3", ."hit@5", ."hit@10"' $RB

# retrieval-v2.json (82 rows, corpus v2): rerankers, blog tier, categories, rank movements
num $D "corpus v2 rerank table" '.[0].per_target["300"].configs | to_entries[] | select(.key | startswith("hybrid:")) | .value | ."mrr@10", ."hit@1", ."hit@3", ."hit@5", ."hit@10", (.latency_ms.rerank_ms.p50 // empty)' $V
num $D "corpus v2 blog tier" '.[0].per_target["300"].blog_tier.configs[] | ."mrr@10", ."hit@1", ."hit@3", ."hit@5", ."hit@10"' $V
num $D "corpus v2 by category" '.[0].per_target["300"].configs as $c | (["hybrid:BAAI/bge-small-en-v1.5", "hybrid:BAAI/bge-small-en-v1.5+rerank:flashrank:ms-marco-TinyBERT-L-2-v2@20"][] as $k | $c[$k].by_category[] | ."mrr@10", ."hit@10")' $V
num $D "TinyBERT rank-1 rows" -c 'rank 1' '.[0].per_target["300"].configs as $c | $c["hybrid:BAAI/bge-small-en-v1.5"].first_hit_rank as $a | $c["hybrid:BAAI/bge-small-en-v1.5+rerank:flashrank:ms-marco-TinyBERT-L-2-v2@20"].first_hit_rank as $b | ([$b[] | select(. == 1)] | length), ([$a[] | select(. == 1)] | length), ([$b | to_entries[] | select(.value == 1 and $a[.key] != 1)] | length), ([$a | to_entries[] | select(.value == 1 and $b[.key] != 1)] | length)' $V
num $D "rank moves (SRC-09, DST-06, SYNC-12, TRB-02, FUS-04, REL-01, FUS-07)" -c 'rank' '.[0].per_target["300"].configs as $c | $c["hybrid:BAAI/bge-small-en-v1.5"].first_hit_rank as $a | $c["hybrid:BAAI/bge-small-en-v1.5+rerank:flashrank:ms-marco-TinyBERT-L-2-v2@20"].first_hit_rank as $b | $a["SRC-09"], $a["DST-06"], $b["SYNC-12"], $b["TRB-02"], $a["FUS-04"], $a["REL-01"], $a["FUS-07"], .[1].per_target["300"].configs["hybrid:BAAI/bge-small-en-v1.5"].first_hit_rank["REL-01"], .[1].per_target["300"].configs["hybrid:BAAI/bge-small-en-v1.5"].first_hit_rank["FUS-07"]' $V $RC

# gate-signals.json and gate-rewrite.json (corpus v2 dense gate, rewrite sweep)
num $D "gate signals at 0 false abstains" '.[0].signals | .dense_max_cos.zero_false_abstain.threshold, .dense_max_cos.zero_false_abstain.recall, ."tinybert_top@10".zero_false_abstain.recall, ."minilm_top@10".zero_false_abstain.recall' $GS
num $D "gate catches (rows)" -c 'caught|abstain' '.[0].signals | (.dense_max_cos, ."tinybert_top@10", ."minilm_top@10") | .zero_false_abstain.abstained_ids | length' $GS
num $D "near-domain dense scores" '.[0].signals.dense_max_cos | (.highest_must_abstain[] | .[1]), (.lowest_must_answer[0:2][] | .[1])' $GS
num $D "dense gate at 0.69 and 0.71" '.[0].sweep.dense_max_cos[] | select(.threshold == 0.69 or .threshold == 0.71) | .threshold, .gate_only_recall, (if .threshold == 0.71 then .abstain_recall else empty end)' $GR
num $D "margin rows (OOS-05, UNK-04)" '.[0].per_question[] | select(.id == "OOS-05" or .id == "UNK-04") | .score.dense_max_cos, (if .id == "UNK-04" then .score_after_rewrite.dense_max_cos else empty end)' $GR
num $D "rewrite cost" '.[0].rewrite_cost | .latency_ms_p50, .latency_ms_p95, .prompt_tokens_mean, .completion_tokens_mean' $GR

# eval_run-canonical.json and the prompt v2 subset
num $D "end-to-end summary" '.[0].summary | .behaviour_correct, .source_hit, .fact_coverage_mean, .judged_behavior_pass, .abstain_recall_unanswerable_out_of_scope, .false_abstain_rate_answerable, .total_wall_s' $EC
num $D "end-to-end p50" -c '/ask' '.[0].summary.latency_ms.p50 / 1000' $EC
num $D "false-abstain breakdown" -c 'abstain|gate|model' '.[0].abstain_breakdown | .false_abstains_all_must_answer_rows | .n, .of, .by_trigger.gate, .by_trigger.model_answerable_false, .by_trigger.scorer_abstain_pattern_on_sourced_answer' $EC
num $D "false abstains on answerable rows" -c 'answerable' '.[0].abstain_breakdown.false_abstains_answerable_rows | .n, .of, .by_trigger.gate, .by_trigger.model_answerable_false' $EC
num $D "weakest types" -c 'false-premise|negative|adversarial' '.[0].by_type | (."false-premise", .negative, .adversarial) | (.behaviour_correct * .n | round), .n' $EC
num $D "prompt v2 subset" -c 'v2|behaviour|35' '([.[1].per_question[] | .id]) as $ids | ([.[0].per_question[] | select(.id as $i | $ids | index($i)) | select(.behaviour_correct == true)] | length), ([.[1].per_question[] | select(.behaviour_correct == true)] | length), (.[1].per_question | length), ([.[0].per_question[] | select(.id as $i | $ids | index($i)) | .judge.coverage // empty] | add / length), ([.[1].per_question[] | .judge.coverage // empty] | add / length)' $EC $E2

# eval_run-canonical-combined.json (round-2 end-to-end run: prompt v3, k=10, TinyBERT gate with one rewrite)
EC3=$RES/eval_run-canonical-combined.json
if [ -s "$EC3" ]; then
  num $D "round-2 summary" '.[0].summary | .behaviour_correct, .source_hit, .fact_coverage_mean, .judged_behavior_pass, .abstain_recall_unanswerable_out_of_scope, .false_abstain_rate_answerable, .false_abstain_rate_all_must_answer' $EC3
  num $D "round-2 latency (s)" -c 'p50|p95|latency' '.[0].summary.latency_ms | .p50 / 1000, .p95 / 1000' $EC3
  num $D "round-2 tokens (rows that called the LLM)" 'def p50: sort | if length % 2 == 1 then .[length / 2 | floor] else (.[length / 2 - 1] + .[length / 2]) / 2 end; [.[0].per_question[] | .server.debug | select(. != null) | fromjson | .usage | select(. != null and .prompt_tokens > 0)] as $u | ($u | map(.prompt_tokens)) as $p | ($u | map(.completion_tokens)) as $c | ($u | length), ($p | add / length), ($p | p50), ($p | max), ($c | add / length), ($c | p50), ($c | max)' $EC3
  num $D "round-2 behaviour by type" -c 'type|answerable|adversarial|unanswerable' '.[0].by_type | .answerable.behaviour_correct, .adversarial.behaviour_correct, .unanswerable.behaviour_correct' $EC3
  num $D "round-2 abstain sources" -c 'rewrite|model|unparseable|abstain' '.[0].summary.server_reasons | .gate_after_rewrite, .model_unanswerable, .unparseable' $EC3
  num $D "round-2 false and missed abstains" -c 'abstain|must-answer|answerable' '.[0].abstain_breakdown | .false_abstains_all_must_answer_rows.n, .false_abstains_all_must_answer_rows.of, .missed_abstains.n, .missed_abstains.of' $EC3
  num $D "round-2 rewrites" -c 'rewrite' '.[0].summary.rewrite_fired' $EC3
  num $PLAN "plan: round-2 numbers" '.[0] | .by_type.answerable.source_hit, .summary.false_abstain_rate_answerable, .summary.abstain_recall_unanswerable_out_of_scope' $EC3
fi

# gate-rewrite-v2-subset.json (the hardened rewrite prompt on the gate-fired and adversarial rows)
GV2=$RES/gate-rewrite-v2-subset.json
if [ -s "$GV2" ]; then
  num $D "hardened rewrite subset size" -c 'gate-fired|hardened' '.[0].per_question | length' $GV2
fi

# freshness.json
num $D "freshness probes" -c 'ms|per hour' '.[0] | .docs_page.if_none_match.ms, ([.git_ls_remote[].ms] | min), ([.git_ls_remote[].ms] | max), .github_unauthenticated.rate_before.limit, .github_authenticated.rate_before.limit' $F
num $D "lastmod redesign commit" -c 'redesign' '.[0].observations | .docs_pages_by_sitemap_lastmod["2026-10-06"], (.docs_pages_by_http_last_modified | add)' $F

# plan.md and the other docs quote a few of the same numbers
num $PLAN "plan: denylist arithmetic" -c 'denylist|108' '.[0].docs.total.pages, .[0].docs.total.pages - 16' $C
num $PLAN "plan: embedding times" -c 'embed' '.[0].per_target["300"].embedding | .["BAAI/bge-small-en-v1.5"].embed_full_corpus_s, .["BAAI/bge-base-en-v1.5"].embed_full_corpus_s' $R
num $PLAN "plan: dense gate" -c 'threshold|gate' '.[0].signals.dense_max_cos.zero_false_abstain.threshold' $GS

[ "$NUM_OK" -gt 0 ] && pass "e: $NUM_OK number checks ($NUM_VALS numbers) agree between the docs and $RES/*.json"

# ---------------------------------------------------------------------------------------------------------
printf '\n== Summary: %d PASS, %d WARN, %d FAIL\n' "$NPASS" "$NWARN" "$NFAIL"
[ "$NFAIL" -eq 0 ]
