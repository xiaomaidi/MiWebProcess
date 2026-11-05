import { expect, test } from "@playwright/test";

import { loginAsAdmin } from "./support/auth";

const DESIGNER_URL = "/design/112/973";
const PAGE_NAME = "数据概览";

/**
 * Browser noise that is not an application error:
 * - the Vite dev server has no favicon, so the browser logs a 404;
 * - ResizeObserver loop warnings are emitted by the browser, not the app.
 */
const IGNORED_CONSOLE_ERRORS = [/favicon\.ico/i, /ResizeObserver loop/i];

test.beforeEach(async ({ page, request }) => {
  await loginAsAdmin(page, request);
});

test("designer loads the 数据概览 page with canvas, header actions and left tabs", async ({ page }) => {
  await page.goto(DESIGNER_URL);

  await expect(page.locator(".wp-d-title")).toHaveText(PAGE_NAME);
  await expect(page.locator(".wp-d-back")).toBeVisible();

  // Canvas mounted and the schema root rendered.
  await expect(page.locator(".wp-d-canvas")).toBeVisible();
  await expect(page.locator(".wp-canvas-root")).toBeVisible();
  await expect(page.locator('.wp-canvas[data-wp-node="root"]')).toBeVisible();

  // Header debug/record entries.
  await expect(page.locator(".wp-d-debug-btn")).toBeVisible();
  await expect(page.locator(".wp-d-debug-btn")).toHaveText("调试");
  await expect(page.locator(".wp-d-record-btn")).toBeVisible();
  await expect(page.locator(".wp-d-record-btn")).toHaveText("录制");

  // Left library tabs required by the designer shell.
  await expect(page.getByRole("tab", { name: "组件", exact: true })).toBeVisible();
  await expect(page.getByRole("tab", { name: "大纲", exact: true })).toBeVisible();
  await expect(page.getByRole("tab", { name: "区块", exact: true })).toBeVisible();
});

test("designer shows page settings, then node property tabs after selecting a node", async ({ page }) => {
  await page.goto(DESIGNER_URL);
  await expect(page.locator(".wp-d-title")).toHaveText(PAGE_NAME);

  // The schema root is selected on load, exposing page-level settings.
  await expect(page.locator(".wp-d-right")).toContainText("页面设置");
  await expect(page.locator(".wp-d-right")).toContainText("画布布局");

  const node = page.locator('[data-wp-node="pageHeadText"]');
  await expect(node).toBeVisible();
  await node.click();

  await expect(page.locator(".wp-pp-tabs")).toBeVisible();
  await expect(page.locator(".wp-pp-node-bar")).toBeVisible();
  for (const name of ["属性", "样式", "事件", "绑定", "高级"]) {
    await expect(page.getByRole("tab", { name, exact: true })).toBeVisible();
  }
  await expect(page.locator(".wp-node-selected")).toHaveCount(1);
});

test("recorder drawer can start recording, show a timeline row, stop and clear", async ({ page }) => {
  await page.goto(DESIGNER_URL);
  await expect(page.locator(".wp-d-title")).toHaveText(PAGE_NAME);

  await page.locator(".wp-d-record-btn").click();
  const drawer = page.locator(".el-drawer").filter({ hasText: "操作录制与回放" });
  await expect(drawer).toBeVisible();
  await expect(drawer.locator(".wp-rec")).toBeVisible();

  const statusTag = drawer.locator(".wp-rec-title .el-tag");
  await expect(statusTag).toHaveText("未开始");

  await drawer.getByRole("button", { name: "● 录制" }).click();
  await expect(statusTag).toHaveText("录制中");

  const rows = drawer.locator(".wp-rec-row");
  await expect(rows.first()).toBeVisible();
  await expect(rows.first()).toContainText("开始录制");

  await drawer.getByRole("button", { name: "停止", exact: true }).click();
  await expect(statusTag).toHaveText("未开始");

  await drawer.getByRole("button", { name: "清空", exact: true }).click();
  const confirm = page.locator(".el-message-box");
  await expect(confirm).toBeVisible();
  await expect(confirm).toContainText("确定清空全部录制记录");
  await confirm.getByRole("button", { name: "确定", exact: true }).click();

  await expect(rows).toHaveCount(0);
  await expect(drawer).toContainText("暂无录制");
});

test("block library tab opens its search and list state without editing blocks", async ({ page }) => {
  await page.goto(DESIGNER_URL);
  await expect(page.locator(".wp-d-title")).toHaveText(PAGE_NAME);

  await page.getByRole("tab", { name: "区块", exact: true }).click();

  const blockLib = page.locator(".wp-block-lib");
  await expect(blockLib).toBeVisible();

  const search = blockLib.getByPlaceholder("搜索区块名称 / 编码");
  await expect(search).toBeVisible();

  // Either existing block cards or the empty state must be rendered; never
  // create/insert/modify a block from this regression test.
  await expect(blockLib.locator(".wp-block-lib-loading")).toHaveCount(0);
  await expect(blockLib.locator(".wp-block-lib-card").first().or(blockLib.locator(".el-empty"))).toBeVisible();

  await search.fill("__playwright_no_match__");
  await expect(blockLib).toContainText("没有匹配的区块");
  await expect(blockLib.getByRole("button", { name: "插入引用" })).toHaveCount(0);
});

test("designer loads without unexpected console errors", async ({ page }) => {
  const errors: string[] = [];
  page.on("console", (message) => {
    if (message.type() !== "error") return;
    const location = message.location().url || "";
    const text = `${message.text()} (${location})`;
    if (IGNORED_CONSOLE_ERRORS.some((pattern) => pattern.test(text))) return;
    errors.push(text);
  });
  page.on("pageerror", (error) => errors.push(`pageerror: ${error.message}`));

  await page.goto(DESIGNER_URL);
  await expect(page.locator(".wp-d-title")).toHaveText(PAGE_NAME);
  await expect(page.locator(".wp-canvas-root")).toBeVisible();

  // Give async schema/registry requests a moment to fail before asserting.
  await page.waitForTimeout(1_000);
  expect(errors, `Unexpected designer console errors:\n${errors.join("\n")}`).toEqual([]);
});

test.describe("designer mobile header", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("面板/属性 buttons are visible and both panels start off-canvas", async ({ page }) => {
    await page.goto(DESIGNER_URL);
    await expect(page.locator(".wp-d-title")).toHaveText(PAGE_NAME);

    const panelButton = page.getByRole("button", { name: "面板", exact: true });
    const propsButton = page.getByRole("button", { name: "属性", exact: true });
    await expect(panelButton).toBeVisible();
    await expect(propsButton).toBeVisible();

    const leftPanel = page.locator(".wp-d-left");
    const rightPanel = page.locator(".wp-d-right");

    // Off-canvas: the left panel is translated fully past the left edge and the
    // right panel fully past the right edge.
    await expect
      .poll(async () => {
        const box = await leftPanel.boundingBox();
        return box ? Math.round(box.x + box.width) : 0;
      })
      .toBeLessThanOrEqual(0);
    await expect
      .poll(async () => {
        const box = await rightPanel.boundingBox();
        return box ? Math.round(box.x) : 0;
      })
      .toBeGreaterThanOrEqual(390);
    await expect(page.locator(".wp-d-mobile-mask")).toHaveCount(0);

    // Opening 面板 slides the left panel into view over a mask.
    await panelButton.click();
    await expect(leftPanel).toHaveClass(/is-mobile-open/);
    await expect
      .poll(async () => {
        const box = await leftPanel.boundingBox();
        return box ? Math.abs(Math.round(box.x)) : 999;
      })
      .toBe(0);
    await expect(page.locator(".wp-d-mobile-mask")).toBeVisible();

    await page.locator(".wp-d-mobile-mask").click({ position: { x: 380, y: 420 } });
    await expect(page.locator(".wp-d-mobile-mask")).toHaveCount(0);

    // Opening 属性 slides the right panel into view.
    await propsButton.click();
    await expect(rightPanel).toHaveClass(/is-mobile-open/);
    await expect
      .poll(async () => {
        const box = await rightPanel.boundingBox();
        return box ? Math.round(box.x + box.width) : 0;
      })
      .toBe(390);
    await expect(page.locator(".wp-d-mobile-mask")).toBeVisible();
  });
});
