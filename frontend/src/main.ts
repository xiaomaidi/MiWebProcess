import { createApp, createSSRApp } from "vue";
import { createPinia } from "pinia";
import ElementPlus from "element-plus";
import zhCn from "element-plus/es/locale/lang/zh-cn";
import "element-plus/dist/index.css";
import "./styles/global.css";
import "./design/common-token-adapter.css";

import App from "./App.vue";
import { createAppRouter } from "./router";
import { setPrefetch } from "./ssr/prefetch";
import { setSsrState } from "./ssr/state";

const ssr = (window as any).__WP_SSR__ as
  | { url: string; payload: unknown; prefetch?: Record<string, unknown> }
  | undefined;

// SSR 快照页：用 createSSRApp 水合已有 DOM；普通 SPA 页面照常挂载。
const app = ssr?.payload ? createSSRApp(App) : createApp(App);
const router = createAppRouter();

if (ssr?.payload) {
  setSsrState({ url: ssr.url, payload: ssr.payload, prefetch: ssr.prefetch });
  setPrefetch(ssr.prefetch);
}

app.use(createPinia());
app.use(router);
app.use(ElementPlus, { locale: zhCn });

router.isReady().then(() => {
  app.mount("#app");
});
