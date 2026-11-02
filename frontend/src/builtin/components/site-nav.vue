<template>
  <header class="wp-site-nav" :class="{ 'is-sticky': sticky, 'is-dark': dark }">
    <div class="wp-site-nav-inner">
      <a class="wp-site-brand" href="#" @click.prevent="go(homePath)">
        <img v-if="logo" :src="logo" alt="" class="wp-site-logo" />
        <span>{{ brand }}</span>
      </a>
      <button class="wp-site-menu-btn" type="button" @click="menuOpen = !menuOpen">☰</button>
      <nav class="wp-site-links" :class="{ open: menuOpen }">
        <a
          v-for="(link, i) in normalizedLinks"
          :key="i"
          :href="hrefOf(link.path)"
          :class="{ active: isActive(link.path) }"
          @click.prevent="go(link.path)"
        >
          {{ link.label }}
        </a>
        <a v-if="showSearch" :href="hrefOf(searchPath)" class="wp-site-search" @click.prevent="go(searchPath)">
          ⌕ {{ searchText }}
        </a>
      </nav>
    </div>
  </header>
</template>

<script setup lang="ts">
import { computed, inject, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import type { RuntimeScope } from "@/types";

interface NavLink {
  label: string;
  path: string;
}

const props = withDefaults(
  defineProps<{
    brand?: string;
    logo?: string;
    links?: NavLink[];
    homePath?: string;
    sticky?: boolean;
    dark?: boolean;
    showSearch?: boolean;
    searchPath?: string;
    searchText?: string;
  }>(),
  {
    brand: "MiWebProcess",
    logo: "",
    links: () => [
      { label: "首页", path: "home" },
      { label: "资讯", path: "news/games" },
      { label: "专题", path: "topics" },
    ],
    homePath: "home",
    sticky: true,
    dark: false,
    showSearch: true,
    searchPath: "search",
    searchText: "搜索",
  }
);

const scope = inject<RuntimeScope | null>("wp.scope", null);
const router = useRouter();
const route = useRoute();
const menuOpen = ref(false);
const appCode = computed(() => String((scope?.variables?.app as any)?.code || route.params.appCode || ""));
const currentPath = computed(() => {
  if (scope?.routePath !== undefined) return scope.routePath;
  return String(route.params.pathMatch ?? route.params.splat ?? "");
});

const normalizedLinks = computed<NavLink[]>(() =>
  Array.isArray(props.links) ? props.links.filter((l) => l && l.label && l.path) : []
);

function cleanPath(path: string): string {
  return String(path || "").replace(/^\/+/, "");
}

function hrefOf(path: string): string {
  if (/^https?:\/\//i.test(path)) return path;
  return `/run/${appCode.value}/${cleanPath(path)}`;
}

function go(path: string) {
  menuOpen.value = false;
  if (/^https?:\/\//i.test(path)) {
    window.open(path, "_blank");
    return;
  }
  if (scope?.navigate) scope.navigate(cleanPath(path));
  else if (appCode.value) router.push(hrefOf(path));
}

function isActive(path: string): boolean {
  const target = cleanPath(path);
  const current = cleanPath(currentPath.value);
  if (target === "home") return current === "" || current === "home";
  return current === target || current.startsWith(`${target}/`);
}
</script>

<style scoped>
.wp-site-nav {
  width: 100%;
  background: #fff;
  border-bottom: 1px solid #e8e8e8;
  z-index: 50;
}
.wp-site-nav.is-sticky {
  position: sticky;
  top: 0;
}
.wp-site-nav.is-dark {
  background: #17181c;
  border-bottom-color: #2c2d33;
  color: #f2f3f5;
}
.wp-site-nav-inner {
  max-width: 1200px;
  margin: 0 auto;
  padding: 0 20px;
  height: 58px;
  display: flex;
  align-items: center;
  gap: 28px;
}
.wp-site-brand {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: inherit;
  text-decoration: none;
  font-size: 20px;
  font-weight: 800;
  letter-spacing: 0.5px;
  white-space: nowrap;
}
.wp-site-logo {
  width: 28px;
  height: 28px;
  object-fit: contain;
}
.wp-site-links {
  display: flex;
  align-items: center;
  gap: 22px;
  flex: 1;
}
.wp-site-links a {
  color: inherit;
  text-decoration: none;
  font-size: 14px;
  opacity: 0.78;
  padding: 6px 0;
  border-bottom: 2px solid transparent;
}
.wp-site-links a:hover,
.wp-site-links a.active {
  opacity: 1;
  border-bottom-color: #e4393c;
}
.wp-site-search {
  margin-left: auto;
}
.wp-site-menu-btn {
  display: none;
  margin-left: auto;
  border: 0;
  background: transparent;
  color: inherit;
  font-size: 20px;
  cursor: pointer;
}
@media (max-width: 720px) {
  .wp-site-menu-btn {
    display: block;
  }
  .wp-site-links {
    display: none;
    position: absolute;
    top: 58px;
    left: 0;
    right: 0;
    background: inherit;
    padding: 12px 20px;
    flex-direction: column;
    align-items: flex-start;
    border-bottom: 1px solid #e8e8e8;
  }
  .wp-site-links.open {
    display: flex;
  }
}
</style>
