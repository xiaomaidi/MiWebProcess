import type { APIRequestContext, Page } from "@playwright/test";

/** Seeded development administrator used by the regression suite. */
export const ADMIN_CREDENTIALS = {
  username: "admin",
  password: "admin123",
} as const;

/**
 * Log in through the Django token endpoint. Using the API keeps tests fast and
 * independent from the login form; the token is injected into localStorage
 * before the Vue app boots, so the router guard sees an authenticated session.
 */
export async function fetchAdminToken(request: APIRequestContext): Promise<string> {
  const response = await request.post("/api/auth/token/", {
    data: ADMIN_CREDENTIALS,
  });
  if (!response.ok()) {
    throw new Error(
      `Admin API login failed: HTTP ${response.status()} — ${await response.text()}`
    );
  }
  const payload = (await response.json()) as { access?: string };
  if (!payload.access) {
    throw new Error("Admin API login response did not contain an access token");
  }
  return payload.access;
}

/** Seed `wp_token` before every navigation of the page. */
export async function loginAsAdmin(page: Page, request: APIRequestContext): Promise<void> {
  const token = await fetchAdminToken(request);
  await page.addInitScript((value) => {
    window.localStorage.setItem("wp_token", value);
  }, token);
}
