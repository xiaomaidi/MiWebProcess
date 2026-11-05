import type { APIRequestContext } from "@playwright/test";

/**
 * Helpers for the designer e2e suite.
 *
 * The lock-conflict and schema-sync specs must never touch the seeded demo
 * pages. Every test creates an isolated temporary page in app 112 through the
 * public REST API, writes a deterministic free-layout schema, and deletes the
 * page in a `finally` block.
 */

/** Seeded demo application shared with the existing designer/admin specs. */
export const DESIGNER_APP_ID = 112;

/** Stable node ids used by the temporary pages (one page per test). */
export const LOCK_NODE_ID = "e2e-lock-text";
export const SYNC_NODE_ID = "e2e-sync-text";

export interface NodeLayout {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface TempDesignerPage {
  id: number;
  appId: number;
  name: string;
  path: string;
  schemaRevision: number;
}

export interface FreeTextPageOptions {
  textId: string;
  content: string;
  layout?: NodeLayout;
}

/** Default free-layout geometry for the single text node. */
export const DEFAULT_NODE_LAYOUT: NodeLayout = { x: 64, y: 64, width: 320, height: 48 };

export function authHeaders(token: string): Record<string, string> {
  return { Authorization: `Bearer ${token}` };
}

/**
 * Build a minimal, valid free-layout page with one `wp-text` node.
 * Keeping ids deterministic makes canvas selectors stable.
 */
export function buildFreeTextPageSchema(options: FreeTextPageOptions): Record<string, any> {
  const layout = options.layout ?? DEFAULT_NODE_LAYOUT;
  return {
    schemaVersion: 2,
    rootId: "e2e-root",
    nodes: {
      "e2e-root": {
        id: "e2e-root",
        type: "wp-canvas",
        componentVersion: "2.0.0",
        props: {},
        children: [options.textId],
      },
      [options.textId]: {
        id: options.textId,
        type: "wp-text",
        componentVersion: "1.0.0",
        props: {
          content: options.content,
          fontSize: 18,
          color: "#111827",
        },
        children: [],
        layout: { ...layout },
      },
    },
    variables: {},
    meta: { title: "E2E temp page", lang: "zh-CN", globalStyle: { cssVars: {} } },
    layout: { mode: "free", width: 1200, height: 800 },
  };
}

/**
 * Create a temporary page and write the supplied schema.
 * Throws (instead of silently continuing) when either REST call fails.
 */
export async function createTempDesignerPage(
  request: APIRequestContext,
  token: string,
  options: { label: string; schema: Record<string, any> }
): Promise<TempDesignerPage> {
  const suffix = `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
  const label = options.label.replace(/[^a-z0-9-]/gi, "").toLowerCase();
  const name = `E2E ${label} ${suffix}`;
  const path = `e2e-${label}-${suffix}`;

  const created = await request.post(`/api/apps/${DESIGNER_APP_ID}/pages/`, {
    headers: authHeaders(token),
    data: { name, path, type: "page" },
  });
  if (!created.ok()) {
    throw new Error(`Creating temporary page failed: HTTP ${created.status()} — ${await created.text()}`);
  }
  const page = (await created.json()) as { id: number };
  if (!page?.id) throw new Error("Temporary page response did not contain an id");

  let savedPayload: { schema_revision?: number };
  try {
    const saved = await request.put(`/api/pages/${page.id}/schema/`, {
      headers: authHeaders(token),
      data: { schema: options.schema },
    });
    if (!saved.ok()) {
      throw new Error(
        `Writing temporary page schema failed: HTTP ${saved.status()} — ${await saved.text()}`
      );
    }
    savedPayload = (await saved.json()) as { schema_revision?: number };
  } catch (error) {
    // Do not leak a half-provisioned page when the schema write fails.
    await deleteTempDesignerPage(request, token, page.id).catch(() => undefined);
    throw error;
  }

  return {
    id: page.id,
    appId: DESIGNER_APP_ID,
    name,
    path,
    schemaRevision: Number(savedPayload.schema_revision) || 1,
  };
}

/** Read the persisted schema (used to prove a blocked drag did not mutate it). */
export async function fetchPageSchema(
  request: APIRequestContext,
  token: string,
  pageId: number
): Promise<{ schema: Record<string, any>; schema_revision: number }> {
  const response = await request.get(`/api/pages/${pageId}/schema/`, {
    headers: authHeaders(token),
  });
  if (!response.ok()) {
    throw new Error(`Reading page schema failed: HTTP ${response.status()} — ${await response.text()}`);
  }
  return (await response.json()) as { schema: Record<string, any>; schema_revision: number };
}

/** Delete a temporary page; a missing page (404) is treated as already cleaned up. */
export async function deleteTempDesignerPage(
  request: APIRequestContext,
  token: string,
  pageId: number
): Promise<void> {
  const response = await request.delete(`/api/pages/${pageId}/`, {
    headers: authHeaders(token),
  });
  if (!response.ok() && response.status() !== 404) {
    throw new Error(
      `Deleting temporary page ${pageId} failed: HTTP ${response.status()} — ${await response.text()}`
    );
  }
}
