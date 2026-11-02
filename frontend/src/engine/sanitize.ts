/** 轻量 HTML/Markdown 安全渲染（无 DOMPurify 依赖，发布时后端再做一次白名单校验）。 */

const ALLOWED_TAGS = new Set([
  "a", "b", "strong", "i", "em", "u", "s", "del", "p", "br", "hr", "ul", "ol", "li",
  "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre", "code", "span", "div",
  "table", "thead", "tbody", "tfoot", "tr", "td", "th", "caption", "colgroup", "col",
  "img", "figure", "figcaption", "video", "audio", "source", "small", "sub", "sup", "mark",
]);

const ALLOWED_ATTRS = new Set([
  "class", "style", "href", "src", "alt", "title", "width", "height", "target", "rel",
  "colspan", "rowspan", "controls", "poster", "muted", "loop", "autoplay", "preload",
  "loading", "role", "aria-label", "aria-hidden",
]);

const SVG_TAGS = new Set([
  "svg", "g", "path", "rect", "circle", "ellipse", "line", "polyline", "polygon", "text",
  "tspan", "defs", "lineargradient", "radialgradient", "stop", "clippath", "mask", "use",
  "symbol", "marker", "pattern", "filter", "fegaussianblur", "fecolormatrix", "title", "desc",
]);

const SVG_ATTRS = new Set([
  "viewbox", "width", "height", "fill", "stroke", "stroke-width", "stroke-linecap",
  "stroke-linejoin", "d", "cx", "cy", "r", "rx", "ry", "x", "x1", "x2", "y", "y1", "y2",
  "points", "transform", "opacity", "fill-opacity", "stroke-opacity", "stop-color",
  "stop-opacity", "offset", "gradientunits", "gradienttransform", "id", "class", "style",
  "preserveaspectratio", "xmlns", "clip-path", "mask", "href", "xlink:href",
]);

function safeUrl(raw: string, opts: { image?: boolean } = {}): string | null {
  const v = (raw || "").trim();
  if (!v) return "";
  if (v.startsWith("#") || v.startsWith("/") || v.startsWith("./") || v.startsWith("../")) return v;
  const lower = v.toLowerCase();
  if (lower.startsWith("http://") || lower.startsWith("https://")) return v;
  if (opts.image && lower.startsWith("data:image/")) return v;
  if (lower.startsWith("mailto:") || lower.startsWith("tel:")) return v;
  return null;
}

function cleanElement(el: Element, opts: { svg?: boolean }): void {
  const tag = el.tagName.toLowerCase();
  const allowed = opts.svg ? SVG_TAGS.has(tag) : ALLOWED_TAGS.has(tag);
  if (!allowed) {
    // 保留文本，移除危险容器（script/style/iframe/object...）
    const text = el.textContent || "";
    el.replaceWith(document.createTextNode(text));
    return;
  }
  for (const attr of Array.from(el.attributes)) {
    const name = attr.name.toLowerCase();
    const allow = opts.svg ? SVG_ATTRS.has(name) : ALLOWED_ATTRS.has(name);
    if (!allow || name.startsWith("on")) {
      el.removeAttribute(attr.name);
      continue;
    }
    if (name === "href" || name === "src" || name === "xlink:href") {
      const safe = safeUrl(attr.value, { image: tag === "img" || tag === "source" });
      if (safe === null) el.removeAttribute(attr.name);
      else if (safe !== attr.value) el.setAttribute(attr.name, safe);
    }
    if (name === "style" && /expression\s*\(|javascript:|url\s*\(\s*['"]?\s*javascript:/i.test(attr.value)) {
      el.removeAttribute(attr.name);
    }
  }
  if (tag === "a" && el.getAttribute("target") === "_blank") {
    el.setAttribute("rel", "noopener noreferrer");
  }
  for (const child of Array.from(el.children)) cleanElement(child, opts);
}

export function sanitizeHtml(html: string): string {
  const raw = String(html ?? "");
  if (!raw.trim()) return "";
  if (typeof window === "undefined" || typeof DOMParser === "undefined") {
    return raw.replace(/<script[\s\S]*?<\/script>/gi, "").replace(/\son\w+\s*=\s*"[^"]*"/gi, "");
  }
  const doc = new DOMParser().parseFromString(raw, "text/html");
  for (const child of Array.from(doc.body.children)) cleanElement(child, {});
  return doc.body.innerHTML;
}

export function sanitizeSvg(code: string): string {
  const raw = String(code ?? "").trim();
  if (!raw) return "";
  if (typeof window === "undefined" || typeof DOMParser === "undefined") return "";
  const doc = new DOMParser().parseFromString(`<body>${raw}</body>`, "text/html");
  for (const child of Array.from(doc.body.children)) cleanElement(child, { svg: true });
  return doc.body.innerHTML;
}

export function escapeHtml(value: unknown): string {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

/** 极简 Markdown（标题/列表/代码/引用/链接/粗斜体）；先转义再生成标签，最后统一 sanitize。 */
export function renderMarkdown(src: string): string {
  const lines = String(src ?? "").replace(/\r\n?/g, "\n").split("\n");
  const out: string[] = [];
  let inCode = false;
  let codeLang = "";
  let inList = false;
  const closeList = () => {
    if (inList) {
      out.push("</ul>");
      inList = false;
    }
  };
  const inline = (text: string) => {
    let s = escapeHtml(text);
    s = s.replace(/`([^`]+)`/g, "<code>$1</code>");
    s = s.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    s = s.replace(/\*([^*]+)\*/g, "<em>$1</em>");
    s = s.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (_m, label, href) => {
      const safe = safeUrl(String(href));
      return safe === null ? label : `<a href="${escapeHtml(safe)}" target="_blank" rel="noopener noreferrer">${label}</a>`;
    });
    return s;
  };
  for (const line of lines) {
    const fence = line.match(/^```(\w*)\s*$/);
    if (fence) {
      if (inCode) {
        out.push(`</code></pre>`);
        inCode = false;
      } else {
        closeList();
        codeLang = fence[1] || "";
        out.push(`<pre><code class="language-${escapeHtml(codeLang)}">`);
        inCode = true;
      }
      continue;
    }
    if (inCode) {
      out.push(escapeHtml(line) + "\n");
      continue;
    }
    if (!line.trim()) {
      closeList();
      continue;
    }
    const h = line.match(/^(#{1,6})\s+(.*)$/);
    if (h) {
      closeList();
      out.push(`<h${h[1].length}>${inline(h[2])}</h${h[1].length}>`);
      continue;
    }
    if (/^>\s?/.test(line)) {
      closeList();
      out.push(`<blockquote>${inline(line.replace(/^>\s?/, ""))}</blockquote>`);
      continue;
    }
    const li = line.match(/^[-*+]\s+(.*)$/);
    if (li) {
      if (!inList) {
        out.push("<ul>");
        inList = true;
      }
      out.push(`<li>${inline(li[1])}</li>`);
      continue;
    }
    closeList();
    out.push(`<p>${inline(line)}</p>`);
  }
  if (inCode) out.push("</code></pre>");
  closeList();
  return sanitizeHtml(out.join("\n"));
}

const KEYWORDS: Record<string, RegExp> = {
  javascript: /\b(const|let|var|function|return|if|else|for|of|in|new|class|import|from|export|await|async|true|false|null|undefined|this)\b/g,
  typescript: /\b(const|let|var|function|return|if|else|for|of|in|new|class|import|from|export|await|async|interface|type|true|false|null|undefined|this)\b/g,
  python: /\b(def|class|return|if|elif|else|for|while|in|import|from|as|try|except|with|lambda|True|False|None|and|or|not)\b/g,
  json: /\b(true|false|null)\b/g,
  sql: /\b(SELECT|FROM|WHERE|JOIN|LEFT|RIGHT|INNER|GROUP|ORDER|BY|LIMIT|INSERT|UPDATE|DELETE|CREATE|TABLE|AND|OR|AS|ON)\b/gi,
  bash: /\b(echo|cd|export|if|then|else|fi|for|do|done|function)\b/g,
};

/** 代码高亮：先 escape，再用 span 包关键字/字符串/注释。输出仍经过 sanitize。 */
export function highlightCode(code: string, language = "text"): string {
  let s = escapeHtml(code);
  s = s.replace(/(&quot;.*?&quot;|&#39;.*?&#39;)/g, '<span class="tok-string">$1</span>');
  s = s.replace(/(\/\/[^\n]*|#[^\n]*)/g, '<span class="tok-comment">$1</span>');
  const kw = KEYWORDS[language];
  if (kw) s = s.replace(kw, '<span class="tok-key">$&</span>');
  return s;
}
