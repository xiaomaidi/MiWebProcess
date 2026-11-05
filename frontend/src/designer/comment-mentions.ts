/**
 * 评论 @ 提及的前端纯函数：解析、候选过滤、高亮分段。
 *
 * 候选成员由 `comment-users.ts` 拉取（`/org/users/?size=200` + 应用成员兜底）；
 * 这里不访问网络，便于在 Node 原生类型剥离下做回归自测。
 */

import { api } from "@/api";

export interface MentionUser {
  id: number;
  username: string;
  display_name: string;
}

export interface MentionRecord {
  id?: number | null;
  username: string;
  display_name?: string;
}

export interface MentionWarning {
  token: string;
  code: string;
  message: string;
}

export interface MentionSegment {
  text: string;
  mention: boolean;
  username?: string;
}

// Unicode 用户名（含中文）与 Django 合法字符；前缀仅排除 ASCII 标识符，避免邮箱误判。
const MENTION_RE = /(^|[^A-Za-z0-9_@])@([\p{L}\p{N}_.@+\-]{1,150})/gu;

function trimCandidates(raw: string): string[] {
  const out = [raw];
  let value = raw;
  while (value && /[.+\-@]$/.test(value)) {
    value = value.slice(0, -1);
    if (value) out.push(value);
  }
  return out;
}

/** 提取去重后的原始 @ token（不含 @ 前缀）。 */
export function extractMentionTokens(text: string): string[] {
  const out: string[] = [];
  const seen = new Set<string>();
  const re = new RegExp(MENTION_RE.source, "gu");
  let match: RegExpExecArray | null;
  while ((match = re.exec(text || ""))) {
    const raw = match[2];
    if (raw && !seen.has(raw)) {
      seen.add(raw);
      out.push(raw);
    }
  }
  return out;
}

/** 在已知成员中解析一个 token（支持句末标点与大小写不敏感）。 */
export function resolveMentionUser(
  token: string,
  users: Iterable<MentionUser>
): MentionUser | null {
  const byName = new Map<string, MentionUser>();
  for (const user of users) byName.set(user.username.toLowerCase(), user);
  for (const candidate of trimCandidates(token)) {
    const hit = byName.get(candidate.toLowerCase());
    if (hit) return hit;
  }
  return null;
}

/** 补全下拉的过滤结果（display_name / username 均可匹配）。 */
export function filterMentionUsers(
  users: MentionUser[],
  query: string,
  limit = 6
): MentionUser[] {
  const needle = query.trim().toLowerCase();
  const rows = needle
    ? users.filter(
        (user) =>
          user.username.toLowerCase().includes(needle) ||
          user.display_name.toLowerCase().includes(needle)
      )
    : users;
  return rows.slice(0, Math.max(1, limit));
}

/**
 * 把评论正文切分为纯文本 / 已确认提及片段（用于模板渲染，避免 v-html）。
 */
export function mentionSegments(
  text: string,
  mentionUsernames: Iterable<string>
): MentionSegment[] {
  const source = text || "";
  const known = new Map<string, string>();
  for (const name of mentionUsernames) {
    const value = String(name || "");
    if (value) known.set(value.toLowerCase(), value);
  }
  if (!known.size) return source ? [{ text: source, mention: false }] : [];

  const segments: MentionSegment[] = [];
  const re = new RegExp(MENTION_RE.source, "gu");
  let last = 0;
  let match: RegExpExecArray | null;
  while ((match = re.exec(source))) {
    const at = match.index + match[1].length;
    const raw = match[2];
    let candidate = raw;
    let hit: string | null = null;
    while (candidate) {
      const value = known.get(candidate.toLowerCase());
      if (value) {
        hit = value;
        break;
      }
      if (!/[.+\-@]$/.test(candidate)) break;
      candidate = candidate.slice(0, -1);
    }
    if (!hit) continue;
    if (at > last) segments.push({ text: source.slice(last, at), mention: false });
    segments.push({ text: `@${hit}`, mention: true, username: hit });
    last = at + 1 + candidate.length;
  }
  if (last < source.length) segments.push({ text: source.slice(last), mention: false });
  return segments;
}

/** 拉取可提及成员：org 用户目录优先，应用成员兜底/合并。 */
export async function fetchMentionUsers(appId: number): Promise<MentionUser[]> {
  const merged = new Map<string, MentionUser>();
  const remember = (row: any) => {
    const username = String(row?.username || "").trim();
    if (!username) return;
    const rawId = row?.user ?? row?.id;
    const id = Number(rawId);
    const displayName =
      String(row?.display_name || row?.full_name || username).trim() || username;
    merged.set(username.toLowerCase(), {
      id: Number.isFinite(id) ? id : 0,
      username,
      display_name: displayName,
    });
  };

  try {
    const res = await api.get<{ results?: any[] }>("/org/users/?size=200", { silent: true });
    for (const row of res?.results || []) remember(row);
  } catch {
    /* 403：非平台管理员 / 部门负责人，走应用成员兜底 */
  }

  if (Number(appId)) {
    try {
      const res = await api.get<{ results?: any[] }>(
        `/apps/${Number(appId)}/members/?size=200`,
        { silent: true }
      );
      for (const row of res?.results || []) remember(row);
    } catch {
      /* 无权读取成员时忽略 */
    }
  }

  return [...merged.values()].sort((a, b) => a.username.localeCompare(b.username));
}
