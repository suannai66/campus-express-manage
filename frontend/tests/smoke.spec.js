import { test, expect } from "@playwright/test";

test("模块入口均可直接访问且无运行错误", async ({ page }) => {
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  for (const path of [
    "/",
    "/tasks",
    "/publish",
    "/orders",
    "/reviews",
    "/wallet",
    "/verification",
    "/login",
    "/register",
    "/admin/verification",
    "/missing",
  ]) {
    await page.goto(path);
    await expect(page.locator("main")).toBeVisible();
    await expect(page.locator("main")).not.toBeEmpty();
  }
  expect(errors).toEqual([]);
});

test("首页示例详情预览", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator(".task-card")).toHaveCount(3);
  await page.getByRole("button", { name: "查看详情" }).first().click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.getByRole("button", { name: "知道了" }).click();
  await expect(page.getByRole("dialog")).not.toBeVisible();
});

test("移动端可导航，页面无横向溢出", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await page.getByRole("button", { name: "切换导航" }).click();
  await page
    .getByRole("navigation")
    .getByRole("link", { name: "我的钱包" })
    .click();
  await expect(page).toHaveURL(/wallet/);
  await expect(page.locator(".sidebar")).not.toHaveClass(/expanded/);
  for (const path of [
    "/",
    "/tasks",
    "/publish",
    "/verification",
    "/login",
    "/orders",
  ]) {
    await page.goto(path);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBeTruthy();
  }
});
