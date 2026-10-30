import { test, expect } from "@playwright/test";
import fs from "node:fs/promises";

const localInput = (date) =>
  new Date(date.getTime() - date.getTimezoneOffset() * 60000)
    .toISOString()
    .slice(0, 16);

test("F4 数据库任务组合筛选、详情和手机布局", async ({ page }) => {
  const runtimeErrors = [];
  page.on("pageerror", (error) => runtimeErrors.push(error.message));
  await page.setViewportSize({ width: 1440, height: 1050 });
  await page.goto("/tasks");
  await page.getByRole("button", { name: "添加演示任务", exact: true }).click();
  await expect(page.locator(".task-card")).toHaveCount(3);
  await expect(page.locator(".hall-summary")).toContainText("3 条");
  await fs.mkdir("outputs", { recursive: true });
  await page.locator("h1").click();
  await page.screenshot({ path: "outputs/f4-desktop.png", fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.evaluate(() => scrollTo(0, 0));
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBeTruthy();
  await page.screenshot({
    path: "outputs/f4-mobile.png",
    fullPage: true,
    animations: "disabled",
  });
  await page.setViewportSize({ width: 1440, height: 1050 });
  await page.getByLabel(/^取件点/).selectOption("菜鸟驿站");
  await page.getByLabel("送达地址", { exact: true }).fill("实验楼");
  await page.getByLabel("小费下限（元）").fill("3");
  await page.getByLabel("小费上限（元）").fill("3");
  await page
    .getByLabel("送达时间从")
    .fill(localInput(new Date(Date.now() + 3600000)));
  await page
    .getByLabel("送达时间至")
    .fill(localInput(new Date(Date.now() + 3 * 3600000)));
  await page.getByRole("button", { name: "筛选任务", exact: true }).click();
  await expect(page.locator(".task-card")).toHaveCount(1);
  await expect(page.locator(".task-card")).toContainText("实验楼 A 座 302 室");
  const response = page.waitForResponse(
    (response) =>
      response.url().includes("/api/orders/hall/") &&
      response.request().method() === "GET",
  );
  await page.getByRole("button", { name: "查看详情" }).click();
  const detail = await (await response).json();
  expect(detail).not.toHaveProperty("code");
  await expect(page.getByRole("dialog")).toContainText("实验楼 A 座 302 室");
  await expect(page.getByRole("dialog")).toContainText("取件码将在接单后提供");
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).not.toBeVisible();
  await page.getByRole("button", { name: "重置筛选", exact: true }).click();
  await expect(page.locator(".task-card")).toHaveCount(3);
  await page.getByLabel("送达地址", { exact: true }).fill("不存在的地址%");
  await page.getByRole("button", { name: "筛选任务", exact: true }).click();
  await expect(
    page.getByText("暂时没有匹配的任务", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "清除筛选", exact: true }).click();
  await expect(page.locator(".task-card")).toHaveCount(3);
  await page.getByLabel("小费下限（元）").fill("9");
  await page.getByLabel("小费上限（元）").fill("3");
  await page.getByRole("button", { name: "筛选任务", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("小费下限不能大于上限");
  expect(runtimeErrors).toEqual([]);
});

test("F4 排除自己发布的订单，未登录不能查询", async ({ page }) => {
  const created = await page.request.post("/api/orders", {
    headers: { "Idempotency-Key": crypto.randomUUID() },
    data: {
      company: "自己的快递",
      code: "private-code",
      station: "菜鸟驿站",
      size: "小件",
      weight: "1",
      address: "自己的实验楼",
      expectedAt: new Date(Date.now() + 4 * 3600000).toISOString(),
      tip: "5",
      note: "自己的需求",
    },
  });
  expect(created.ok()).toBeTruthy();
  const order = await created.json();
  await page.request.post(`/api/orders/${order.orderId}/demo-pay`);
  await page.goto("/tasks");
  await expect(page.locator(".task-card")).toHaveCount(3);
  await expect(
    page.locator(".task-card").filter({ hasText: "自己的快递" }),
  ).toHaveCount(0);
  await page.getByLabel("体验身份").selectOption("guest");
  await expect(
    page.getByRole("link", { name: "去登录", exact: true }),
  ).toBeVisible();
  await expect(page.locator(".task-card")).toHaveCount(0);
  expect((await page.request.get("/api/orders?status=pending")).status()).toBe(
    401,
  );
});

test("F4 请求失败展示错误而非零条任务，恢复后可继续查询", async ({ page }) => {
  await page.route("**/api/orders?**", (route) =>
    route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({ detail: "任务服务暂不可用" }),
    }),
  );
  await page.goto("/tasks");
  await expect(page.getByRole("alert")).toContainText("任务服务暂不可用");
  await expect(
    page.getByText("暂时没有匹配的任务", { exact: true }),
  ).not.toBeVisible();
  await expect(page.locator(".hall-summary .soft-tag")).toHaveCount(0);
  await page.unroute("**/api/orders?**");
  await page.getByRole("button", { name: "重新加载", exact: true }).click();
  await expect(page.locator(".task-card")).toHaveCount(3);
});

test("F4 外部状态变化十秒内刷新，演示取消移除任务", async ({ page }) => {
  await page.goto("/tasks");
  await expect(page.locator(".task-card")).toHaveCount(3);
  const rows = await (
    await page.request.get("/api/orders?status=pending")
  ).json();
  await page.getByRole("button", { name: "查看详情" }).first().click();
  await expect(page.getByRole("dialog")).toBeVisible();
  // 在页面外投递状态，必须依靠大厅自身的定时刷新感知。
  const changed = await page.request.post(
    `/api/orders/demo/hall/${rows.items[0].orderId}/status`,
    { data: { status: "accepted" } },
  );
  expect(changed.ok()).toBeTruthy();
  await expect(page.locator(".task-card")).toHaveCount(2, { timeout: 16000 });
  await expect(page.getByRole("dialog")).not.toBeVisible();
  await page.getByRole("button", { name: "查看详情" }).first().click();
  await page.getByRole("button", { name: "模拟取消", exact: true }).click();
  await expect(page.locator(".task-card")).toHaveCount(1);
  await expect(page.getByRole("dialog")).not.toBeVisible();
  await expect(page.getByRole("status")).toContainText("已模拟取消");
  await page.getByRole("button", { name: "添加演示任务", exact: true }).click();
  await expect(page.locator(".task-card")).toHaveCount(1);
});
