import { defineStore } from "pinia";
import rawRegistry from "../../../shared/component-registry.json";
import { categoriesOf, normalizeRegistry, type RawRegistry } from "@/builtin/registry-normalize";
import type { ComponentCategory, ComponentMeta } from "@/types";

/** 组件注册表：shared/component-registry.json 为唯一事实源；API 数据叠加启停/自定义组件。 */
const normalized = normalizeRegistry(rawRegistry as unknown as RawRegistry);

export const useComponentStore = defineStore("component", {
  state: () => ({
    list: [...normalized.components] as ComponentMeta[],
    byName: {} as Record<string, ComponentMeta>,
    categories: [...categoriesOf(normalized)] as ComponentCategory[],
    registryVersion: normalized.version || "2.0.0",
    styleSchema: normalized.style_schema || { preset: "common" },
  }),
  getters: {
    enabled: (s) => s.list.filter((c) => c.is_enabled !== false),
    byCategory: (s) => {
      const out: Record<string, ComponentMeta[]> = {};
      for (const c of s.list) if (c.is_enabled !== false) (out[c.category] ||= []).push(c);
      return out;
    },
    getByName: (s) => (name: string) => s.byName[name],
  },
  actions: {
    rebuildIndex() {
      const byName: Record<string, ComponentMeta> = {};
      for (const c of this.list) byName[c.name] = c;
      this.byName = byName;
    },
    /** 用 API 返回覆盖/合并（启停、自定义组件）。保持本地 schema 优先，避免旧后端覆盖 v2 字段。 */
    applyApi(list: ComponentMeta[]) {
      for (const c of list) {
        const i = this.list.findIndex((x) => x.name === c.name);
        if (i >= 0) {
          this.list[i] = {
            ...this.list[i],
            ...c,
            props_schema: c.props_schema?.properties ? c.props_schema : this.list[i].props_schema,
            style_schema: c.style_schema || this.list[i].style_schema,
          };
        } else {
          this.list.push(c);
        }
      }
      this.rebuildIndex();
      // 保留 shared 注册表里的中文分类名/图标；只补充 API 引入的新分类。
      const known = new Set(this.categories.map((x) => x.key));
      for (const c of categoriesOf({ schemaVersion: 2, components: this.list })) {
        if (!known.has(c.key)) {
          this.categories.push(c);
          known.add(c.key);
        }
      }
    },
    meta(name: string): ComponentMeta | undefined {
      if (!Object.keys(this.byName).length) this.rebuildIndex();
      return this.byName[name];
    },
    defaultProps(name: string): Record<string, any> {
      return { ...(this.byName[name]?.default_props || {}) };
    },
    /** props 默认值：default_props 优先，其次 props_schema.properties[*].default。 */
    schemaDefaults(name: string): Record<string, any> {
      const m = this.meta(name);
      if (!m) return {};
      const out: Record<string, any> = { ...(m.default_props || {}) };
      for (const [k, ps] of Object.entries(m.props_schema?.properties || {})) {
        if (ps.default !== undefined && out[k] === undefined) out[k] = ps.default;
      }
      return out;
    },
    categoryLabel(key: string): string {
      return this.categories.find((c) => c.key === key)?.label || key;
    },
  },
});
