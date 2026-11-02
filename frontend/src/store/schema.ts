import { defineStore } from "pinia";
import type { PageSchema, SchemaNode } from "@/types";
import { useComponentStore } from "./component";
import { deepClone, uid } from "@/utils";

/** 节点树操作（纯变更；撤销/重做由 historyStore 快照包装）。 */
export const useSchemaStore = defineStore("schema", {
  state: () => ({
    schema: null as PageSchema | null,
    pageId: 0,
    appId: 0,
    selectedId: null as string | null,
    selectedIds: [] as string[],
    hoveredId: null as string | null,
    dirty: false,
    clipboard: null as null | { nodes: Record<string, SchemaNode>; rootIds: string[] },
  }),
  getters: {
    root(): SchemaNode | null {
      if (!this.schema) return null;
      return this.schema.nodes[this.schema.rootId] || null;
    },
    node: (s) => (id: string) => (s.schema ? s.schema.nodes[id] : undefined),
    /** 子节点（children + 所有命名插槽，保持顺序） */
    childrenOf: (s) => (id: string): SchemaNode[] => {
      const n = s.schema?.nodes[id];
      if (!n) return [];
      const ids = [...(n.children || [])];
      for (const list of Object.values(n.slots || {})) ids.push(...list);
      return ids.map((x) => s.schema!.nodes[x]).filter(Boolean);
    },
    layoutMode: (s) => s.schema?.layout?.mode || "flow",
    selectedNodes: (s): SchemaNode[] =>
      s.selectedIds.map((id) => s.schema?.nodes[id]).filter((n): n is SchemaNode => !!n),
    isSelected: (s) => (id: string) => s.selectedIds.includes(id),
    parentOf: (s) => (id: string): string | null => {
      if (!s.schema) return null;
      for (const [pid, p] of Object.entries(s.schema.nodes)) {
        if (p.children?.includes(id)) return pid;
        for (const list of Object.values(p.slots || {})) if (list.includes(id)) return pid;
      }
      return null;
    },
  },
  actions: {
    setSchema(schema: PageSchema | null, pageId = 0, appId = 0) {
      // 空 schema（后端旧数据 schema={}）无 rootId，无法拖放/渲染 → 归一化为默认空白画布
      const s = schema && schema.rootId && schema.nodes && schema.nodes[schema.rootId] ? schema : this.createEmpty();
      this.schema = deepClone(s);
      this.pageId = pageId;
      this.appId = appId;
      this.selectedId = this.schema.rootId;
      this.selectedIds = [this.schema.rootId];
      this.clipboard = null;
      this.dirty = false;
    },
    /** 单选 / Ctrl 多选（additive=true 时切换该节点）。 */
    select(id: string | null, additive = false) {
      if (!id) {
        this.selectedId = null;
        this.selectedIds = [];
        return;
      }
      if (!additive) {
        this.selectedId = id;
        this.selectedIds = [id];
        return;
      }
      // 画布根节点默认选中；Ctrl 点第一个子节点时应替换根，而不是把根一起多选。
      if (this.selectedIds.length === 1 && this.selectedIds[0] === this.schema?.rootId && id !== this.schema?.rootId) {
        this.selectedId = id;
        this.selectedIds = [id];
        return;
      }
      const idx = this.selectedIds.indexOf(id);
      if (idx >= 0) {
        this.selectedIds.splice(idx, 1);
        this.selectedId = this.selectedIds[this.selectedIds.length - 1] || null;
      } else {
        this.selectedIds.push(id);
        this.selectedId = id;
      }
    },
    selectMany(ids: string[]) {
      const unique = [...new Set(ids)];
      this.selectedIds = unique;
      this.selectedId = unique[unique.length - 1] || null;
    },
    selectAll() {
      if (!this.schema) return;
      this.selectedIds = Object.keys(this.schema.nodes);
      this.selectedId = this.selectedIds[this.selectedIds.length - 1] || null;
    },
    hover(id: string | null) {
      this.hoveredId = id;
    },
    markSaved() {
      this.dirty = false;
    },

    patchNode(id: string, patch: Partial<SchemaNode>) {
      const n = this.schema?.nodes[id];
      if (!n) return;
      Object.assign(n, patch);
      if (patch.props) n.props = { ...n.props, ...patch.props };
      if (patch.style) n.style = { ...n.style, ...patch.style };
      if (patch.events) n.events = { ...n.events, ...patch.events };
      this.dirty = true;
    },

    insertNode(type: string, parentId: string, index: number): string {
      const s = this.schema;
      const comp = useComponentStore();
      if (!s) return "";
      const id = uid();
      const parent = s.nodes[parentId];
      const node: SchemaNode = {
        id,
        type,
        componentVersion: comp.meta(type)?.version || "1.0.0",
        props: comp.defaultProps(type),
        children: [],
      };
      if (s.layout?.mode === "free") {
        node.layout = { x: 24 + Math.floor(Math.random() * 120), y: 24 + Math.floor(Math.random() * 120), width: 200, height: 80 };
      }
      s.nodes[id] = node;
      if (parent) {
        const arr = parent.children || (parent.children = []);
        arr.splice(Math.max(0, Math.min(index, arr.length)), 0, id);
      }
      this.selectedId = id;
      this.selectedIds = [id];
      this.dirty = true;
      return id;
    },

    removeNode(id: string) {
      const s = this.schema;
      if (!s || id === s.rootId) return;
      // 从父节点摘除
      for (const p of Object.values(s.nodes)) {
        if (p.children?.includes(id)) p.children = p.children.filter((x) => x !== id);
        for (const key of Object.keys(p.slots || {})) {
          p.slots![key] = (p.slots![key] || []).filter((x) => x !== id);
        }
      }
      // 级联删除子树
      const del = (nid: string) => {
        const n = s.nodes[nid];
        if (!n) return;
        for (const c of n.children || []) del(c);
        for (const list of Object.values(n.slots || {})) for (const c of list) del(c);
        delete s.nodes[nid];
      };
      del(id);
      this.selectedIds = this.selectedIds.filter((x) => x !== id);
      if (this.selectedId === id) this.selectedId = this.selectedIds[this.selectedIds.length - 1] || s.rootId;
      this.dirty = true;
    },

    /** 移动节点到 newParentId 的 children index 处（同 parent 即重排序）；兼容节点原位于父节点命名插槽的情形。 */
    moveNode(id: string, newParentId: string, index: number) {
      const s = this.schema;
      if (!s || id === s.rootId || !s.nodes[id]) return;
      const findParent = (nid: string): { parentId: string; slotKey?: string } | null => {
        for (const [pid, p] of Object.entries(s.nodes)) {
          if (p.children?.includes(nid)) return { parentId: pid };
          for (const [k, list] of Object.entries(p.slots || {})) {
            if (list.includes(nid)) return { parentId: pid, slotKey: k };
          }
        }
        return null;
      };
      const old = findParent(id);
      // 目标父节点合法性：不能移入自己或自己的后代
      let cur: string | undefined = newParentId;
      while (cur) {
        if (cur === id) return;
        cur = findParent(cur)?.parentId;
      }
      let targetIndex = index;
      if (old) {
        const p = s.nodes[old.parentId];
        if (old.slotKey) {
          p.slots![old.slotKey] = p.slots![old.slotKey].filter((x) => x !== id);
        } else {
          const from = p.children!.indexOf(id);
          p.children = p.children!.filter((x) => x !== id);
          if (old.parentId === newParentId && from < index) targetIndex -= 1;
        }
      }
      s.nodes[newParentId].children ||= [];
      s.nodes[newParentId].children!.splice(Math.max(0, Math.min(targetIndex, s.nodes[newParentId].children!.length)), 0, id);
      this.selectedId = id;
      this.selectedIds = [id];
      this.dirty = true;
    },

    duplicateNode(id: string) {
      const s = this.schema;
      if (!s) return "";
      const src = s.nodes[id];
      if (!src) return "";
      const map: Record<string, string> = {};
      const copy = (nid: string): string => {
        const n = s.nodes[nid];
        const newId = uid();
        map[nid] = newId;
        const clone: SchemaNode = deepClone(n);
        clone.id = newId;
        clone.children = (clone.children || []).map((c) => map[c] || copy(c));
        clone.slots = Object.fromEntries(Object.entries(clone.slots || {}).map(([k, v]) => [k, v.map((c) => map[c] || copy(c))]));
        s.nodes[newId] = clone;
        return newId;
      };
      const newId = copy(id);
      const parentId = Object.keys(s.nodes).find((pid) => s.nodes[pid].children?.includes(id)) || s.rootId;
      const arr = s.nodes[parentId].children!;
      arr.splice(arr.indexOf(id) + 1, 0, newId);
      this.selectedId = newId;
      this.selectedIds = [newId];
      this.dirty = true;
      return newId;
    },

    /** 复制当前选中的顶层节点（含子树）到内部剪贴板。 */
    copySelection(): boolean {
      const s = this.schema;
      if (!s || !this.selectedIds.length) return false;
      const selected = new Set(this.selectedIds.filter((id) => id !== s.rootId));
      const parentOf = (nid: string): string | null => {
        for (const [pid, p] of Object.entries(s.nodes)) {
          if (p.children?.includes(nid)) return pid;
          for (const list of Object.values(p.slots || {})) if (list.includes(nid)) return pid;
        }
        return null;
      };
      const top = this.selectedIds.filter((id) => {
        if (id === s.rootId) return false;
        let p = parentOf(id);
        while (p) {
          if (selected.has(p)) return false;
          p = parentOf(p);
        }
        return true;
      });
      const out: Record<string, SchemaNode> = {};
      const cloneTree = (nid: string): string => {
        const src = s.nodes[nid];
        if (!src) return "";
        const newId = uid();
        const clone: SchemaNode = deepClone(src);
        clone.id = newId;
        clone.children = (src.children || []).map(cloneTree);
        clone.slots = Object.fromEntries(
          Object.entries(src.slots || {}).map(([k, list]) => [k, list.map(cloneTree)])
        );
        out[newId] = clone;
        return newId;
      };
      const rootIds = top.map(cloneTree);
      this.clipboard = { nodes: out, rootIds };
      return rootIds.length > 0;
    },

    /** 粘贴内部剪贴板到指定容器；返回新节点 id。 */
    pasteClipboard(parentId?: string, index = -1): string[] {
      const s = this.schema;
      const clip = this.clipboard;
      if (!s || !clip || !clip.rootIds.length) return [];
      const parent = s.nodes[parentId || s.rootId];
      if (!parent) return [];
      const map: Record<string, string> = {};
      const out: Record<string, SchemaNode> = {};
      for (const [oldId, src] of Object.entries(clip.nodes)) {
        const newId = uid();
        map[oldId] = newId;
        const clone: SchemaNode = deepClone(src);
        clone.id = newId;
        out[newId] = clone;
      }
      for (const n of Object.values(out)) {
        n.children = (n.children || []).map((id) => map[id]).filter(Boolean);
        n.slots = Object.fromEntries(
          Object.entries(n.slots || {}).map(([k, list]) => [k, list.map((id) => map[id]).filter(Boolean)])
        );
      }
      Object.assign(s.nodes, out);
      const roots = clip.rootIds.map((id) => map[id]).filter(Boolean);
      parent.children ||= [];
      const at = index === -1 ? parent.children.length : Math.max(0, Math.min(index, parent.children.length));
      parent.children.splice(at, 0, ...roots);
      this.selectedIds = roots;
      this.selectedId = roots[roots.length - 1] || null;
      this.dirty = true;
      return roots;
    },

    /** 删除选中的顶层节点（子节点上移）。 */
    removeSelected() {
      const s = this.schema;
      if (!s) return;
      const selected = new Set(this.selectedIds.filter((id) => id !== s.rootId));
      const parentOf = (nid: string): string | null => {
        for (const [pid, p] of Object.entries(s.nodes)) {
          if (p.children?.includes(nid)) return pid;
          for (const list of Object.values(p.slots || {})) if (list.includes(nid)) return pid;
        }
        return null;
      };
      const top = this.selectedIds.filter((id) => {
        let p = parentOf(id);
        while (p) {
          if (selected.has(p)) return false;
          p = parentOf(p);
        }
        return true;
      });
      for (const id of top) if (s.nodes[id]) this.removeNodeReparent(id);
      this.selectedIds = [];
      this.selectedId = s.rootId;
    },

    /** 自由布局多选对齐。 */
    alignSelection(mode: "left" | "hcenter" | "right" | "top" | "vcenter" | "bottom") {
      const nodes = this.selectedNodes.filter((n) => !!n.layout);
      if (!nodes.length) return;
      const left = Math.min(...nodes.map((n) => n.layout!.x));
      const right = Math.max(...nodes.map((n) => n.layout!.x + n.layout!.width));
      const top = Math.min(...nodes.map((n) => n.layout!.y));
      const bottom = Math.max(...nodes.map((n) => n.layout!.y + n.layout!.height));
      for (const n of nodes) {
        const l = n.layout!;
        if (mode === "left") l.x = left;
        else if (mode === "right") l.x = right - l.width;
        else if (mode === "hcenter") l.x = Math.round((left + right - l.width) / 2);
        else if (mode === "top") l.y = top;
        else if (mode === "bottom") l.y = bottom - l.height;
        else if (mode === "vcenter") l.y = Math.round((top + bottom - l.height) / 2);
      }
      this.dirty = true;
    },

    /** 自由布局多选等间距分布。 */
    distributeSelection(axis: "x" | "y") {
      const nodes = this.selectedNodes.filter((n) => !!n.layout);
      if (nodes.length < 3) return;
      const size = (n: SchemaNode) => (axis === "x" ? n.layout!.width : n.layout!.height);
      const pos = (n: SchemaNode) => (axis === "x" ? n.layout!.x : n.layout!.y);
      nodes.sort((a, b) => pos(a) - pos(b));
      const start = pos(nodes[0]);
      const end = pos(nodes[nodes.length - 1]) + size(nodes[nodes.length - 1]);
      const total = nodes.reduce((sum, n) => sum + size(n), 0);
      const gap = (end - start - total) / (nodes.length - 1);
      let cursor = start;
      for (const n of nodes) {
        if (axis === "x") n.layout!.x = Math.round(cursor);
        else n.layout!.y = Math.round(cursor);
        cursor += size(n) + gap;
      }
      this.dirty = true;
    },

    /** 插入组件节点：props 取 props_schema 默认值，slots 按 meta.slots 初始化。 */
    insertComponent(type: string, parentId: string, index = -1): string {
      const s = this.schema;
      const comp = useComponentStore();
      if (!s) return "";
      const meta = comp.meta(type);
      const id = uid();
      const props: Record<string, any> = meta ? comp.schemaDefaults(type) : {};
      const node: SchemaNode = {
        id,
        type,
        componentVersion: meta?.version || "1.0.0",
        props,
        children: [],
      };
      if (meta && meta.slots && meta.slots.length) {
        node.slots = Object.fromEntries(meta.slots.map((k) => [k, []]));
      }
      if (s.layout?.mode === "free") {
        const sibs = s.nodes[parentId] ? this.childrenOf(parentId).length : 0;
        node.layout = { x: 24 + (sibs % 6) * 216, y: 24 + Math.floor(sibs / 6) * 96, width: 200, height: 80 };
      }
      s.nodes[id] = node;
      const parent = s.nodes[parentId];
      if (parent) {
        const arr = parent.children || (parent.children = []);
        const at = index === -1 ? arr.length : Math.max(0, Math.min(index, arr.length));
        arr.splice(at, 0, id);
      }
      this.selectedId = id;
      this.selectedIds = [id];
      this.dirty = true;
      return id;
    },

    setNodeHideOn(id: string, breakpoints: string[]) {
      const n = this.schema?.nodes[id];
      if (!n) return;
      n.hideOn = [...new Set(breakpoints)];
      this.dirty = true;
    },
    setNodeMotion(id: string, motion: string) {
      const n = this.schema?.nodes[id];
      if (!n) return;
      if (motion) n.motion = motion;
      else delete n.motion;
      this.dirty = true;
    },

    /** 合并节点 style（整体替换由调用方构造完整对象后传入）；历史包装由调用方负责。 */
    setNodeStyle(id: string, style: Record<string, any>) {
      const n = this.schema?.nodes[id];
      if (!n) return;
      n.style = { ...(n.style || {}), ...style };
    },

    /** 设置断点覆盖样式（xs/sm/md/lg/xl）。 */
    setNodeResponsive(id: string, breakpoint: string, style: Record<string, any>) {
      const n = this.schema?.nodes[id];
      if (!n) return;
      n.responsive ||= {};
      if (style && Object.keys(style).length) n.responsive[breakpoint] = { ...style };
      else delete n.responsive[breakpoint];
      if (!Object.keys(n.responsive).length) delete n.responsive;
      this.dirty = true;
    },

    /** 页面级 meta 合并。 */
    setPageMeta(patch: Record<string, any>) {
      if (!this.schema) return;
      this.schema.meta = { ...(this.schema.meta || {}), ...patch };
      this.dirty = true;
    },

    /** 切换画布布局模式 flow/free；历史包装由调用方负责。 */
    setLayoutMode(mode: "flow" | "free") {
      if (!this.schema) return;
      this.schema.layout = { ...(this.schema.layout || { mode: "flow", width: 1200, height: 800 }), mode };
    },

    /** 设置单个 prop（字面量或 {__binding__} 绑定值）；历史包装由调用方负责。 */
    setNodeProp(id: string, key: string, value: any) {
      const n = this.schema?.nodes[id];
      if (!n) return;
      if (!n.props) n.props = {};
      n.props[key] = value;
      this.dirty = true;
    },

    removeNodeProp(id: string, key: string) {
      const n = this.schema?.nodes[id];
      if (!n?.props) return;
      delete n.props[key];
      this.dirty = true;
    },

    /** 删除节点：其 children/插槽子节点上移至父节点（不级联删除）。 */
    removeNodeReparent(id: string) {
      const s = this.schema;
      if (!s || id === s.rootId || !s.nodes[id]) return;
      const target = s.nodes[id];
      let parent: SchemaNode | null = null;
      for (const p of Object.values(s.nodes)) {
        if (p.children?.includes(id) || Object.values(p.slots || {}).some((l) => l.includes(id))) {
          parent = p;
          break;
        }
      }
      const childIds = [...(target.children || [])];
      for (const list of Object.values(target.slots || {})) childIds.push(...list);
      if (parent) {
        const oldIndex = parent.children ? parent.children.indexOf(id) : -1;
        if (parent.children) parent.children = parent.children.filter((x) => x !== id);
        for (const k of Object.keys(parent.slots || {})) parent.slots![k] = parent.slots![k].filter((x) => x !== id);
        if (parent.children && oldIndex >= 0) parent.children.splice(oldIndex, 0, ...childIds);
      }
      delete s.nodes[id];
      this.selectedIds = this.selectedIds.filter((x) => x !== id);
      if (this.selectedId === id) this.selectedId = this.selectedIds[this.selectedIds.length - 1] || s.rootId;
      this.dirty = true;
    },

    addVariable(key: string, def: { value: any; scope?: "global" | "page" }) {
      if (!this.schema) return;
      this.schema.variables ||= {};
      this.schema.variables[key] = def;
      this.dirty = true;
    },

    removeVariable(key: string) {
      if (!this.schema?.variables) return;
      delete this.schema.variables[key];
      this.dirty = true;
    },

    renameAsset(oldKey: string, newKey: string) {
      const a = this.schema?.assets;
      if (!a || !a[oldKey] || oldKey === newKey) return;
      a[newKey] = a[oldKey];
      delete a[oldKey];
      this.dirty = true;
    },

    /** 创建默认空白页面 schema。 */
    createEmpty(): PageSchema {
      const rootId = uid();
      return {
        schemaVersion: 2,
        rootId,
        nodes: {
          [rootId]: {
            id: rootId,
            type: "wp-canvas",
            componentVersion: "2.0.0",
            props: {},
            children: [],
          },
        },
        variables: {},
        meta: { title: "", lang: "zh-CN", globalStyle: { cssVars: {} } },
        layout: { mode: "flow", width: 1200, height: 800 },
      };
    },
  },
});
