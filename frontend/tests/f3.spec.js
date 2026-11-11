import { test, expect } from "@playwright/test";
export async function login(page, token = "alice") {
  await page.addInitScript(
    (value) =>
      sessionStorage.getItem("accessToken") ||
      sessionStorage.setItem("accessToken", value),
    token,
  );
}
export async function fillDraft(page) {
  await page.getByLabel(/快递公司/).fill("中通快递");
  await page.getByLabel(/^取件点/).selectOption("station_cainiao");
  await page.getByLabel(/^取件码/).fill("A-1234");
  await page.getByLabel(/送达区域/).selectOption("zone_qinyuan");
  await page.getByLabel(/详细送达地址/).fill("沁园 3 栋 302 室");
  await page
    .getByLabel(/期望送达时间/)
    .fill(new Date(Date.now() + 11 * 3600000).toISOString().slice(0, 16));
  await page.getByLabel(/小费金额/).fill("2.35");
}
test("F3 使用目录、整数分，创建预占并通过支付事件发布", async ({ page }) => {
  await login(page);
  await page.goto("/publish");
  await expect(
    page.getByText("北京时间（UTC+8），未来七天内", { exact: true }),
  ).toBeVisible();
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await fillDraft(page);
  await expect(page.locator(".fee-total")).toContainText("4.35");
  const creation = page.waitForRequest(
    (req) =>
      req.method() === "POST" && new URL(req.url()).pathname === "/api/orders",
  );
  await page.getByRole("button", { name: "创建订单", exact: true }).click();
  const body = (await creation).postDataJSON();
  expect(body.tip).toBe(235);
  expect(body.weight).toBe("1");
  expect(body.size).toBe("small");
  expect(body).not.toHaveProperty("uid");
  await expect(
    page.getByRole("heading", { name: "订单已创建，支付后发布" }),
  ).toBeVisible();
  const url = page.url();
  await page.reload();
  await expect(page.locator(".order-details")).toContainText("A-1234");
  const reserve = page.waitForRequest((req) =>
    req.url().endsWith("/payment-request"),
  );
  await page.getByRole("button", { name: /去支付/ }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.getByRole("button", { name: "确认支付", exact: true }).click();
  expect((await reserve).postDataJSON().version).toBe(1);
  await expect(page.locator(".order-result .soft-tag")).toHaveText("待接单");
  expect(page.url()).toBe(url);
  expect(errors).toEqual([]);
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({
    path: "test-results/f3-desktop.png",
    fullPage: true,
  });
});
test("F3 创建响应延迟时离开页面，不跳回且订单仍保存", async ({
  page,
  request,
}) => {
  await login(page);
  await page.goto("/publish");
  await fillDraft(page);
  let release, captured;
  const gate = new Promise((resolve) => {
    release = resolve;
  });
  const received = new Promise((resolve) => {
    captured = resolve;
  });
  await page.route("**/api/orders", async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    const response = await route.fetch();
    captured();
    await gate;
    await route.fulfill({ response });
  });
  await page.getByRole("button", { name: "创建订单", exact: true }).click();
  await received;
  await page.getByRole("link", { name: "代取大厅", exact: true }).click();
  await expect(page).toHaveURL(/\/tasks$/);
  let staleQueries = 0;
  page.on("request", (r) => {
    if (r.url().includes("/api/orders?scope=mine")) staleQueries++;
  });
  const completed = page.waitForResponse(
    (r) =>
      r.request().method() === "POST" &&
      new URL(r.url()).pathname === "/api/orders",
  );
  release();
  const response = await completed;
  await response.finished();
  // 让响应处理和 Vue 更新跨过浏览器帧，检查卸载页面的回调没有发起导航或查询。
  await page.evaluate(
    () =>
      new Promise((resolve) =>
        requestAnimationFrame(() => requestAnimationFrame(resolve)),
      ),
  );
  await expect(page).toHaveURL(/\/tasks$/);
  expect(staleQueries).toBe(0);
  const order = await response.json();
  const saved = await request.get(`/api/orders/${order.orderId}`, {
    headers: { Authorization: "Bearer alice" },
  });
  expect(saved.status()).toBe(200);
  expect((await saved.json()).status).toBe("pending_payment");
});

for (const staleKind of ["旧快照", "旧错误"]) {
  test(`F3 ${staleKind}晚返回不覆盖已付款状态`, async ({ page, request }) => {
    const response = await request.post("/api/orders", {
      headers: {
        Authorization: "Bearer alice",
        "Idempotency-Key": crypto.randomUUID(),
      },
      data: {
        company: "刷新乱序演示",
        code: "STALE-1234",
        stationId: "station_cainiao",
        deliveryAreaId: "zone_qinyuan",
        address: "演示楼302",
        size: "small",
        weight: "1",
        tip: 235,
        expectedAt: new Date(Date.now() + 5 * 3600000).toISOString(),
      },
    });
    expect(response.status()).toBe(201);
    const order = await response.json();
    await login(page);
    await page.goto(`/publish?orderId=${order.orderId}`);
    await expect(page.locator(".order-result .soft-tag")).toHaveText("待支付");
    let release,
      captured,
      fulfilled,
      first = true,
      oldSnapshot;
    const gate = new Promise((resolve) => {
      release = resolve;
    });
    const received = new Promise((resolve) => {
      captured = resolve;
    });
    const replied = new Promise((resolve) => {
      fulfilled = resolve;
    });
    const pattern = `**/api/orders/${order.orderId}`;
    await page.route(pattern, async (route) => {
      if (!first) return route.continue();
      first = false;
      const old = await route.fetch();
      oldSnapshot = await old.json();
      captured();
      await gate;
      if (staleKind === "旧错误") {
        await route.fulfill({
          status: 503,
          json: {
            code: "DEPENDENCY_UNAVAILABLE",
            detail: "过期请求失败",
            fields: {},
          },
        });
      } else await route.fulfill({ response: old });
      fulfilled();
    });
    await page.getByRole("button", { name: "刷新状态", exact: true }).click();
    await received;
    await expect(
      page.getByRole("button", { name: "正在刷新…", exact: true }),
    ).toBeDisabled();
    // 付款后的刷新必须能替代仍在等待的手动刷新。
    await page.getByRole("button", { name: /去支付/ }).click();
    await page.getByRole("button", { name: "确认支付", exact: true }).click();
    await expect(page.locator(".order-result .soft-tag")).toHaveText("待接单");
    const finished = page.waitForResponse(
      (r) => new URL(r.url()).pathname === `/api/orders/${order.orderId}`,
    );
    release();
    await (await finished).finished();
    await replied;
    await page.evaluate(
      () =>
        new Promise((resolve) =>
          requestAnimationFrame(() => requestAnimationFrame(resolve)),
        ),
    );
    await expect(page.locator(".order-result .soft-tag")).toHaveText("待接单");
    await expect(
      page.getByRole("button", { name: /去支付|查询并继续支付/ }),
    ).toHaveCount(0);
    await expect(page.locator(".error-banner")).not.toBeVisible();
    if (staleKind === "旧快照") {
      // 即使最新请求返回低版本快照，也不能让订单版本回退。
      await page.unroute(pattern);
      await page.route(pattern, (route) =>
        route.fulfill({ json: oldSnapshot }),
      );
      const refreshed = page.waitForResponse(
        (r) => new URL(r.url()).pathname === `/api/orders/${order.orderId}`,
      );
      await page.getByRole("button", { name: "刷新状态", exact: true }).click();
      await (await refreshed).finished();
      await expect(
        page.getByRole("button", { name: "刷新状态", exact: true }),
      ).toBeEnabled();
      await expect(page.locator(".order-result .soft-tag")).toHaveText(
        "待接单",
      );
    }
  });
}

test("F3 必填逐项提示、未认证引导", async ({ page }) => {
  await login(page);
  await page.goto("/publish");
  await page.getByRole("button", { name: "创建订单", exact: true }).click();
  await expect(page.getByText("请填写快递公司", { exact: true })).toBeVisible();
  await expect(page.getByText("请填写送达区域", { exact: true })).toBeVisible();
  await page.evaluate(() =>
    sessionStorage.setItem("accessToken", "unverified"),
  );
  await page.reload();
  await expect(page.getByRole("link", { name: "去认证" })).toBeVisible();
  await expect(
    page.getByRole("button", { name: "创建订单", exact: true }),
  ).toBeDisabled();
  expect(await page.evaluate(() => sessionStorage.getItem("accessToken"))).toBe(
    "unverified",
  );
});
test("F3 未登录回到登录页，redirect 为站内路径", async ({ page }) => {
  await page.goto("/publish?orderId=example");
  await expect(page).toHaveURL(/\/login\?redirect=/);
  expect(new URL(page.url()).searchParams.get("redirect")).toBe(
    "/publish?orderId=example",
  );
});
test("F3 支付网络失败保留 paying，重新进入可恢复", async ({ page }) => {
  await login(page);
  await page.goto("/publish");
  await fillDraft(page);
  await page.getByRole("button", { name: "创建订单", exact: true }).click();
  await expect(page.locator(".order-result")).toBeVisible();
  await page.route("**/api/pay/prepay", (route) => route.abort("failed"));
  await page.getByRole("button", { name: /去支付/ }).click();
  await page.getByRole("button", { name: "确认支付", exact: true }).click();
  await expect(page.locator(".order-result .soft-tag")).toHaveText(
    "支付处理中",
  );
  await page.reload();
  await expect(
    page.getByRole("button", { name: "查询并继续支付" }),
  ).toBeVisible();
  await page.unroute("**/api/pay/prepay");
  await page.getByRole("button", { name: "查询并继续支付" }).click();
  await page.getByRole("button", { name: "确认支付", exact: true }).click();
  await expect(page.locator(".order-result .soft-tag")).toHaveText("待接单");
});
test("F3 手机布局保留表单和费用明细", async ({ page }) => {
  await login(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/publish");
  await fillDraft(page);
  await expect(page.locator(".fee-total")).toContainText("4.35");
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBeTruthy();
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: "test-results/f3-mobile.png", fullPage: true });
});
