import { defineStore } from "pinia";
import { api } from "@/api";
import type { DataSourceDef } from "@/types";

export const useDatasourceStore = defineStore("datasource", {
  state: () => ({
    list: [] as DataSourceDef[],
    results: {} as Record<number, any>,
    loading: {} as Record<number, boolean>,
  }),
  actions: {
    async loadAll(appId: number) {
      const data = await api.get<unknown>(`/apps/${appId}/datasources/`, { silent: true });
      const list = Array.isArray(data) ? (data as DataSourceDef[]) : ((data as { results?: DataSourceDef[] })?.results ?? []);
      this.list = list;
      return this.list;
    },
    async query(id: number, params: Record<string, any> = {}): Promise<any> {
      if (this.results[id]) return this.results[id];
      this.loading[id] = true;
      try {
        const res = await api.post<any>(`/datasources/${id}/query/`, params, { silent: true });
        this.results[id] = res;
        return res;
      } finally {
        this.loading[id] = false;
      }
    },
    invalidate(id: number) {
      delete this.results[id];
    },
    reset() {
      this.list = [];
      this.results = {};
      this.loading = {};
    },
  },
});
