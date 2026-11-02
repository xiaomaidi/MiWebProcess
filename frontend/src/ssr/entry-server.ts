/** SSR 入口：由 vite build --ssr 打包，Node 侧调用 render()。 */
import { createSSRApp } from "vue";
import { createPinia } from "pinia";
import ElementPlus from "element-plus";
import zhCn from "element-plus/es/locale/lang/zh-cn";
import { renderToString } from "vue/server-renderer";
import { createMemoryHistory } from "vue-router";

import App from "@/App.vue";
import { createAppRouter } from "@/router";
import { dumpPrefetch, clearPrefetch } from "./prefetch";
import { setSsrState } from "./state";

export async function render(url: string, payload: any, apiBase = ""): Promise<{ html: string; prefetch: Record<string, any> }> {
  if (apiBase) (globalThis as any).__WP_API_BASE__ = apiBase;
  clearPrefetch();
  setSsrState({ url, payload });

  const app = createSSRApp(App);
  const pinia = createPinia();
  const router = createAppRouter(createMemoryHistory());
  app.use(pinia);
  app.use(router);
  app.use(ElementPlus, { locale: zhCn });

  await router.push(url);
  await router.isReady();
  const html = await renderToString(app);
  return { html, prefetch: dumpPrefetch() };
}
