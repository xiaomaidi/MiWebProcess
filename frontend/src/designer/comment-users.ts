/**
 * 评论 @ 提及候选成员。
 *
 * 优先 `/org/users/?size=200`（平台管理员 / 部门负责人可用），普通成员
 * 回退到 `/apps/{appId}/members/?size=200`。只保留 id / username /
 * display_name，不渲染或缓存邮箱。
 */
import { api } from "@/api";
import type { MentionUser } from "./comment-mentions";

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
