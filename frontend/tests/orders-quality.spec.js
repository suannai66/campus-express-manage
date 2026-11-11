import { test, expect } from "@playwright/test";

const headers = (uid = "alice") => ({
  Authorization: `Bearer ${uid}`,
  "Idempotency-Key": crypto.randomUUID(),
});
const draft = (extra = {}) => ({
  company: "质量测试快递",
  code: "QUALITY-PRIVATE-CODE",
  stationId: "station_cainiao",
  deliveryAreaId: "zone_qinyuan",
  address: "QUALITY-PRIVATE-ROOM",
  size: "small",
  weight: "1",
  expectedAt: new Date(Date.now() + 5 * 3600000).toISOString(),
  tip: 0,
  ...extra,
});
async function login(page, uid = "alice") {
  await page.addInitScript((token) => sessionStorage.setItem("accessToken", token), uid);
}
async function fillDraft(page) {
  await page.getByLabel(/快递公司/).fill("质量测试快递");
  await page.getByLabel(/^取件点/).selectOption("station_cainiao");
  await page.getByLabel(/^取件码/).fill("QUALITY-PRIVATE-CODE");
  await page.getByLabel(/送达区域/).selectOption("zone_qinyuan");
  await page.getByLabel(/详细送达地址/).fill("QUALITY-PRIVATE-ROOM");
  // 显式生成北京时间输入，不依赖浏览器或执行机器的时区。
  await page.getByLabel(/期望送达时间/).fill(
    new Date(Date.now() + (5 + 8) * 3600000).toISOString().slice(0, 16),
  );
}
async function seed(request, extra = {}) {
  const created = await request.post("/api/orders", { headers: headers(), data: draft(extra) });
  expect(created.status()).toBe(201);
  const order = await created.json();
  const reserved = await request.post(`/api/orders/${order.orderId}/payment-request`, {
    headers: headers(), data: { version: order.version },
  });
  expect(reserved.ok()).toBeTruthy();
  const reservation = await reserved.json();
  const paid = await request.post("/api/pay/prepay", {
    headers: headers(),
    data: { orderId: order.orderId, paymentRequestId: reservation.paymentRequestId },
  });
  expect(paid.ok()).toBeTruthy();
  return order;
}

test("BQ23 用户输入按文本显示，列表及弹窗不执行 HTML", async ({ page, request }) => {
  const note = '<img src=x onerror="window.__qualityXss=1">';
  const order = await seed(request, { company: "<b>质量测试</b>", note });
  await login(page, "bob");
  await page.goto("/tasks");
  const card = page.locator(".task-card").filter({ hasText: order.company });
  await expect(card).toBeVisible();
  await expect(card.locator("b")).toHaveCount(0);
  await card.getByRole("button", { name: "查看详情" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText(note);
  await expect(dialog.locator("img")).toHaveCount(0);
  expect(await page.evaluate(() => window.__qualityXss)).toBeUndefined();
  await expect(dialog).not.toContainText("QUALITY-PRIVATE-CODE");
  await expect(dialog).not.toContainText("QUALITY-PRIVATE-ROOM");
});

test("BQ24 创建已提交但响应丢失，原键重试恢复同一订单", async ({ page, request }) => {
  await login(page);
  await page.goto("/publish");
  await fillDraft(page);
  const keys = [];
  let saved;
  await page.route("**/api/orders", async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    keys.push(route.request().headers()["idempotency-key"]);
    const response = await route.fetch();
    expect(response.status()).toBe(201);
    if (!saved) {
      saved = await response.json();
      return route.abort("failed");
    }
    await route.fulfill({ response });
  });
  const submit = page.getByRole("button", { name: "创建订单", exact: true });
  await submit.click();
  await expect(page.getByRole("alert")).toBeVisible();
  await expect(submit).toBeEnabled();
  await submit.click();
  await expect(page).toHaveURL(new RegExp(`orderId=${saved.orderId}`));
  expect(keys).toHaveLength(2);
  expect(keys[0]).toBeTruthy();
  expect(keys[1]).toBe(keys[0]);
  const mine = await request.get("/api/orders?scope=mine&pageSize=100", { headers: headers() });
  const items = (await mine.json()).items;
  expect(items.filter((row) => row.orderId === saved.orderId)).toHaveLength(1);
});

test("BQ25 创建请求处理中重复点击，只发送一次创建请求", async ({ page }) => {
  await login(page);
  await page.goto("/publish");
  await fillDraft(page);
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  let requests = 0;
  await page.route("**/api/orders", async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    requests++;
    await gate;
    await route.continue();
  });
  const submit = page.locator('button[type="submit"]');
  try {
    await submit.evaluate((button) => { button.click(); button.click(); button.click(); });
    await expect.poll(() => requests).toBe(1);
    await expect(submit).toBeDisabled();
  } finally {
    release();
  }
  await expect(page.locator(".order-result")).toBeVisible();
  expect(requests).toBe(1);
});

test("BQ26 大厅弹窗可用键盘打开关闭并恢复焦点", async ({ page, request }) => {
  const order = await seed(request, { company: `键盘${crypto.randomUUID().slice(0, 8)}` });
  await login(page, "bob");
  await page.goto("/tasks");
  const button = page.locator(".task-card").filter({ hasText: order.company })
    .getByRole("button", { name: "查看详情" });
  await button.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("dialog")).toBeVisible();
  await expect(page.getByRole("button", { name: "关闭详情" })).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).not.toBeVisible();
  await expect(button).toBeFocused();
});

test("BQ27 非 JSON 服务故障显示可恢复错误，重试后正常展示", async ({ page, request }) => {
  const order = await seed(request, { company: `恢复${crypto.randomUUID().slice(0, 8)}` });
  await login(page, "bob");
  const pattern = "**/api/orders?*";
  await page.route(pattern, (route) => route.fulfill({
    status: 503, contentType: "text/html", body: "<html>proxy unavailable</html>",
  }));
  await page.goto("/tasks");
  await expect(page.getByRole("alert")).toContainText("请求失败（503）");
  await expect(page.getByText("暂时没有匹配的任务", { exact: true })).not.toBeVisible();
  expect(await page.evaluate(() => sessionStorage.getItem("accessToken"))).toBe("bob");
  await page.unroute(pattern);
  await page.getByRole("button", { name: "重新加载" }).click();
  await expect(page.locator(".task-card").filter({ hasText: order.company })).toBeVisible();
  await expect(page.getByRole("alert")).not.toBeVisible();
});

for (const width of [320, 768, 1440]) {
  test(`BQ28-${width} 发布页及大厅弹窗在 ${width}px 宽度下可操作`, async ({ page, request }) => {
    const order = await seed(request, { company: `布局${width}-${crypto.randomUUID().slice(0, 8)}` });
    await login(page, "bob");
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/publish");
    await fillDraft(page);
    await expect(page.getByRole("button", { name: "创建订单", exact: true })).toBeEnabled();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
    await page.goto("/tasks");
    await page.locator(".task-card").filter({ hasText: order.company })
      .getByRole("button", { name: "查看详情" }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    const box = await dialog.boundingBox();
    expect(box.x).toBeGreaterThanOrEqual(0);
    expect(box.x + box.width).toBeLessThanOrEqual(width);
    expect(await dialog.evaluate((node) => node.scrollWidth <= node.clientWidth)).toBeTruthy();
    await page.getByRole("button", { name: "知道了" }).click();
    await expect(dialog).not.toBeVisible();
  });
}
