"""Capability 'md-html': markdown -> html (render).

Minimal stdlib subset: #..###### headings, paragraphs, -/* and 1. lists,
``` fenced code, `inline code`, **bold**, *italic*, [text](url).
Everything else renders as escaped text — no raw HTML passthrough, no
javascript: links (XSS boundary).
"""
from __future__ import annotations

import html
import re
from typing import Any, Mapping


def _inline(s: str) -> str:
    s = html.escape(s)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", s)
    s = re.sub(
        r"\[([^\]]+)\]\(([^)]+)\)",
        lambda m: (
            f'<a href="{html.escape(m[2], quote=True)}">{m[1]}</a>'
            if re.match(r"(?i)^(https?://|mailto:|/|\./|#|[^:]*$)", m[2])
               and "javascript:" not in m[2].lower()
            else m[1]
        ),
        s,
    )
    return s


def render_md(text: str) -> str:
    out: list[str] = []
    in_code = False
    in_list: str | None = None
    para: list[str] = []

    def flush_para() -> None:
        if para:
            out.append(f"<p>{_inline(' '.join(para))}</p>")
            para.clear()

    def flush_list() -> None:
        nonlocal in_list
        if in_list:
            out.append(f"</{in_list}>")
            in_list = None

    for line in text.splitlines():
        if line.strip().startswith("```"):
            flush_para(); flush_list()
            if in_code:
                out.append("</code></pre>")
                in_code = False
            else:
                out.append("<pre><code>")
                in_code = True
            continue
        if in_code:
            out.append(html.escape(line) + "\n")
            continue
        s = line.strip()
        if not s:
            flush_para(); flush_list()
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", s)
        if m:
            flush_para(); flush_list()
            out.append(f"<h{len(m[1])}>{_inline(m[2])}</h{len(m[1])}>")
            continue
        m = re.match(r"^[-*]\s+(.*)$", s)
        if m:
            flush_para()
            if in_list != "ul":
                flush_list(); out.append("<ul>"); in_list = "ul"
            out.append(f"<li>{_inline(m[1])}</li>")
            continue
        m = re.match(r"^\d+[.)]\s+(.*)$", s)
        if m:
            flush_para()
            if in_list != "ol":
                flush_list(); out.append("<ol>"); in_list = "ol"
            out.append(f"<li>{_inline(m[1])}</li>")
            continue
        flush_list()
        para.append(s)
    flush_para(); flush_list()
    if in_code:
        out.append("</code></pre>")
    return "".join(out)


class MarkdownHtml:
    id = "md-html"
    in_kind = "markdown"
    out_kind = "html"
    mode = "render"

    def run(self, value: Any, ctx: Mapping[str, Any]) -> str:
        return render_md(str(value))
