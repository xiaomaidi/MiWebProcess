/** 远程 Web Component 加载器：导入的 Vue 自定义元素按需加载。 */
import { defineComponent, h, onMounted, ref, type Component } from "vue";

const scriptCache = new Map<string, Promise<void>>();
const componentCache = new Map<string, Component>();

function loadRemote(src: string): Promise<void> {
  // 兼容某些库打包后残留的 process.env.NODE_ENV 引用。
  if (typeof window !== "undefined" && !(window as any).process) {
    (window as any).process = { env: { NODE_ENV: "production" } };
  }
  const existing = scriptCache.get(src);
  if (existing) return existing;
  const task = import(/* @vite-ignore */ src).then(() => undefined);
  scriptCache.set(src, task);
  task.catch(() => scriptCache.delete(src));
  return task;
}

function whenDefined(tag: string, timeoutMs = 12000): Promise<void> {
  if (typeof customElements === "undefined") return Promise.resolve();
  if (customElements.get(tag)) return Promise.resolve();
  return Promise.race([
    customElements.whenDefined(tag).then(() => undefined),
    new Promise<void>((_, reject) => window.setTimeout(() => reject(new Error(`自定义元素 ${tag} 未注册`)), timeoutMs)),
  ]);
}

export function remoteComponentFor(src: string, tag: string): Component {
  const key = `${src}|${tag}`;
  const cached = componentCache.get(key);
  if (cached) return cached;
  const Remote = defineComponent({
    name: "WpRemoteWebComponent",
    inheritAttrs: false,
    setup(_, { attrs }) {
      const ready = ref(false);
      const error = ref("");
      onMounted(async () => {
        try {
          await loadRemote(src);
          await whenDefined(tag);
          ready.value = true;
        } catch (exc: any) {
          error.value = exc?.message || "组件加载失败";
        }
      });
      return () => {
        if (error.value) return h("div", { class: "wp-remote-error" }, `组件加载失败：${error.value}`);
        if (!ready.value) return h("div", { class: "wp-remote-loading" }, "加载组件…");
        return h(tag, attrs);
      };
    },
  });
  componentCache.set(key, Remote);
  return Remote;
}
