import { test, expect } from "@playwright/test";
const draft = (tip = 235) => ({
  company: "顺丰速运",
  code: "private-code",
  stationId: "station_sf",
  deliveryAreaId: "zone_zhuyuan",
  size: "medium",
  weight: "1",
  address: "private-room-302",
  expectedAt: new Date(Date.now() + 5 * 3600000).toISOString(),
  tip,
  note: "轻拿轻放",
});
const headers = (uid) => ({
  Authorization: `Bearer ${uid}`,
  "Idempotency-Key": crypto.randomUUID(),
});
async function seed(request, uid = "alice", tip = 235) {
  const result = await request.post("/api/orders", {
    data: draft(tip),
    headers: headers(uid),
  });
  expect(result.status()).toBe(201);
  const order = await result.json();
  const reserve = await request.post(
    `/api/orders/${order.orderId}/payment-request`,
    { data: { version: order.version }, headers: headers(uid) },
  );
  const reservation = await reserve.json();
  const payment = await request.post("/api/pay/prepay", {
    data: {
      orderId: order.orderId,
      paymentRequestId: reservation.paymentRequestId,
    },
    headers: headers(uid),
  });
  expect(payment.ok()).toBeTruthy();
  return order;
}
async function visit(page, uid = "bob") {
  await page.addInitScript(
    (value) => sessionStorage.setItem("accessToken", value),
    uid,
  );
  await page.goto("/tasks");
}
test("F4 组合筛选和公开详情不泄露取件码、门牌", async ({ page, request }) => {
  await seed(request);
  await visit(page);
  await page.getByLabel("取件点", { exact: true }).selectOption("station_sf");
  await page
    .getByLabel("送达区域", { exact: true })
    .selectOption("zone_zhuyuan");
  await page.getByLabel("小费下限（元）").fill("2.35");
  await page.getByLabel("小费上限（元）").fill("2.35");
  const query = page.waitForRequest(
    (r) => r.url().includes("scope=hall") && r.url().includes("tipMin=235"),
  );
  await page.getByRole("button", { name: "筛选任务" }).click();
  await query;
  await expect(page.locator(".task-card").first()).toBeVisible();
  await page.getByRole("button", { name: "查看详情" }).first().click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await expect(page.getByRole("dialog")).toContainText("竹园");
  await expect(page.locator("main")).not.toContainText("private-code");
  await expect(page.locator("main")).not.toContainText("private-room-302");
  await page.getByRole("button", { name: "知道了" }).click();
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({
    path: "test-results/f4-desktop.png",
    fullPage: true,
  });
});
test("F4 空态和筛选边界", async ({ page }) => {
  await visit(page);
  await page.getByLabel("小费下限（元）").fill("900");
  await page.getByLabel("小费上限（元）").fill("1");
  await page.getByRole("button", { name: "筛选任务" }).click();
  await expect(page.getByRole("alert")).toHaveText("小费下限不能大于上限。");
  await page.getByLabel("小费上限（元）").fill("999");
  await page.getByRole("button", { name: "筛选任务" }).click();
  await expect(
    page.getByText("暂时没有匹配的任务", { exact: true }),
  ).toBeVisible();
});
test("F4 列表错误保留错误态，不显示空任务结论", async ({ page, request }) => {
  await seed(request);
  await visit(page);
  await expect(page.locator(".task-card").first()).toBeVisible();
  await page.route("**/api/orders?*", (route) =>
    route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({
        code: "DEPENDENCY_UNAVAILABLE",
        detail: "订单查询暂不可用",
        fields: {},
      }),
    }),
  );
  await page.getByRole("button", { name: "刷新任务" }).click();
  await expect(page.getByRole("alert")).toContainText("订单查询暂不可用");
  await expect(
    page.getByText("暂时没有匹配的任务", { exact: true }),
  ).not.toBeVisible();
});
test("F4 每 10 秒刷新，离开页面停止轮询", async ({ page, request }) => {
  await seed(request);
  let count = 0;
  page.on("request", (r) => {
    if (r.url().includes("/api/orders?scope=hall")) count++;
  });
  await page.clock.install();
  await visit(page);
  await expect(page.locator(".task-card").first()).toBeVisible();
  const before = count;
  await page.clock.fastForward(10001);
  await expect.poll(() => count).toBeGreaterThan(before);
  await page.getByRole("link", { name: "首页概览" }).click();
  await expect(page.locator(".hall-filters")).toHaveCount(0);
  const left = count;
  await page.clock.fastForward(30001);
  expect(count).toBe(left);
});
test("F4 移动端无横向溢出", async ({ page, request }) => {
  await seed(request);
  await page.setViewportSize({ width: 390, height: 844 });
  await visit(page);
  await expect(page.locator(".task-card").first()).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBeTruthy();
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: "test-results/f4-mobile.png", fullPage: true });
});
