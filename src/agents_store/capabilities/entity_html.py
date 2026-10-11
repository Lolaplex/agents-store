"""Capability 'entity-html': entity -> html card (render).

Input value: {"id": str, "view": {attr: val}, "kinds": [..],
              "derived": {attr: rule}, "lineage": [(child,parent,kind)]}
(id and view required; the rest optional). Derived values are rendered
marked, never as real attrs.
"""
from __future__ import annotations

import html
from typing import Any, Mapping


def render_entity(payload: Mapping[str, Any]) -> str:
    e = html.escape(str(payload.get("id", "?")))
    view = dict(payload.get("view") or {})
    kinds = payload.get("kinds") or []
    derived = payload.get("derived") or {}
    lineage = payload.get("lineage") or []
    title = html.escape(str(view.pop("title", e)))

    badges = "".join(f'<span class="kind">{html.escape(str(k))}</span> ' for k in kinds)
    rows = []
    for a in sorted(view):
        mark = ' <em class="derived">(derived)</em>' if a in derived else ""
        v = view[a]
        v = ", ".join(map(str, v)) if isinstance(v, (list, tuple)) else v
        rows.append(f"<tr><th>{html.escape(a)}</th><td>{html.escape(str(v))}{mark}</td></tr>")
    for a, rule in derived.items():
        if a not in view:
            rows.append(
                f'<tr><th>{html.escape(a)}</th><td><em class="derived">(derived via {html.escape(str(rule))})</em></td></tr>'
            )
    edges = "".join(
        f"<li>{html.escape(str(k))}: {html.escape(str(p))} → {html.escape(str(c))}</li>"
        for c, p, k in lineage
    )
    return (
        f'<article class="entity" data-id="{e}">'
        f"<h2>{title}</h2>{badges}"
        f'<div class="eid"><code>{e}</code></div>'
        f"<table>{''.join(rows)}</table>"
        f"{('<ul class=lineage>' + edges + '</ul>') if edges else ''}"
        f"</article>"
    )


class EntityHtml:
    id = "entity-html"
    in_kind = "entity"
    out_kind = "html"
    mode = "render"

    def run(self, value: Any, ctx: Mapping[str, Any]) -> str:
        return render_entity(value)
