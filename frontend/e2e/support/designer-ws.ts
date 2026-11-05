import type { Page } from "@playwright/test";

export type DesignerChannel = "designer-lock" | "designer-sync";

function isSnapshotFrame(payload: string | Buffer): boolean {
  const text = String(payload);
  return text.includes('"type": "snapshot"') || text.includes('"type":"snapshot"');
}

/**
 * Wait until the designer page has opened the given WebSocket channel *and*
 * received the server's initial snapshot.
 *
 * IMPORTANT: call this before `page.goto(...)`; the returned promise registers
 * listeners eagerly so the short-lived connection cannot be missed.
 *
 * - `designer-lock` proves the page can acquire/release node locks;
 * - `designer-sync` proves the page is subscribed to remote schema broadcasts.
 */
export async function waitForDesignerChannel(
  page: Page,
  channel: DesignerChannel,
  timeout = 15_000
): Promise<void> {
  const fragment = `/ws/${channel}/`;
  const socketPromise = page.waitForEvent("websocket", {
    predicate: (socket) => socket.url().includes(fragment),
    timeout,
  });
  const socket = await socketPromise;
  await socket.waitForEvent("framereceived", {
    predicate: (frame) => isSnapshotFrame(frame.payload),
    timeout,
  });
}
