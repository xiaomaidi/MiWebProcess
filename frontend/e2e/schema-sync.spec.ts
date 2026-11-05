import { expect, test, type BrowserContext, type Page } from "@playwright/test";

import { fetchAdminToken, loginAsAdmin } from "./support/auth";
import {
  DEFAULT_NODE_LAYOUT,
  DESIGNER_APP_ID,
  SYNC_NODE_ID,
  buildFreeTextPageSchema,
  createTempDesignerPage,
  deleteTempDesignerPage,
} from "./support/designer-api";
import { waitForDesignerChannel } from "./support/designer-ws";

const INITIAL_TEXT = "E2E sync old";
const UPDATED_TEXT = "E2E sync new";

/**
 * Two-user schema-sync regression coverage.
 *
 * Both contexts open the same temporary free-layout designer page. Page A edits
 * a text node through the real property panel; page B must apply the broadcast
 * in place (no reload, no navigation). The temporary page is deleted afterwards.
 */
test.describe("designer schema sync", () => {
  test("property edit in one context reaches the second context without a reload", async ({
    browser,
    page,
    request,
  }) => {
    const token = await fetchAdminToken(request);
    const temp = await createTempDesignerPage(request, token, {
      label: "sync",
      schema: buildFreeTextPageSchema({
        textId: SYNC_NODE_ID,
        content: INITIAL_TEXT,
        layout: DEFAULT_NODE_LAYOUT,
      }),
    });

    let contextB: BrowserContext | undefined;
    let pageB: Page | undefined;

    try {
      const designerPath = `/design/${DESIGNER_APP_ID}/${temp.id}`;

      // ---------- User A ----------
      await loginAsAdmin(page, request);
      const syncAReady = waitForDesignerChannel(page, "designer-sync");
      const lockAReady = waitForDesignerChannel(page, "designer-lock");
      await page.goto(designerPath);
      await expect(page.locator(".wp-d-title")).toHaveText(temp.name);

      const nodeA = page.locator(`[data-wp-node="${SYNC_NODE_ID}"]`);
      await expect(nodeA).toBeVisible();
      await expect(nodeA).toContainText(INITIAL_TEXT);
      await Promise.all([syncAReady, lockAReady]);

      // ---------- User B ----------
      contextB = await browser.newContext({ viewport: { width: 1440, height: 900 } });
      pageB = await contextB.newPage();
      let navigationCount = 0;
      pageB.on("framenavigated", (frame) => {
        if (pageB && frame === pageB.mainFrame()) navigationCount += 1;
      });

      await loginAsAdmin(pageB, request);
      const syncBReady = waitForDesignerChannel(pageB, "designer-sync");
      await pageB.goto(designerPath);
      await expect(pageB.locator(".wp-d-title")).toHaveText(temp.name);

      const nodeB = pageB.locator(`[data-wp-node="${SYNC_NODE_ID}"]`);
      await expect(nodeB).toBeVisible();
      await expect(nodeB).toContainText(INITIAL_TEXT);
      await syncBReady;
      await expect(pageB.locator(".wp-d-dirty")).toHaveCount(0);

      // Baseline after B has finished its initial navigation. A full reload
      // would either bump this counter or clear the sentinel below.
      const navigationBaseline = navigationCount;
      await pageB.evaluate(() => {
        (window as any).__wpE2ESyncSentinel = "alive";
      });

      // ---------- Edit in A via the real property panel ----------
      await nodeA.click();
      await expect(page.locator(".wp-pp-node-bar")).toContainText("wp-text");

      const contentProp = page
        .locator(".wp-props .wp-prop")
        .filter({ has: page.locator(".wp-prop-label", { hasText: "内容" }) });
      const contentInput = contentProp.locator("input.el-input__inner");
      await expect(contentInput).toHaveValue(INITIAL_TEXT);

      await contentInput.fill(UPDATED_TEXT);
      await contentInput.press("Tab");

      await expect(nodeA).toContainText(UPDATED_TEXT);
      await expect(page.locator(".wp-d-dirty")).toHaveCount(1);

      // ---------- B applies the broadcast in place ----------
      await expect(nodeB).toContainText(UPDATED_TEXT, { timeout: 10_000 });
      await expect(pageB).toHaveURL(new RegExp(`/design/${DESIGNER_APP_ID}/${temp.id}$`));
      expect(navigationCount, "schema sync must not navigate/reload page B").toBe(navigationBaseline);
      expect(
        await pageB.evaluate(() => (window as any).__wpE2ESyncSentinel),
        "page B window state must survive the remote schema update"
      ).toBe("alive");
      // 远端操作尚未落库，B 会显示“未保存”并交给自动保存；这里只校验无刷新收敛。
    } finally {
      if (pageB) await pageB.close().catch(() => undefined);
      if (contextB) await contextB.close().catch(() => undefined);
      await page.close().catch(() => undefined);
      await deleteTempDesignerPage(request, token, temp.id);
    }
  });
});
