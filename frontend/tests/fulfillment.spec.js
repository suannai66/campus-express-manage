import { test, expect } from "@playwright/test";
import { randomInt } from "node:crypto";
import { readFileSync } from "node:fs";

const photo = readFileSync(
  new URL("./fixtures/学生证样例.png", import.meta.url),
);
const code = "482917";
let admin;
const auth = (user) => ({ Authorization: `Bearer ${user.accessToken}` });
const keyed = (user) => ({
  ...auth(user),
  "Idempotency-Key": crypto.randomUUID(),
});
async function login(request, phone) {
  expect(
    (
      await request.post("/api/auth/codes", {
        data: { phone, purpose: "login" },
      })
    ).status(),
  ).toBe(200);
  const response = await request.post("/api/auth/login", {
    data: { phone, code },
  });
  expect(response.status()).toBe(200);
  return response.json();
}
async function student(request) {
  const phone = `139${String(randomInt(100000000)).padStart(8, "0")}`;
  await request.post("/api/auth/codes", {
    data: { phone, purpose: "register" },
  });
  expect(
    (
      await request.post("/api/auth/register", { data: { phone, code } })
    ).status(),
  ).toBe(201);
  const user = await login(request, phone);
  admin ||= await login(request, "13900999998");
  const submitted = await request.post("/api/auth/verification-applications", {
    headers: auth(user),
    multipart: {
      realName: "履约测试同学",
      studentNo: "2026001234",
      photo: { name: "sample.png", mimeType: "image/png", buffer: photo },
    },
  });
  expect(submitted.status()).toBe(201);
  const approved = await request.post(
    `/api/admin/verification-applications/${(await submitted.json()).applicationId}/review`,
    {
      headers: auth(admin),
      data: { decision: "approved", rejectReason: null, version: 1 },
    },
  );
  expect(approved.status()).toBe(200);
  return user;
}
async function create(request, user, paid = true) {
  const result = await request.post("/api/orders", {
    headers: keyed(user),
    data: {
      company: `测试快递${randomInt(100000)}`,
      code: "C-123456",
      stationId: "station_cainiao",
      deliveryAreaId: "zone_qinyuan",
      size: "small",
      weight: "1",
      address: "测试楼302",
      tip: 235,
      expectedAt: new Date(Date.now() + 3600000).toISOString(),
      note: "履约验收包裹",
    },
  });
  expect(result.status()).toBe(201);
  const order = await result.json();
  if (!paid) return order;
  const recharge = await request.post("/api/wallet/recharge", {
    headers: keyed(user),
    data: { amount: 1000 },
  });
  expect(recharge.status()).toBe(201);
  expect(
    (
      await request.post(
        `/api/wallet/recharge/${(await recharge.json()).rechargeId}/confirm`,
        { headers: keyed(user) },
      )
    ).status(),
  ).toBe(200);
  const reserve = await request.post(
    `/api/orders/${order.orderId}/payment-request`,
    { headers: keyed(user), data: { version: order.version } },
  );
  const payment = await request.post("/api/pay/prepay", {
    headers: keyed(user),
    data: {
      orderId: order.orderId,
      paymentRequestId: (await reserve.json()).paymentRequestId,
    },
  });
  expect((await payment.json()).status).toBe("succeeded");
  await expect
    .poll(async () => (await latest(request, order, user)).status)
    .toBe("pending");
  return latest(request, order, user);
}
async function latest(request, order, user) {
  return (
    await request.get(`/api/orders/${order.orderId}`, { headers: auth(user) })
  ).json();
}
async function accept(request, order, courier) {
  const result = await request.post(`/api/orders/${order.orderId}/accept`, {
    headers: keyed(courier),
    data: { version: order.version },
  });
  expect(result.status()).toBe(200);
  return result.json();
}
async function visit(page, user, path = "/orders") {
  await page.goto("/login");
  await page.evaluate(
    (token) => sessionStorage.setItem("accessToken", token),
    user.accessToken,
  );
  await page.goto(path);
}
async function open(page, order) {
  await page
    .locator(".order-card")
    .filter({ hasText: order.company })
    .getByRole("button")
    .click();
  await expect(page.getByRole("region", { name: "订单详情" })).toContainText(
    order.orderId,
  );
  await expect(page.locator(".detail dl")).toBeVisible();
}
test("真实账号：大厅接单、履约、双向评价、信用刷新与低分准入", async ({
  page,
  request,
}) => {
  const publisher = await student(request),
    courier = await student(request);
  const order = await create(request, publisher);
  await visit(page, courier, "/tasks");
  await page
    .locator(".task-card")
    .filter({ hasText: order.company })
    .getByRole("button", { name: "查看详情" })
    .click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: /确认接单/ })
    .click();
  await expect(page.getByText(/接单成功/)).toBeVisible();
  await page.goto("/orders");
  await open(page, order);
  await page.getByRole("button", { name: "开始取件", exact: true }).click();
  await page.getByLabel("输入取件码").fill("C-123456");
  await page.getByRole("button", { name: "核验取件码", exact: true }).click();
  await page.getByRole("button", { name: "确认送达", exact: true }).click();
  await expect(page.getByLabel("评分")).toBeVisible({ timeout: 15000 });
  await page.getByLabel("文字评价（可选）").fill("沟通顺畅");
  await page.getByRole("button", { name: "提交评价" }).click();
  await expect(page.getByText(/评价已提交/)).toBeVisible();
  await visit(page, publisher, "/reviews");
  await open(page, order);
  await page.getByLabel("评分").selectOption("1");
  await page.getByLabel("文字评价（可选）").fill("<script>仅作为文字</script>");
  await page.getByRole("button", { name: "提交评价" }).click();
  await expect(
    page.getByText("<script>仅作为文字</script>", { exact: true }),
  ).toBeVisible();
  await visit(page, courier, "/reviews");
  await expect(page.locator(".summary").first()).toContainText("限制接单");
  await open(page, order);
  await expect(page.locator(".review")).toHaveCount(2);
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({
    path: "test-results/c-reviews-desktop.png",
    fullPage: true,
  });
  const another = await create(request, publisher);
  await page.goto("/tasks");
  await page
    .locator(".task-card")
    .filter({ hasText: another.company })
    .getByRole("button", { name: "查看详情" })
    .click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: /确认接单/ })
    .click();
  await expect(page.getByRole("dialog")).toContainText("信用分低于");
});

test("390px 手机：错误三次锁单，双方可见通知且无横向溢出", async ({
  page,
  request,
}) => {
  const publisher = await student(request),
    courier = await student(request);
  const order = await accept(
    request,
    await create(request, publisher),
    courier,
  );
  await page.setViewportSize({ width: 390, height: 844 });
  await visit(page, courier);
  await open(page, order);
  await page.getByRole("button", { name: "开始取件", exact: true }).click();
  for (let n = 1; n <= 3; n++) {
    await page.getByLabel("输入取件码").fill("错误码");
    await page.getByRole("button", { name: "核验取件码", exact: true }).click();
    if (n < 3)
      await expect(
        page.getByText(`取件码已连续错误 ${n} 次，累计三次将锁定订单。`),
      ).toBeVisible();
  }
  await expect(page.getByLabel("订单通知")).toContainText("订单已锁定");
  await expect(
    page.getByRole("button", { name: "核验取件码", exact: true }),
  ).toHaveCount(0);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({
    path: "test-results/c-lock-mobile.png",
    fullPage: true,
  });
  await visit(page, publisher);
  await open(page, order);
  await expect(page.getByLabel("订单通知")).toContainText("订单已锁定");
});

test("取消未支付和已支付订单，等待真实退款结果", async ({ page, request }) => {
  const publisher = await student(request);
  const unpaid = await create(request, publisher, false);
  await visit(page, publisher);
  await open(page, unpaid);
  await page.getByLabel("取消原因").fill("计划变更");
  await page.getByRole("button", { name: "取消订单", exact: true }).click();
  await expect(page.locator(".detail")).toContainText("订单已取消");
  await expect(page.locator(".detail dl")).toContainText("无需退款");
  const paid = await create(request, publisher);
  await page.getByRole("button", { name: "刷新订单" }).click();
  await open(page, paid);
  await page.getByLabel("取消原因").fill("不再需要");
  await page.getByRole("button", { name: "取消订单", exact: true }).click();
  await expect
    .poll(async () => (await latest(request, paid, publisher)).refundStatus)
    .toBe("succeeded");
  await page.getByRole("button", { name: "刷新订单" }).click();
  await expect(page.locator(".detail dl")).toContainText("已退款");
});

test("连接失败保留重试且使用同一提交标识，详情失败禁用操作", async ({
  page,
  request,
}) => {
  const publisher = await student(request),
    courier = await student(request);
  const order = await accept(
    request,
    await create(request, publisher),
    courier,
  );
  await visit(page, courier);
  await open(page, order);
  let failed = false;
  const keys = [];
  await page.route(`**/api/orders/${order.orderId}/status`, async (route) => {
    keys.push(route.request().headers()["idempotency-key"]);
    if (!failed) {
      failed = true;
      await route.abort();
    } else await route.continue();
  });
  await page.getByRole("button", { name: "开始取件", exact: true }).click();
  await expect(page.getByText(/连接中断/)).toBeVisible();
  await page.getByRole("button", { name: "开始取件", exact: true }).click();
  await expect(page.getByLabel("输入取件码")).toBeVisible();
  expect(keys).toHaveLength(2);
  expect(keys[0]).toBe(keys[1]);
  await page.route(`**/api/orders/${order.orderId}`, (route) =>
    route.fulfill({ status: 503, json: { detail: "暂不可用" } }),
  );
  await page.getByRole("button", { name: "刷新订单" }).click();
  await expect(page.getByRole("alert")).toContainText("无法更新订单");
  await expect(
    page.getByRole("button", { name: "核验取件码", exact: true }),
  ).toBeDisabled();
});

test("轮询在离开页面时停止，列表错误与空态分开显示", async ({
  page,
  request,
}) => {
  const publisher = await student(request);
  await create(request, publisher, false);
  await page.clock.install();
  await visit(page, publisher);
  await expect(page.locator(".order-card")).toHaveCount(1);
  let queries = 0;
  page.on("request", (req) => {
    if (req.url().includes("scope=mine")) queries++;
  });
  await page.clock.runFor(11000);
  await expect.poll(() => queries).toBeGreaterThan(0);
  await page
    .getByRole("link", { name: "代取大厅", exact: true })
    .first()
    .click();
  await expect(page.locator(".fulfillment-workspace")).toHaveCount(0);
  const before = queries;
  await page.clock.runFor(31000);
  expect(queries).toBe(before);
  await page.route("**/api/orders?*scope=mine*", (route) =>
    route.fulfill({ status: 503, json: { detail: "查询暂不可用" } }),
  );
  await page.goto("/orders");
  await expect(page.getByRole("alert")).toContainText("查询暂不可用");
  await expect(page.getByText("暂无符合条件的订单")).toHaveCount(0);
});
