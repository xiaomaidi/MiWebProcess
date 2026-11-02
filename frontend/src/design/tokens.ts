/** 设计 Token：颜色 / 间距 / 字体 / 圆角 / 阴影 → CSS 变量。 */

export interface DesignTokens {
  preset?: string;
  color: {
    bg: string;
    surface: string;
    text: string;
    muted: string;
    accent: string;
    border: string;
    success: string;
    warning: string;
    danger: string;
  };
  space: { xs: string; sm: string; md: string; lg: string; xl: string };
  font: { family: string; body: string; title: string; mono: string };
  radius: { sm: string; md: string; lg: string };
  shadow: { sm: string; md: string; lg: string };
  breakpoint: { sm: string; md: string; lg: string; xl: string };
}

const BASE: DesignTokens = {
  preset: "dark-game",
  color: {
    bg: "#0b0f14",
    surface: "#121820",
    text: "#e5e7eb",
    muted: "#94a3b8",
    accent: "#e11d48",
    border: "#283344",
    success: "#22c55e",
    warning: "#f59e0b",
    danger: "#ef4444",
  },
  space: { xs: "4px", sm: "8px", md: "16px", lg: "24px", xl: "32px" },
  font: {
    family: '-apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif',
    body: "14px",
    title: "24px",
    mono: "13px",
  },
  radius: { sm: "4px", md: "8px", lg: "12px" },
  shadow: {
    sm: "0 1px 2px rgba(0,0,0,.08)",
    md: "0 6px 18px rgba(0,0,0,.12)",
    lg: "0 16px 40px rgba(0,0,0,.18)",
  },
  breakpoint: { sm: "640px", md: "768px", lg: "1024px", xl: "1280px" },
};

export const TOKEN_PRESETS: Record<string, DesignTokens> = {
  "dark-game": BASE,
  "light-admin": {
    ...BASE,
    preset: "light-admin",
    color: {
      bg: "#f5f7fa",
      surface: "#ffffff",
      text: "#303133",
      muted: "#909399",
      accent: "#409eff",
      border: "#dcdfe6",
      success: "#67c23a",
      warning: "#e6a23c",
      danger: "#f56c6c",
    },
    shadow: {
      sm: "0 1px 2px rgba(0,0,0,.04)",
      md: "0 4px 14px rgba(0,0,0,.08)",
      lg: "0 12px 32px rgba(0,0,0,.12)",
    },
  },
  "corporate-blue": {
    ...BASE,
    preset: "corporate-blue",
    color: {
      ...BASE.color,
      bg: "#f4f7ff",
      surface: "#ffffff",
      text: "#1f2a44",
      muted: "#6b7a99",
      accent: "#2563eb",
      border: "#d8e0f0",
    },
  },
  "dashboard-dark": {
    ...BASE,
    preset: "dashboard-dark",
    color: {
      ...BASE.color,
      bg: "#07111f",
      surface: "#0d1b2f",
      accent: "#22d3ee",
      border: "#1e3a5f",
    },
  },
  warm: {
    ...BASE,
    preset: "warm",
    color: {
      ...BASE.color,
      bg: "#fffaf3",
      surface: "#ffffff",
      text: "#3d2f23",
      muted: "#8c7b6b",
      accent: "#d97706",
      border: "#eadfd3",
    },
  },
};

export function normalizeTokens(raw: any): DesignTokens {
  if (!raw || typeof raw !== "object") return clone(TOKEN_PRESETS["dark-game"]);
  const preset = TOKEN_PRESETS[String(raw.preset || "")] || null;
  const merged = clone(preset || BASE);
  for (const group of ["color", "space", "font", "radius", "shadow", "breakpoint"] as const) {
    if (raw[group] && typeof raw[group] === "object") {
      Object.assign((merged as any)[group], raw[group]);
    }
  }
  merged.preset = String(raw.preset || merged.preset || "custom");
  return merged;
}

export function tokensToCssVars(tokens: DesignTokens): Record<string, string> {
  const t = normalizeTokens(tokens);
  return {
    "--wp-color-bg": t.color.bg,
    "--wp-color-surface": t.color.surface,
    "--wp-color-text": t.color.text,
    "--wp-color-muted": t.color.muted,
    "--wp-color-accent": t.color.accent,
    "--wp-color-border": t.color.border,
    "--wp-color-success": t.color.success,
    "--wp-color-warning": t.color.warning,
    "--wp-color-danger": t.color.danger,
    "--wp-bg": t.color.bg,
    "--wp-surface": t.color.surface,
    "--wp-text": t.color.text,
    "--wp-muted": t.color.muted,
    "--wp-accent": t.color.accent,
    "--wp-border": t.color.border,
    "--wp-page-bg": t.color.bg,
    "--el-color-primary": t.color.accent,
    "--wp-space-xs": t.space.xs,
    "--wp-space-sm": t.space.sm,
    "--wp-space-md": t.space.md,
    "--wp-space-lg": t.space.lg,
    "--wp-space-xl": t.space.xl,
    "--wp-font-family": t.font.family,
    "--wp-font-body": t.font.body,
    "--wp-font-title": t.font.title,
    "--wp-font-mono": t.font.mono,
    "--wp-radius-sm": t.radius.sm,
    "--wp-radius-md": t.radius.md,
    "--wp-radius-lg": t.radius.lg,
    "--wp-shadow-sm": t.shadow.sm,
    "--wp-shadow-md": t.shadow.md,
    "--wp-shadow-lg": t.shadow.lg,
    "--wp-breakpoint-sm": t.breakpoint.sm,
    "--wp-breakpoint-md": t.breakpoint.md,
    "--wp-breakpoint-lg": t.breakpoint.lg,
    "--wp-breakpoint-xl": t.breakpoint.xl,
  };
}

export function clone(tokens: DesignTokens): DesignTokens {
  return JSON.parse(JSON.stringify(tokens));
}
