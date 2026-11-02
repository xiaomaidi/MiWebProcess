import { defineStore } from "pinia";
import { api, setToken, getToken } from "@/api";
import type { UserInfo } from "@/types";

export const useAuthStore = defineStore("auth", {
  state: () => ({
    token: getToken(),
    user: { id: 0, username: "", is_superuser: false, is_active: false } as UserInfo,
  }),
  getters: {
    isLoggedIn: (s) => !!s.token,
    isAdmin: (s) => !!s.user?.is_superuser,
    displayName: (s) => s.user.username || "未登录",
  },
  actions: {
    setTokenLocal(t: string) {
      this.token = t;
      setToken(t);
    },
    async login(username: string, password: string) {
      const r = await api.post<{ access: string; refresh: string; user: UserInfo }>("/auth/token/", {
        username,
        password,
      });
      this.setTokenLocal(r.access);
      this.user = r.user;
    },
    async fetchUser() {
      this.user = await api.get<UserInfo>("/auth/user/", { silent: true });
    },
    logout() {
      this.token = "";
      this.user = { id: 0, username: "", is_superuser: false, is_active: false };
      setToken("");
    },
  },
});
