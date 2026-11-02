/**
 * Windows 下 Vite 文件监听对编辑工具产生的临时目录可能抛 EBUSY（未处理 'error' 事件 → 进程崩溃）。
 * 本守护进程级拦截 EBUSY 类异常，保证 dev server 存活；其余异常照常抛出。
 * 用法：node --require ./vite-watch-guard.cjs node_modules/vite/bin/vite.js ...
 */
process.on("uncaughtException", (err) => {
  if (err && (err.code === "EBUSY" || err.code === "EPERM") && /watch/i.test(String(err.syscall || ""))) {
    console.error(`[watch-guard] 忽略文件监听 ${err.code} 异常: ${err.path || ""}`);
    return;
  }
  console.error(err);
  process.exit(1);
});
