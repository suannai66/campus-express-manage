import { test, expect } from "@playwright/test";
import { randomInt } from "node:crypto";

const demoCode = "482917";
const nextPhone = () => `139${String(randomInt(100000000)).padStart(8, "0")}`;

async function skipToPhone(page) {
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "跳到主要内容" })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("main")).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(page.getByLabel("手机号", { exact: true })).toBeFocused();
}

async function tabToCodeButton(page) {
  await page.keyboard.press("Tab");
  await expect(page.getByLabel("验证码", { exact: true })).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(
    page.getByRole("button", { name: "获取验证码", exact: true }),
  ).toBeFocused();
}

async function enterValidCode(page) {
  await expect(page.getByRole("status")).toContainText("验证码已准备好");
  await expect(page.getByLabel("验证码", { exact: true })).toBeFocused();
  await page.keyboard.type(demoCode);
  await page.keyboard.press("Enter");
}

test("键盘可注册、登录、返回原页面并退出", async ({ page }) => {
  await page.goto("/register?redirect=%2Ftasks");
  await expect(
    page.getByRole("heading", { level: 1, name: "注册账号" }),
  ).toBeVisible();
  await skipToPhone(page);
  await page.keyboard.type(nextPhone());
  await tabToCodeButton(page);
  await page.keyboard.press("Enter");
  await enterValidCode(page);

  await expect(
    page.getByRole("heading", { level: 1, name: "登录" }),
  ).toBeVisible();
  await expect(page.getByRole("status")).toContainText("注册成功");
  await expect(page.getByRole("main")).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(page.getByLabel("手机号", { exact: true })).toBeFocused();
  await tabToCodeButton(page);
  await page.keyboard.press("Enter");
  await enterValidCode(page);

  await expect(page).toHaveURL(/\/tasks$/);
  await expect(page.getByRole("main")).toBeFocused();
  await page.keyboard.press("Shift+Tab");
  await expect(page.getByRole("button", { name: "退出登录" })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(
    page.getByRole("heading", { level: 1, name: "登录" }),
  ).toBeVisible();
});

test("字段错误关联到输入框，发送等待时保留焦点且不会重复请求", async ({
  page,
  request,
}) => {
  const phoneNumber = nextPhone();
  await request.post("/api/auth/codes", {
    data: { phone: phoneNumber, purpose: "register" },
  });
  expect(
    (
      await request.post("/api/auth/register", {
        data: { phone: phoneNumber, code: demoCode },
      })
    ).status(),
  ).toBe(201);

  await page.goto("/login");
  await skipToPhone(page);
  const phone = page.getByLabel("手机号", { exact: true });
  const code = page.getByLabel("验证码", { exact: true });
  const requestCode = page.getByRole("button", {
    name: "获取验证码",
    exact: true,
  });
  const alert = page.getByRole("alert");

  await tabToCodeButton(page);
  await page.keyboard.press("Enter");
  await expect(phone).toBeFocused();
  await expect(phone).toHaveAttribute("aria-invalid", "true");
  await expect(phone).toHaveAccessibleDescription("请输入正确的 11 位手机号");
  await expect(alert).toContainText("请检查手机号");
  await page.keyboard.type(phoneNumber);

  let sendCalls = 0;
  let release;
  const responseReady = new Promise((resolve) => {
    release = resolve;
  });
  await page.route("**/api/auth/codes", async (route) => {
    sendCalls += 1;
    await responseReady;
    await route.continue();
  });
  try {
    await tabToCodeButton(page);
    await page.keyboard.press("Enter");
    await expect(requestCode).toBeDisabled();
    await expect(requestCode).toBeFocused();
    await expect(requestCode).toContainText("正在获取");
    await page.keyboard.press("Enter");
  } finally {
    release();
  }
  await expect(page.getByRole("status")).toContainText("验证码已准备好");
  await expect(requestCode).toContainText(/秒后重试/);
  await expect(code).toBeFocused();
  expect(sendCalls).toBe(1);

  await page.keyboard.type("000000");
  await page.keyboard.press("Tab");
  await expect(requestCode).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(
    page.getByRole("button", { name: "登录", exact: true }),
  ).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(alert).toContainText("验证码错误");
  await expect(code).toBeFocused();
  await expect(code).toHaveAttribute("aria-invalid", "true");
  await expect(code).toHaveAccessibleDescription(
    "验证码错误，连续五次错误后失效",
  );
  await page.keyboard.press("ControlOrMeta+a");
  await page.keyboard.type(demoCode);
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/$/);
});
