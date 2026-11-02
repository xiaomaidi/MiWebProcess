"""HTML 白名单清洗（发布校验 + 运行时兜底），不依赖 bleach。

前端 engine/sanitize.ts 使用同一套标签/属性白名单；服务端在发布时再做一次，
发现 script / 事件属性 / javascript: 协议时直接报错。
"""
from __future__ import annotations

import html as html_lib
import re
from html.parser import HTMLParser

ALLOWED_TAGS = {
    "a", "b", "strong", "i", "em", "u", "s", "del", "p", "br", "hr", "ul", "ol", "li",
    "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre", "code", "span", "div",
    "table", "thead", "tbody", "tfoot", "tr", "td", "th", "caption", "colgroup", "col",
    "img", "figure", "figcaption", "video", "audio", "source", "small", "sub", "sup", "mark",
}
ALLOWED_ATTRS = {
    "class", "style", "href", "src", "alt", "title", "width", "height", "target", "rel",
    "colspan", "rowspan", "controls", "poster", "muted", "loop", "autoplay", "preload",
    "loading", "role", "aria-label", "aria-hidden",
}
SVG_TAGS = {
    "svg", "g", "path", "rect", "circle", "ellipse", "line", "polyline", "polygon", "text",
    "tspan", "defs", "lineargradient", "radialgradient", "stop", "clippath", "mask", "use",
    "symbol", "marker", "pattern", "filter", "fegaussianblur", "fecolormatrix", "title", "desc",
}
SVG_ATTRS = {
    "viewbox", "width", "height", "fill", "stroke", "stroke-width", "stroke-linecap",
    "stroke-linejoin", "d", "cx", "cy", "r", "rx", "ry", "x", "x1", "x2", "y", "y1", "y2",
    "points", "transform", "opacity", "fill-opacity", "stroke-opacity", "stop-color",
    "stop-opacity", "offset", "gradientunits", "gradienttransform", "id", "class", "style",
    "preserveaspectratio", "xmlns", "clip-path", "mask", "href", "xlink:href",
}
DANGEROUS_RE = re.compile(
    r"<\s*(script|style|iframe|object|embed|form)\b|on[a-z]+\s*=|javascript\s*:|vbscript\s*:|data\s*:\s*text/html",
    re.IGNORECASE,
)


def _safe_url(value: str, image: bool = False) -> str | None:
    v = (value or "").strip()
    if not v:
        return ""
    low = v.lower()
    if v.startswith("#") or v.startswith("/") or v.startswith("./") or v.startswith("../"):
        return v
    if low.startswith("http://") or low.startswith("https://") or low.startswith("mailto:") or low.startswith("tel:"):
        return v
    if image and low.startswith("data:image/"):
        return v
    return None


class _Sanitizer(HTMLParser):
    def __init__(self, allow_svg: bool = False):
        super().__init__(convert_charrefs=False)
        self.allow_svg = allow_svg
        self.tags = SVG_TAGS if allow_svg else ALLOWED_TAGS
        self.attrs = SVG_ATTRS if allow_svg else ALLOWED_ATTRS
        self.out: list[str] = []
        self.stack: list[str] = []

    def handle_starttag(self, tag: str, attrs):
        tag = tag.lower()
        if tag not in self.tags:
            return
        parts = [tag]
        for name, value in attrs:
            name = name.lower()
            if name.startswith("on") or name not in self.attrs:
                continue
            if name in ("href", "src", "xlink:href"):
                safe = _safe_url(value or "", image=(tag in ("img", "source")))
                if safe is None:
                    continue
                value = safe
            if name == "style" and re.search(r"expression\s*\(|javascript:", value or "", re.I):
                continue
            value = html_lib.escape(value or "", quote=True)
            parts.append(f'{name}="{value}"')
        self.out.append("<" + " ".join(parts) + ">")
        if tag not in ("br", "hr", "img", "source", "col"):
            self.stack.append(tag)

    def handle_startendtag(self, tag: str, attrs):
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str):
        tag = tag.lower()
        if tag in self.stack:
            # 关闭到最近的同名标签，保持输出基本平衡
            while self.stack:
                last = self.stack.pop()
                self.out.append(f"</{last}>")
                if last == tag:
                    break

    def handle_data(self, data: str):
        self.out.append(html_lib.escape(data, quote=False))

    def handle_entityref(self, name: str):
        self.out.append(f"&{name};")

    def handle_charref(self, name: str):
        self.out.append(f"&#{name};")

    def result(self) -> str:
        while self.stack:
            self.out.append(f"</{self.stack.pop()}>")
        return "".join(self.out)


def sanitize_html(raw: str, allow_svg: bool = False) -> str:
    parser = _Sanitizer(allow_svg=allow_svg)
    try:
        parser.feed(str(raw or ""))
        parser.close()
    except Exception:
        return ""
    return parser.result()


def check_html(raw: str, allow_svg: bool = False) -> tuple[str, list[str]]:
    """返回 (清洗后 HTML, 问题列表)；问题列表非空时发布应阻塞。"""
    text = str(raw or "")
    issues: list[str] = []
    if DANGEROUS_RE.search(text):
        issues.append("HTML 含 script/事件属性/javascript: 等不安全内容")
    cleaned = sanitize_html(text, allow_svg=allow_svg)
    return cleaned, issues
