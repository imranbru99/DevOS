#!/usr/bin/env python3
"""Tiny Markdown -> Qt rich-text HTML (bold, italic, code, lists, headings, links)."""

import html
import re

CODE_BG = "#0d1117"
INLINE_CODE_BG = "#1a2130"
LINK = "#7dd3fc"

_URL = re.compile(r"(?<![\"'=(])\bhttps?://[^\s<>()]+[^\s<>().,;:!?'\"]")


def _inline(text: str, link_color: str = LINK) -> str:
    codes = []

    def keep_code(m):
        codes.append(m.group(1))
        return f"\x00{len(codes) - 1}\x00"

    text = re.sub(r"`([^`\n]+)`", keep_code, text)
    links = []

    def keep_link(m):
        links.append((m.group(1), m.group(2)))
        return f"\x01{len(links) - 1}\x01"

    text = re.sub(r"\[([^\]\n]+)\]\((https?://[^)\s]+)\)", keep_link, text)
    text = html.escape(text, quote=False)
    text = _URL.sub(lambda m: f'<a href="{m.group(0)}" style="color:{link_color}; text-decoration:none;">{m.group(0)}</a>', text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"__(.+?)__", r"<b>\1</b>", text)
    text = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<i>\1</i>", text)
    text = re.sub(r"(?<![\w_])_(?!\s)(.+?)(?<!\s)_(?![\w_])", r"<i>\1</i>", text)

    def put_link(m):
        label, url = links[int(m.group(1))]
        return f'<a href="{html.escape(url)}" style="color:{link_color}; text-decoration:none;">{html.escape(label)}</a>'

    text = re.sub(r"\x01(\d+)\x01", put_link, text)

    def put_code(m):
        c = html.escape(codes[int(m.group(1))], quote=False)
        return (f'<code style="background-color:{INLINE_CODE_BG}; color:#e2e8f0; font-size:13px; '
                f'font-family:\'JetBrains Mono\',\'Noto Sans Mono\',monospace;">&nbsp;{c}&nbsp;</code>')

    return re.sub(r"\x00(\d+)\x00", put_code, text)


def _code_html(code: str) -> str:
    code = html.escape(code, quote=False)
    return (f"<table width='100%' cellspacing='0' cellpadding='10' style='margin:2px 0 4px 0;'>"
            f"<tr><td style='background-color:{CODE_BG};'><pre style=\"margin:0; white-space:pre-wrap; "
            f"font-family:'JetBrains Mono','Noto Sans Mono',monospace; font-size:13px;\">{code}</pre>"
            f"</td></tr></table>")


def split_blocks(md: str):
    """Split Markdown into [("text", markdown) | ("code", language, code)] so the
    window can show fenced code as separate cards with a Copy button."""
    lines = (md or "").replace("\r\n", "\n").split("\n")
    out = []
    buf = []
    i = 0
    while i < len(lines):
        s = lines[i].strip()
        if s.startswith("```"):
            if any(x.strip() for x in buf):
                out.append(("text", "\n".join(buf).strip("\n")))
            buf = []
            lang = s[3:].strip().split(" ")[0][:20]
            i += 1
            block = []
            while i < len(lines) and not lines[i].strip().startswith("```"):
                block.append(lines[i])
                i += 1
            i += 1
            out.append(("code", lang, "\n".join(block)))
            continue
        buf.append(lines[i])
        i += 1
    if any(x.strip() for x in buf):
        out.append(("text", "\n".join(buf).strip("\n")))
    return out


def to_html(md: str, link_color: str = LINK, line_height: int = 0, gap: int = 8) -> str:
    """line_height: percent (e.g. 155) or 0 for the default; gap: px between blocks."""
    lines = (md or "").replace("\r\n", "\n").split("\n")
    out = []
    i = 0
    list_kind = None
    para = []
    lh = f" line-height:{line_height}%;" if line_height else ""
    end = f"margin:0 0 {gap}px 0;"

    def flush_para():
        if para:
            out.append(f"<p style='{end}{lh}'>" + "<br>".join(_inline(p, link_color) for p in para) + "</p>")
            para.clear()

    def close_list():
        nonlocal list_kind
        if list_kind:
            out.append(f"</{list_kind}>")
            list_kind = None

    while i < len(lines):
        line = lines[i]
        if line.strip().startswith("```"):
            flush_para()
            close_list()
            i += 1
            block = []
            while i < len(lines) and not lines[i].strip().startswith("```"):
                block.append(lines[i])
                i += 1
            i += 1
            out.append(_code_html("\n".join(block)))
            continue
        m_h = re.match(r"^(#{1,4})\s+(.*)$", line)
        m_ul = re.match(r"^\s*[-*•]\s+(.*)$", line)
        m_ol = re.match(r"^\s*(\d+)[.)]\s+(.*)$", line)
        if m_h:
            flush_para()
            close_list()
            size = {1: 17, 2: 17, 3: 15, 4: 15}[len(m_h.group(1))]
            out.append(f"<p style='margin:{gap // 2}px 0 {max(4, gap - 2)}px 0; font-size:{size}px; font-weight:600;{lh}'>"
                       f"{_inline(m_h.group(2), link_color)}</p>")
        elif m_ul or m_ol:
            flush_para()
            kind = "ul" if m_ul else "ol"
            if list_kind != kind:
                close_list()
                out.append(f"<{kind} style='{end} -qt-list-indent:1;'>")
                list_kind = kind
            item = m_ul.group(1) if m_ul else m_ol.group(2)
            out.append(f"<li style='margin-bottom:{max(3, gap // 3)}px;'>{_inline(item, link_color)}</li>")
        elif not line.strip():
            flush_para()
            close_list()
        else:
            if list_kind and line.startswith("  "):
                out[-1] = out[-1][:-5] + "<br>" + _inline(line.strip(), link_color) + "</li>"
            else:
                close_list()
                para.append(line)
        i += 1
    flush_para()
    close_list()
    html_out = "".join(out)
    # no trailing bottom margin on the last block
    tail = re.escape(end)
    return re.sub(tail + r"((?:(?!margin:0 0).)*)$", r"margin:0;\1", html_out, flags=re.S)
