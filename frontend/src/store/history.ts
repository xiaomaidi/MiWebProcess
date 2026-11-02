import { defineStore } from "pinia";
import { useSchemaStore } from "./schema";
import { deepClone } from "@/utils";

interface Command {
  label: string;
  before: any;
  after: any;
}

/** 命令模式：每次变更记录整份 schema 快照（首版规模下性能足够）。 */
export const useHistoryStore = defineStore("history", {
  state: () => ({
    stack: [] as Command[],
    future: [] as Command[],
    max: 100,
  }),
  getters: {
    canUndo: (s) => s.stack.length > 0,
    canRedo: (s) => s.future.length > 0,
    lastLabel: (s) => s.stack[s.stack.length - 1]?.label || "",
  },
  actions: {
    /** 手动推送一条命令（变更已在外部完成，如拖拽移动）。 */
    push(label: string, before: any, after: any) {
      this.stack.push({ label, before, after });
      if (this.stack.length > this.max) this.stack.shift();
      this.future = [];
    },

    /** 包装一次变更：自动记录前后快照；返回 apply 的返回值。 */
    run(label: string, apply: () => any): any {
      const ss = useSchemaStore();
      if (!ss.schema) return apply();
      const before = deepClone(ss.schema);
      const result = apply();
      this.stack.push({ label, before, after: deepClone(ss.schema) });
      if (this.stack.length > this.max) this.stack.shift();
      this.future = [];
      return result;
    },
    undo() {
      const ss = useSchemaStore();
      const top = this.stack.pop();
      if (!top || !ss.schema) return;
      this.future.push(top);
      ss.schema = deepClone(top.before);
      ss.dirty = true;
    },
    redo() {
      const ss = useSchemaStore();
      const top = this.future.pop();
      if (!top || !ss.schema) return;
      this.stack.push(top);
      ss.schema = deepClone(top.after);
      ss.dirty = true;
    },
    clear() {
      this.stack = [];
      this.future = [];
    },
  },
});
