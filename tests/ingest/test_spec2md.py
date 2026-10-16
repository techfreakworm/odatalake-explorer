from __future__ import annotations

from index.chunk import chunk_markdown, parse_markdown
from ingest.spec2md import spec_to_markdown


def test_spec_becomes_a_field_table(fixture_text):
    md = spec_to_markdown(fixture_text("spec.json"), "OLake postgres source connector")
    lines = md.split("\n")
    assert lines[0] == "# OLake postgres source connector"
    header = "| Field | Title | Type | Required | Default | Allowed values / limits | Description |"
    assert header in lines
    rows = {ln.split(" | ")[0].lstrip("| ").strip(): ln for ln in lines if ln.startswith("| `")}
    assert "| `host` | Host | string | yes |" in rows["`host`"]
    assert "`5432`" in rows["`port`"] and "min 1; max 65535" in rows["`port`"]
    assert "disable, require, verify-ca" in rows["`ssl.mode`"]
    # allOf if/then and oneOf variants are labelled with their condition / variant title
    assert "`ssl.server_ca` [when mode = verify-ca]" in rows
    assert "CA \\| PEM" in rows["`ssl.server_ca` [when mode = verify-ca]"]  # pipes escaped
    assert "`update_method.replication_slot` [CDC]" in rows
    assert not any("`update_method.type`" in r for r in rows)  # const discriminators are not fields


def test_spec_table_chunks_keep_their_header_row(fixture_text):
    md = spec_to_markdown(fixture_text("spec.json"), "Spec")
    blocks = parse_markdown(md)
    assert any(b.kind == "table" for b in blocks)
    for r in chunk_markdown(md, title="olake: drivers/postgres/resources/spec.json"):
        if "| `" in r.text:
            assert "| Field | Title | Type |" in r.text
