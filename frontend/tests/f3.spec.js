import { test, expect } from "@playwright/test";
import fs from "node:fs/promises";

async function fillDraft(page) {
  await page.getByLabel(/^快递公司/).fill("中通快递");
  await page.getByLabel(/^取件点/).fill("菜鸟驿站");
  await page.getByLabel(/^取件码/).fill("1-2-3456");
  await page.getByLabel(/^包裹重量/).fill("1.2");
  await page.getByLabel(/^送达地址/).fill("实验楼 A 座 302 室");
  const time = new Date(Date.now() + 3 * 3600000);
  const local = new Date(time.getTime() - time.getTimezoneOffset() * 60000)
    .toISOString()
    .slice(0, 16);
  await page.getByLabel(/^期望送达时间/).fill(local);
  await page.getByLabel(/^小费金额/).fill("2.35");
  await page.getByLabel(/^备注/).fill("包裹易碎，请轻拿轻放");
}

test("F3 创建、恢复待支付订单及演示支付闭环", async ({ page }) => {
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.setViewportSize({ width: 1440, height: 1100 });
  await page.goto("/publish");
  await expect(
    page.getByText("订单会保存；身份与支付为模拟", { exact: false }),
  ).toBeVisible();
  await fillDraft(page);
  await expect(page.locator(".fee-total")).toContainText("¥5.35");
  await fs.mkdir("outputs", { recursive: true });
  await page.locator("h1").click();
  await page.evaluate(() => scrollTo(0, 0));
  await page.screenshot({ path: "outputs/f3-desktop.png", fullPage: true });
  await page.getByRole("button", { name: "创建订单", exact: true }).click();
  await expect(page).toHaveURL(/orderId=/);
  await expect(
    page.getByRole("heading", { name: "订单已创建，支付后发布" }),
  ).toBeVisible();
  const savedUrl = page.url();
  await page.reload();
  await expect(page.getByText("1-2-3456", { exact: false })).toBeVisible();
  await expect(page.locator(".order-details")).toContainText(
    "实验楼 A 座 302 室",
  );
  await page.getByRole("button", { name: "去支付 ¥5.35" }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.getByRole("button", { name: "稍后支付" }).click();
  await expect(page.getByRole("dialog")).not.toBeVisible();
  await page.getByRole("button", { name: "去支付 ¥5.35" }).click();
  await page.getByRole("button", { name: "确认演示支付", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "需求已发布，等待同学接单" }),
  ).toBeVisible();
  await expect(page.getByRole("dialog")).not.toBeVisible();
  await page.goto(savedUrl);
  await expect(page.locator(".order-result .soft-tag")).toHaveText("待接单");
  await page.getByRole("button", { name: "再发一单" }).click();
  await expect(page).toHaveURL(/\/publish$/);
  await expect(page.getByLabel(/^快递公司/)).toHaveValue("");
  expect(errors).toEqual([]);
});

test("F3 逐项校验和未登录、未认证引导", async ({ page }) => {
  await page.goto("/publish");
  await expect(
    page.getByRole("button", { name: "创建订单", exact: true }),
  ).toBeEnabled();
  await page.getByRole("button", { name: "创建订单", exact: true }).click();
  await expect(page.getByText("请填写快递公司", { exact: true })).toBeVisible();
  await expect(page.getByText("请填写送达地址", { exact: true })).toBeVisible();
  await page.getByLabel("体验身份").selectOption("unverified");
  await expect(
    page.getByRole("link", { name: "去认证", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "创建订单", exact: true }),
  ).toBeDisabled();
  await page.getByLabel("体验身份").selectOption("guest");
  await expect(
    page.getByRole("link", { name: "去登录", exact: true }),
  ).toHaveAttribute("href", /redirect/);
  await page.getByLabel("体验身份").selectOption("verified");
  await expect(
    page.getByRole("button", { name: "创建订单", exact: true }),
  ).toBeEnabled();
});

test("F3 创建失败保留表单，可重试", async ({ page }) => {
  await page.goto("/publish");
  await expect(
    page.getByRole("button", { name: "创建订单", exact: true }),
  ).toBeEnabled();
  await fillDraft(page);
  await page.route("**/api/orders", (route) =>
    route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({ detail: "服务暂时不可用，请稍后重试" }),
    }),
  );
  await page.getByRole("button", { name: "创建订单", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("服务暂时不可用");
  await expect(page.getByLabel(/^取件码/)).toHaveValue("1-2-3456");
  await expect(
    page.getByRole("button", { name: "创建订单", exact: true }),
  ).toBeEnabled();
});

test("F3 手机端发布表单与支付弹窗无溢出", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/publish");
  await expect(
    page.getByRole("button", { name: "创建订单", exact: true }),
  ).toBeEnabled();
  await fillDraft(page);
  await expect(page.locator(".fee-total")).toContainText("¥5.35");
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBeTruthy();
  await fs.mkdir("outputs", { recursive: true });
  await page.locator("h1").click();
  await page.evaluate(() => scrollTo(0, 0));
  await page.screenshot({ path: "outputs/f3-mobile.png", fullPage: true });
  await page.getByRole("button", { name: "创建订单", exact: true }).click();
  await page.getByRole("button", { name: "去支付 ¥5.35" }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBeTruthy();
});
