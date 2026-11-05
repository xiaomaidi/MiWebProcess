import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

// Resolve filesystem paths from the config URL without node: type imports.
// file:///D:/a/b/vite.config.ts -> "D:/a/b" (Windows), "/a/b" (POSIX).
const metaUrl = new URL(import.meta.url);
const rootDir = new URL(".", metaUrl).pathname.slice(1);
const projectDir = new URL("../", metaUrl).pathname.slice(1);

export default defineConfig({
  plugins: [
    vue(),
    {
      name: "market-sandbox-cors",
      configureServer(server) {
        server.middlewares.use((req, res, next) => {
          const url = (req as any).url as string | undefined;
          if (url && url.startsWith("/market-demo")) {
            res.setHeader("Access-Control-Allow-Origin", "*");
          }
          next();
        });
      },
    },
  ],
  resolve: {
    alias: {
      "@": new URL("./src", metaUrl).pathname.slice(1),
      "@shared": new URL("../shared", metaUrl).pathname.slice(1),
    },
  },
  server: {
    port: 5173,
    // 编辑器/工具会先写临时目录再原子替换；监听这些目录会在 Windows 上触发 EBUSY。
    watch: {
      ignored: ["**/.*.tmpdir/**", "**/.*.tmp", "**/.tmp/**"],
    },
    // shared/ 位于 frontend 之外；开发服务器需要显式允许项目根目录。
    fs: { allow: [rootDir, projectDir] },
    proxy: {
      "/api": { target: "http://127.0.0.1:8000", changeOrigin: true },
      "/media": { target: "http://127.0.0.1:8000", changeOrigin: true },
      "/ws": { target: "ws://127.0.0.1:8000", ws: true },
    },
  },
});
