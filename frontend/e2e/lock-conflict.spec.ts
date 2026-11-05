import { expect, test, type BrowserContext, type Page } from "@playwright/test";

import { fetchAdminToken, loginAsAdmin } from "./support/auth";
import {
  DEFAULT_NODE_LAYOUT,
  DESIGNER_APP_ID,
  LOCK_NODE_ID,
  buildFreeTextPageSchema,
  createTempDesignerPage,
  deleteTempDesignerPage,
  fetchPageSchema,
} from "./support/designer-api";
import { waitForDesignerChannel } from "./support/designer-ws";
import { acquireRemoteLock, closeRemoteLock, releaseRemoteLock } from "./support/remote-lock";

/**
 * Lock-conflict regression coverage.
 *
 * Page 973 is a flow-layout page, so it cannot express "drag did not move the
 * node" through node coordinates. Instead each test provisions a temporary
 * free-layout page through the API and deletes it afterwards; no seeded page is
 * ever written to or deleted.
 */
test.describe("designer lock conflict", () => {
  test("remote lock blocks dragging, warns, keeps layout unchanged and clears the badge on release", async ({
    browser,
    page,
    request,
  }) => {
    const token = await fetchAdminToken(request);
    const temp = await createTempDesignerPage(request, token, {
      label: "lock",
      schema: buildFreeTextPageSchema({
        textId: LOCK_NODE_ID,
        content: "E2E lock target",
        layout: DEFAULT_NODE_LAYOUT,
      }),
    });

    let remoteContext: BrowserContext | undefined;
    let remotePage: Page | undefined;

    try {
      await loginAsAdmin(page, request);

      // Register channel listeners before navigation so the initial snapshots
      // cannot be missed.
      const lockReady = waitForDesignerChannel(page, "designer-lock");
      const syncReady = waitForDesignerChannel(page, "designer-sync");
      await page.goto(`/design/${DESIGNER_APP_ID}/${temp.id}`);
      await expect(page.locator(".wp-d-title")).toHaveText(temp.name);

      const node = page.locator(`[data-wp-node="${LOCK_NODE_ID}"]`);
      await expect(node).toBeVisible();
      await Promise.all([lockReady, syncReady]);

      const originalBox = await node.boundingBox();
      expect(originalBox, "temp node should have a measurable box").not.toBeNull();
      if (!originalBox) throw new Error("Lock target node has no bounding box");

      // Baseline: the persisted schema holds the known free-layout coordinates.
      const persistedBefore = await fetchPageSchema(request, token, temp.id);
      expect(persistedBefore.schema.nodes[LOCK_NODE_ID]?.layout).toEqual(DEFAULT_NODE_LAYOUT);

      // Second browser context = second user/session. It only needs to be on
      // the app origin to open the lock WebSocket with the admin JWT.
      remoteContext = await browser.newContext({ viewport: { width: 1440, height: 900 } });
      remotePage = await remoteContext.newPage();
      await loginAsAdmin(remotePage, request);
      await remotePage.goto("/admin/apps");
      await expect(remotePage.locator(".wp-admin-user-name")).toHaveText("admin");

      const remoteLock = await acquireRemoteLock(remotePage, {
        pageId: temp.id,
        nodeId: LOCK_NODE_ID,
        token,
      });
      expect(remoteLock.expiresAt).not.toBe("");

      // The main page receives the lock broadcast and renders the read-only
      // overlay before we attempt the drag.
      const badge = page.locator(".wp-node-lock-badge").filter({ hasText: "admin" });
      await expect(badge).toHaveCount(1);
      await expect(badge).toBeVisible();
      await expect(page.locator(".wp-node-lock-ring")).toHaveCount(1);
      await expect(page.locator(".wp-collab-locks")).toContainText("1 处锁定");

      // Drag attempt: pointerdown is intercepted by the remote-lock guard, so
      // no dragState is created and layout must stay identical.
      const centerX = originalBox.x + originalBox.width / 2;
      const centerY = originalBox.y + originalBox.height / 2;
      await page.mouse.move(centerX, centerY);
      await page.mouse.down();
      await page.mouse.move(centerX + 140, centerY + 90, { steps: 8 });
      await page.mouse.up();

      const warning = page.locator(".el-message").filter({ hasText: "已被 admin 锁定" }).first();
      await expect(warning).toBeVisible();
      await expect(warning).toContainText("无法拖动");

      const afterBox = await node.boundingBox();
      expect(afterBox, "blocked drag should leave the node in place").not.toBeNull();
      if (afterBox) {
        expect(Math.abs(afterBox.x - originalBox.x)).toBeLessThanOrEqual(1);
        expect(Math.abs(afterBox.y - originalBox.y)).toBeLessThanOrEqual(1);
      }

      // The failed drag must not dirty the page nor change the persisted schema.
      await expect(page.locator(".wp-d-dirty")).toHaveCount(0);
      const persistedAfter = await fetchPageSchema(request, token, temp.id);
      expect(persistedAfter.schema.nodes[LOCK_NODE_ID]?.layout).toEqual(DEFAULT_NODE_LAYOUT);

      // Explicit release → server broadcasts `lock:release` → badge/ring vanish.
      await releaseRemoteLock(remotePage);
      await expect(page.locator(".wp-node-lock-badge")).toHaveCount(0);
      await expect(page.locator(".wp-node-lock-ring")).toHaveCount(0);
      await expect(page.locator(".wp-collab-locks")).toHaveCount(0);
    } finally {
      if (remotePage) await closeRemoteLock(remotePage).catch(() => undefined);
      if (remoteContext) await remoteContext.close().catch(() => undefined);
      await page.close().catch(() => undefined);
      await deleteTempDesignerPage(request, token, temp.id);
    }
  });
});
