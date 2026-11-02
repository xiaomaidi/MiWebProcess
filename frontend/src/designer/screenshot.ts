/**
 * 设计器截图：把画布 DOM 序列化为 SVG foreignObject → canvas → PNG dataURL。
 * 不引入 html2canvas 等依赖；跨域图片会导致 canvas 被污染，此时抛出可读错误。
 */
export interface CaptureOptions {
  maxWidth?: number;
  maxHeight?: number;
  scale?: number;
}

function inlineStyles(source: Element, target: Element, depth = 0): void {
  if (depth > 24) return;
  const computed = window.getComputedStyle(source);
  const style = (target as HTMLElement).style;
  for (let i = 0; i < computed.length; i += 1) {
    const prop = computed.item(i);
    style.setProperty(prop, computed.getPropertyValue(prop), computed.getPropertyPriority(prop));
  }
  const sChildren = Array.from(source.children);
  const tChildren = Array.from(target.children);
  for (let i = 0; i < sChildren.length; i += 1) {
    const tag = sChildren[i].tagName;
    if (tag === "SCRIPT" || tag === "NOSCRIPT" || tag === "IFRAME") continue;
    if (tChildren[i]) inlineStyles(sChildren[i], tChildren[i], depth + 1);
  }
}

export async function captureElement(
  element: HTMLElement,
  options: CaptureOptions = {}
): Promise<{ dataUrl: string; width: number; height: number }> {
  const rect = element.getBoundingClientRect();
  const width = Math.max(320, Math.min(options.maxWidth ?? 1280, Math.ceil(element.scrollWidth || rect.width)));
  const height = Math.max(240, Math.min(options.maxHeight ?? 2200, Math.ceil(element.scrollHeight || rect.height)));
  const scale = options.scale ?? 1;

  const clone = element.cloneNode(true) as HTMLElement;
  inlineStyles(element, clone);
  clone.style.width = `${width}px`;
  clone.style.height = `${height}px`;
  clone.style.margin = "0";
  clone.style.overflow = "hidden";
  clone.setAttribute("xmlns", "http://www.w3.org/1999/xhtml");

  const html = new XMLSerializer().serializeToString(clone);
  const svg =
    `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}">` +
    `<foreignObject x="0" y="0" width="100%" height="100%">${html}</foreignObject></svg>`;
  const url = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;

  const image = new Image();
  await new Promise<void>((resolve, reject) => {
    image.onload = () => resolve();
    image.onerror = () => reject(new Error("画布序列化失败，请检查图片是否跨域"));
    image.src = url;
  });

  const canvas = document.createElement("canvas");
  canvas.width = Math.round(width * scale);
  canvas.height = Math.round(height * scale);
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("浏览器不支持 canvas");
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.scale(scale, scale);
  ctx.drawImage(image, 0, 0, width, height);
  try {
    return { dataUrl: canvas.toDataURL("image/png"), width, height };
  } catch {
    throw new Error("截图失败：画布包含跨域图片，请更换为本站图片后重试");
  }
}

/** 优先截取设计器画布，其次整个页面容器。 */
export function findCanvasElement(): HTMLElement | null {
  return (
    (document.querySelector(".wp-canvas-inner") as HTMLElement | null) ||
    (document.querySelector(".wp-canvas-root") as HTMLElement | null) ||
    (document.querySelector(".wp-runtime") as HTMLElement | null)
  );
}
