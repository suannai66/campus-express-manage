import { test, expect } from "@playwright/test";
import { randomInt } from "node:crypto";

const demoCode = "482917";
const nextPhone = () => `139${String(randomInt(100000000)).padStart(8, "0")}`;
async function account(request) {
  const phone = nextPhone();
  await request.post("/api/auth/codes", {
    data: { phone, purpose: "register" },
  });
  expect(
    (
      await request.post("/api/auth/register", {
        data: { phone, code: demoCode },
      })
    ).status(),
  ).toBe(201);
  return phone;
}
async function signIn(page, phone, redirect = "/tasks") {
  await page.goto(`/login?redirect=${encodeURIComponent(redirect)}`);
  await page.getByLabel("手机号", { exact: true }).fill(phone);
  await page.getByRole("button", { name: "获取验证码" }).click();
  await expect(page.getByRole("status")).toContainText("验证码已准备好");
  await page.getByLabel("验证码", { exact: true }).fill(demoCode);
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await expect(page.getByRole("button", { name: "退出登录" })).toBeVisible();
}

test("注册、登录、刷新恢复、认证限制与退出撤销", async ({ page }) => {
  const phone = nextPhone();
  await page.goto("/register?redirect=%2Ftasks");
  await page.getByLabel("手机号", { exact: true }).fill(phone);
  await page.getByRole("button", { name: "获取验证码" }).click();
  await expect(page.getByRole("status")).toContainText("验证码已准备好");
  await page.getByLabel("验证码", { exact: true }).fill(demoCode);
  await page.getByRole("button", { name: "注册账号" }).click();
  await expect(page).toHaveURL(/\/login/);
  expect(
    await page.evaluate(() => sessionStorage.getItem("accessToken")),
  ).toBeNull();
  await signIn(page, phone);
  await expect(page).toHaveURL(/\/tasks$/);
  await expect(
    page.getByText("暂时没有匹配的任务", { exact: true }),
  ).toBeVisible();
  const token = await page.evaluate(() =>
    sessionStorage.getItem("accessToken"),
  );
  expect(token.split(".")).toHaveLength(3);
  expect(
    await page.evaluate(() => localStorage.getItem("accessToken")),
  ).toBeNull();
  await page.reload();
  await expect(page.locator(".topbar")).toContainText(phone);
  await page.goto("/publish");
  await expect(page.getByText("完成学生认证后，即可发布需求")).toBeVisible();
  await page.goto("/verification");
  await expect(page.getByText("未提交认证", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "退出登录" }).click();
  await expect(page).toHaveURL(/\/login$/);
  expect(
    await page.evaluate(() => sessionStorage.getItem("accessToken")),
  ).toBeNull();
  const old = await page.request.get("/api/auth/current", {
    headers: { Authorization: `Bearer ${token}` },
  });
  expect(old.status()).toBe(401);
});

test("错误验证码显示错误且发送倒计时生效", async ({ page, request }) => {
  await page.goto("/login");
  await page.getByLabel("手机号", { exact: true }).fill(await account(request));
  await page.getByRole("button", { name: "获取验证码" }).click();
  const requestCode = page.getByRole("button", {
    name: "获取验证码",
    exact: true,
  });
  await expect(requestCode).toBeDisabled();
  await expect(requestCode).toContainText(/秒后重试/);
  await page.getByLabel("验证码", { exact: true }).fill("000000");
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("验证码错误");
  expect(
    await page.evaluate(() => sessionStorage.getItem("accessToken")),
  ).toBeNull();
});

test("403 保留会话，退出失败可重试", async ({ page, request }) => {
  await signIn(page, await account(request));
  const token = await page.evaluate(() =>
    sessionStorage.getItem("accessToken"),
  );
  const response = await page.evaluate(async () => {
    const { request } = await import("/src/services/http.js");
    try {
      await request("/orders", {
        method: "POST",
        headers: { "Idempotency-Key": crypto.randomUUID() },
        body: JSON.stringify({
          company: "中通",
          code: "test",
          stationId: "station_cainiao",
          deliveryAreaId: "zone_qinyuan",
          address: "沁园",
          size: "small",
          weight: "1",
          tip: 0,
          expectedAt: new Date(Date.now() + 3600000).toISOString(),
        }),
      });
    } catch (error) {
      return error.status;
    }
  });
  expect(response).toBe(403);
  expect(await page.evaluate(() => sessionStorage.getItem("accessToken"))).toBe(
    token,
  );
  await page.route("**/api/auth/logout", (route) =>
    route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({
        code: "DEPENDENCY_UNAVAILABLE",
        detail: "服务暂不可用",
        fields: {},
      }),
    }),
  );
  await page.getByRole("button", { name: "退出登录" }).click();
  await expect(page.locator("#session-alert")).toContainText("退出失败");
  expect(await page.evaluate(() => sessionStorage.getItem("accessToken"))).toBe(
    token,
  );
  await page.unroute("**/api/auth/logout");
  await page.getByRole("button", { name: "退出登录" }).click();
  await expect(page).toHaveURL(/\/login$/);
});

test("失效会话清理并返回本站登录页", async ({ page }) => {
  await page.addInitScript(() =>
    sessionStorage.setItem("accessToken", "invalid-token"),
  );
  await page.goto("/tasks");
  await expect(page).toHaveURL(/\/login\?redirect=/);
  expect(new URL(page.url()).searchParams.get("redirect")).toBe("/tasks");
  // addInitScript 会在下一次导航再次注入；移除注入后独立核对响应清理。
  await page.evaluate(async () => {
    const { request } = await import("/src/services/http.js");
    try {
      await request("/auth/current");
    } catch {}
  });
  expect(
    await page.evaluate(() => sessionStorage.getItem("accessToken")),
  ).toBeNull();
});

test("站外 redirect 被拒绝，手机布局正常", async ({ page, request }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/login");
  await page.screenshot({ path: "test-results/identity-login-mobile.png", fullPage: true });
  await signIn(page, await account(request), "https://example.com/");
  await expect(page).toHaveURL("http://127.0.0.1:18142/");
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBeTruthy();
  await page.screenshot({
    path: "test-results/identity-mobile.png",
    fullPage: true,
  });
});
