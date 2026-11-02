/**
 * SSR 渲染器：由 Django 的 ssr_prerender / runtime.ssr 调用。
 * 用法：node scripts/ssr-render.mjs <job.json> <out.html> <prefetch.json>
 */
import fs from "node:fs";

const entry = new URL("../dist-ssr/entry-server.js", import.meta.url);
const [jobPath, outPath, prePath] = process.argv.slice(2);

if (!jobPath || !outPath) {
  console.error("usage: node scripts/ssr-render.mjs <job.json> <out.html> [prefetch.json]");
  process.exit(2);
}

try {
  const job = JSON.parse(fs.readFileSync(jobPath, "utf8"));
  const mod = await import(entry.href);
  const result = await mod.render(job.url, job.payload, job.apiBase || "");
  fs.writeFileSync(outPath, result.html || "", "utf8");
  if (prePath) fs.writeFileSync(prePath, JSON.stringify(result.prefetch || {}), "utf8");
} catch (error) {
  console.error("[ssr-render]", error && error.stack ? error.stack : String(error));
  process.exit(1);
}
