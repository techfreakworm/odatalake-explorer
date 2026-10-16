// Markdown renderer: model text only ever becomes text nodes; markup comes from a fixed allow-list.
// Run: node --test tests/web/
import { test } from "node:test";
import assert from "node:assert/strict";
import { parseMarkdown, toHTML, safeUrl } from "../../web/embed-core.mjs";

const html = (md, opts) => toHTML(parseMarkdown(md, opts));
const TAGS = new Set(["p", "h3", "h4", "h5", "h6", "ul", "ol", "li", "pre", "code", "strong", "em", "a", "table",
  "thead", "tbody", "tr", "th", "td", "blockquote", "hr", "br", "del"]);
const ATTRS = new Set(["href", "title", "target", "rel", "class", "data-n", "start"]);

function assertOnlyAllowedMarkup(out) {
  for (const m of out.matchAll(/<\/?([a-zA-Z0-9-]+)([^>]*)>/g)) {
    assert.ok(TAGS.has(m[1]), `unexpected tag <${m[1]}> in ${out}`);
    for (const a of m[2].matchAll(/\s([^\s=]+)="[^"]*"/g)) assert.ok(ATTRS.has(a[1]), `unexpected attribute ${a[1]}`);
    assert.equal(m[2].replace(/\s[^\s=]+="[^"]*"/g, "").trim(), "", `stray attribute text in ${m[0]}`);
  }
}

test("raw HTML is text: <img onerror>", () => {
  const out = html("Look: <img src=x onerror=alert(1)> done");
  assert.ok(!out.includes("<img"));
  assert.ok(out.includes("&lt;img src=x onerror=alert(1)&gt;"));
  assertOnlyAllowedMarkup(out);
});

test("javascript: and other non-https links never become links", () => {
  for (const md of ["[click](javascript:alert(1))", "[click](JAVASCRIPT:alert(1))", "[click](  javascript:alert(1) )",
                    "[click](data:text/html,<script>alert(1)</script>)", "[click](http://example.com)",
                    "<javascript:alert(1)>", "[click](//evil.example/x)", "[click](vbscript:msgbox)"]) {
    const out = html(md);
    assert.ok(!out.includes("<a"), `${md} -> ${out}`);
    assert.ok(!/href="(?!https:)/.test(out));
    assertOnlyAllowedMarkup(out);
  }
  assert.equal(safeUrl("java\tscript:alert(1)"), null);
  assert.equal(safeUrl(" https://olake.io/docs/ "), "https://olake.io/docs/");
});

test("a <script> inside a code fence stays text", () => {
  const out = html("Example:\n\n```html\n<script>alert(1)</script>\n```");
  assert.ok(!out.includes("<script"));
  assert.ok(out.includes('<pre><code class="language-html">&lt;script&gt;alert(1)&lt;/script&gt;</code></pre>'));
});

test("attribute injection through a link title or URL is inert", () => {
  for (const md of ['[x](https://example.com "a\\" onmouseover=\\"alert(1)")',
                    '[x](https://example.com "t" onmouseover="alert(1)")',
                    '[x](https://example.com/" onmouseover="alert(1))',
                    "[x](https://example.com/'onmouseover='alert(1))"]) {
    const out = html(md);
    for (const tag of out.match(/<[^>]*>/g) || []) {
      assert.ok(!/onmouseover/i.test(tag.replace(/="[^"]*"/g, '=""')), `${md} -> ${tag}`);  // text content is fine
    }
    assertOnlyAllowedMarkup(out);
  }
});

test("https links open in a new tab without opener", () => {
  const out = html("See [the REST page](https://olake.io/docs/writers/iceberg/catalog/rest/) and https://olake.io/slack/.");
  assert.ok(out.includes('<a href="https://olake.io/docs/writers/iceberg/catalog/rest/" target="_blank" rel="noopener noreferrer">the REST page</a>'));
  assert.ok(out.includes('<a href="https://olake.io/slack/" target="_blank" rel="noopener noreferrer">https://olake.io/slack/</a>.'));
});

test("emphasis, inline code, headings, rules and quotes", () => {
  assert.equal(html("**bold** and *it* and `x < y`"),
    "<p><strong>bold</strong> and <em>it</em> and <code>x &lt; y</code></p>");
  assert.equal(html("# Big\n## Smaller"), "<h3>Big</h3><h4>Smaller</h4>");
  assert.equal(html("a\n\n---\n\nb"), "<p>a</p><hr><p>b</p>");
  assert.equal(html("> quoted **text**"), "<blockquote><p>quoted <strong>text</strong></p></blockquote>");
  assert.equal(html("line one\nline two"), "<p>line one<br>line two</p>");
});

test("snake_case and file paths are not emphasis", () => {
  const out = html("Set initial_wait_time and max_threads in /etc/olake/*.json or *.yaml files");
  assert.ok(!out.includes("<em>"), out);
});

test("lists, nested lists and code under list items", () => {
  assert.equal(html("- one\n- two\n  - nested\n- three"),
    "<ul><li>one</li><li>two<ul><li>nested</li></ul></li><li>three</li></ul>");
  assert.equal(html("3. third\n4. fourth"), '<ol start="3"><li>third</li><li>fourth</li></ol>');
  const out = html("1. Install:\n   ```bash\n   helm install olake olake/olake\n   ```\n2. Open the UI");
  assert.equal(out, '<ol><li>Install:<pre><code class="language-bash">helm install olake olake/olake</code></pre></li>' +
    "<li>Open the UI</li></ol>");
});

test("tables with alignment and escaped pipes", () => {
  const out = html("| Source | CDC |\n|:---|:---:|\n| Postgres | yes |\n| a \\| b | `no` |");
  assert.equal(out, "<table><thead><tr><th>Source</th><th class=\"al-c\">CDC</th></tr></thead><tbody>" +
    "<tr><td>Postgres</td><td class=\"al-c\">yes</td></tr><tr><td>a | b</td><td class=\"al-c\"><code>no</code></td></tr>" +
    "</tbody></table>");
});

test("code blocks keep whitespace exactly, an unclosed fence (mid-stream) still renders as code", () => {
  const yaml = "x-envs:\n  shared: &sharedEnvs\n    TELEMETRY_DISABLED: \"true\"";
  assert.ok(html("```yaml\n" + yaml + "\n```").includes("<code class=\"language-yaml\">" +
    "x-envs:\n  shared: &amp;sharedEnvs\n    TELEMETRY_DISABLED: &quot;true&quot;</code>"));
  assert.equal(html("Run:\n\n```bash\ndocker compose up"), '<p>Run:</p><pre><code class="language-bash">docker compose up</code></pre>');
});

test("citation markers link only when a matching citation exists, never inside code", () => {
  const out = html("Use REST [1][2]. Not [3]. `arr[1]`", { cites: 2 });
  assert.ok(out.includes('<a href="#cite-1" class="cite" data-n="1">1</a><a href="#cite-2" class="cite" data-n="2">2</a>'));
  assert.ok(out.includes("Not [3]."));
  assert.ok(out.includes("<code>arr[1]</code>"));
  assert.ok(!html("Use REST [1].").includes("cite"), "no citations while streaming");
});

test("language names on fences are sanitised", () => {
  const out = html('```js" onload="x\nconsole.log(1)\n```');
  assertOnlyAllowedMarkup(out);
  assert.ok(!out.includes("onload"));
});
