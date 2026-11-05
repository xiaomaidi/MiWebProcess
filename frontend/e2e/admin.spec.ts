import { expect, test } from "@playwright/test";

import { loginAsAdmin } from "./support/auth";

test.beforeEach(async ({ page, request }) => {
  await loginAsAdmin(page, request);
});

test("admin logs in, sees the apps list and opens the MiAdmin app detail", async ({ page }) => {
  await page.goto("/admin/apps");

  // Auth helper seeded a token, so the router guard must not bounce us to /login.
  await expect(page).toHaveURL(/\/admin\/apps$/);
  await expect(page.getByRole("heading", { name: "应用管理", exact: true })).toBeVisible();
  await expect(page.locator(".wp-admin-user-name")).toHaveText("admin");

  const appCard = page.locator(".app-card", { hasText: "MiWebProcess" });
  await expect(appCard).toBeVisible();
  await expect(appCard).toContainText("mi-admin");

  await appCard.getByRole("button", { name: "进入应用" }).click();

  await expect(page).toHaveURL(/\/admin\/apps\/112$/);
  await expect(page.locator(".wp-page-header h2")).toContainText("MiWebProcess");
  await expect(page.getByRole("tab", { name: "页面", exact: true })).toBeVisible();

  // The page list is loaded asynchronously; the designer target page must be there.
  const pageRow = page.locator(".el-table__row", { hasText: "数据概览" }).first();
  await expect(pageRow).toBeVisible();
  await expect(pageRow).toContainText("dashboard");
});

test("notification center renders its page, filters and current notifications", async ({ page }) => {
  await page.goto("/admin/notifications");

  await expect(page.getByRole("heading", { name: /通知中心/ })).toBeVisible();
  await expect(page.locator(".wp-notify-summary")).toContainText("通知");
  await expect(page.getByRole("radio", { name: "全部" })).toBeVisible();
  await expect(page.getByRole("radio", { name: "未读" })).toBeVisible();

  const cards = page.locator(".wp-notify-card");
  const empty = page.locator(".wp-notify-list .el-empty");
  await expect(cards.first().or(empty)).toBeVisible();

  // Read-only regression: never mark notifications as read.
  if (await cards.count()) {
    await expect(cards.first()).toContainText(/Admin|通知|评论|系统/);
  }
});

test("component market renders cards with sandbox and signature badges", async ({ page }) => {
  await page.goto("/admin/market");

  await expect(page.getByRole("heading", { name: "组件与区块市场" })).toBeVisible();

  const cards = page.locator(".market-card");
  await expect(cards.first()).toBeVisible();
  expect(await cards.count()).toBeGreaterThanOrEqual(2);

  // Component market items advertise their sandbox state and signature status.
  await expect(
    page.locator(".market-card .el-tag").filter({ hasText: /^沙箱$/ }).first()
  ).toBeVisible();
  await expect(
    page.locator(".market-card .el-tag").filter({ hasText: /^已签名$/ }).first()
  ).toBeVisible();
});
