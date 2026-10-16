"""Convert an OLake connector spec.json (JSON Schema behind the UI form) to a Markdown field table.

Nested objects become dotted paths (`ssl.mode`), `oneOf` variants are labelled with the
variant title (`update_method.publication` [CDC]) and `allOf` if/then blocks with their
condition (`ssl.server_ca` [when mode = verify-ca]). These descriptions are the help texts
the OLake UI shows next to each field.
"""

from __future__ import annotations

import json


def _fmt(v) -> str:
    if v is None:
        return ""
    if isinstance(v, str):
        return f"`{v}`" if v else '`""`'
    return f"`{json.dumps(v)}`"


def _cell(s: str) -> str:
    return " ".join(str(s).split()).replace("|", "\\|")


def _limits(p: dict) -> str:
    parts = []
    if p.get("enum"):
        parts.append(", ".join(str(x) for x in p["enum"]))
    for k, label in (("minimum", "min"), ("maximum", "max"), ("minLength", "min length"), ("pattern", "pattern")):
        if k in p:
            parts.append(f"{label} {p[k]}")
    if "const" in p:
        parts.append(f"const {p['const']}")
    return "; ".join(parts)


def _type(p: dict) -> str:
    t = p.get("type")
    if isinstance(t, list):
        t = "/".join(t)
    if t == "array" and isinstance(p.get("items"), dict) and p["items"].get("type"):
        return f"array of {p['items']['type']}"
    if not t and p.get("oneOf"):
        return "one of: " + ", ".join(o.get("title", "?") for o in p["oneOf"])
    return t or ""


def _has_children(p: dict) -> bool:
    return any(p.get(k) for k in ("properties", "oneOf", "allOf", "dependencies"))


def _discriminator(variant: dict) -> str:
    for k, v in (variant.get("properties") or {}).items():
        if isinstance(v, dict) and "const" in v:
            return f"{k} = {v['const']}"
    return variant.get("title", "variant")


def walk(node: dict, prefix: str = "", tag: str = "", out: list | None = None) -> list[tuple]:
    """Rows (path, tag, title, type, required, default, limits, description) for one schema node:
    its properties (recursively), then its oneOf variants, allOf if/then blocks and dependencies."""
    out = [] if out is None else out
    required = set(node.get("required") or [])
    for name, p in (node.get("properties") or {}).items():
        if not isinstance(p, dict) or set(p) <= {"const"}:  # discriminators like "type": {"const": "CDC"}
            continue
        path = f"{prefix}{name}"
        out.append((path, tag, p.get("title", ""), _type(p), "yes" if name in required else "",
                    _fmt(p.get("default")) if "default" in p else "", _limits(p), p.get("description", "")))
        if _has_children(p):
            walk(p, path + ".", tag, out)
    for variant in node.get("oneOf") or []:
        if isinstance(variant, dict) and variant.get("properties"):
            walk(variant, prefix, variant.get("title") or _discriminator(variant), out)
    for cond in node.get("allOf") or []:
        if not isinstance(cond, dict):
            continue
        then = cond.get("then")
        when = (cond.get("if") or {}).get("properties", {})
        if then and _has_children(then):
            label = ", ".join(f"{k} = {v.get('const')}" for k, v in when.items() if isinstance(v, dict))
            walk(then, prefix, f"when {label}" if label else "conditional", out)
    for dep in (node.get("dependencies") or {}).values():
        if isinstance(dep, dict):
            for variant in dep.get("oneOf") or []:
                if isinstance(variant, dict) and variant.get("properties"):
                    walk(variant, prefix, _discriminator(variant), out)
    return out


def spec_to_markdown(text: str, title: str) -> str:
    spec = json.loads(text)
    root = spec.get("spec", spec) if isinstance(spec, dict) else {}
    rows = walk(root)
    lines = [f"# {title}", "",
             "Each row is a configuration field, as shown in the OLake UI form, with its help text.", "",
             "| Field | Title | Type | Required | Default | Allowed values / limits | Description |",
             "|---|---|---|---|---|---|---|"]
    seen = set()
    for path, tag, t, typ, req, default, limits, desc in rows:
        key = (path, tag)
        if key in seen:  # verify-ca and verify-full repeat the same conditional fields
            continue
        seen.add(key)
        field = f"`{path}`" + (f" [{tag}]" if tag else "")
        lines.append("| " + " | ".join(_cell(x) for x in (field, t, typ, req, default, limits, desc)) + " |")
    return "\n".join(lines) + "\n"
