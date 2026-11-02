/** 轻量 Markdown 渲染：只生成安全标签，适用于 AI 文本。 */

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function inline(text: string): string {
  return text
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/\*([^*]+)\*/g, "<em>$1</em>");
}

export function renderMarkdown(source: string): string {
  const codeBlocks: string[] = [];
  let text = String(source || "").replace(/```([\s\S]*?)```/g, (_match, code: string) => {
    const index = codeBlocks.length;
    codeBlocks.push(`<pre><code>${escapeHtml(code.replace(/^\w*\n/, ""))}</code></pre>`);
    return `\n@@CODE_BLOCK_${index}@@\n`;
  });
  text = escapeHtml(text);

  const lines = text.split(/\r?\n/);
  const html: string[] = [];
  let listType: "ul" | "ol" | null = null;

  const closeList = () => {
    if (listType) {
      html.push(`</${listType}>`);
      listType = null;
    }
  };

  for (const raw of lines) {
    const line = raw.trimEnd();
    const trimmed = line.trim();
    if (!trimmed) {
      closeList();
      continue;
    }
    if (/^@@CODE_BLOCK_\d+@@$/.test(trimmed)) {
      closeList();
      const index = Number(trimmed.match(/\d+/)![0]);
      html.push(codeBlocks[index] || "");
      continue;
    }
    const heading = trimmed.match(/^(#{1,4})\s+(.+)$/);
    if (heading) {
      closeList();
      const level = Math.min(4, heading[1].length);
      html.push(`<h${level}>${inline(heading[2])}</h${level}>`);
      continue;
    }
    const bullet = trimmed.match(/^[-*]\s+(.+)$/);
    if (bullet) {
      if (listType !== "ul") {
        closeList();
        listType = "ul";
        html.push("<ul>");
      }
      html.push(`<li>${inline(bullet[1])}</li>`);
      continue;
    }
    const ordered = trimmed.match(/^\d+[.)]\s+(.+)$/);
    if (ordered) {
      if (listType !== "ol") {
        closeList();
        listType = "ol";
        html.push("<ol>");
      }
      html.push(`<li>${inline(ordered[1])}</li>`);
      continue;
    }
    closeList();
    if (trimmed.startsWith("&gt;")) {
      html.push(`<blockquote>${inline(trimmed.slice(4).trim())}</blockquote>`);
      continue;
    }
    html.push(`<p>${inline(trimmed)}</p>`);
  }
  closeList();
  return html.join("");
}
