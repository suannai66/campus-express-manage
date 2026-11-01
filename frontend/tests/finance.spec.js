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

async function recharge(page, amount = "10") {
  await page.goto("/wallet");
  await page.getByRole("button", { name: "模拟充值", exact: true }).click();
  await page.getByLabel("充值金额（元）").fill(amount);
  await page.getByRole("button", { name: "去支付", exact: true }).click();
  await page.getByRole("button", { name: /我已支付/ }).click();
  await expect(page.getByRole("status")).toContainText("充值成功");
  await expect(page.locator(".wallet-banner strong")).toHaveText("¥ 10.00");
}
async function publish(page, company) {
  await page.goto("/publish");
  await page.getByLabel("快递公司", { exact: true }).fill(company);
  await page
    .getByLabel("取件点", { exact: true })
    .selectOption("station_cainiao");
  await page.getByLabel("取件码", { exact: true }).fill("C-123456");
  await page
    .getByLabel("送达区域", { exact: true })
    .selectOption("zone_qinyuan");
  await page.getByLabel("包裹重量（kg）", { exact: true }).fill("1.2");
  await page.getByLabel("详细送达地址", { exact: true }).fill("虚构联调楼302");
  await page
    .getByLabel("期望送达时间", { exact: true })
    .fill(new Date(Date.now() + 11 * 3600000).toISOString().slice(0, 16));
  await page.getByLabel("小费金额（元）", { exact: true }).fill("2.35");
  await expect(page.locator(".fee-total")).toContainText("5.35");
  const created = page.waitForResponse(
    (r) =>
      new URL(r.url()).pathname === "/api/orders" &&
      r.request().method() === "POST",
  );
  await page.getByRole("button", { name: "创建订单", exact: true }).click();
  const response = await created;
  expect(response.status()).toBe(201);
  const order = await response.json();
  await page.reload();
  await page.getByRole("button", { name: /去支付/ }).click();
  await page.getByRole("button", { name: "确认支付", exact: true }).click();
  await expect(page.locator(".order-result .soft-tag")).toHaveText("待接单", {
    timeout: 15000,
  });
  await page.reload();
  await expect(page.locator(".order-result .soft-tag")).toHaveText("待接单");
  return { ...order, company };
}

test("页面完整交易：充值、报价支付、刷新、接单配送、收益流水", async ({
  page,
  request,
}) => {
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const publisher = await student(request),
    courier = await student(request);
  await visit(page, publisher, "/wallet");
  await recharge(page);
  const order = await publish(page, `资金联调${randomInt(100000)}`);
  await page.goto("/wallet");
  await expect(page.locator(".wallet-banner strong")).toHaveText("¥ 4.65");
  await expect(page.locator(".ledger-list")).toContainText("订单支付");
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
  await expect
    .poll(async () =>
      (await request.get("/api/wallet", { headers: auth(courier) }))
        .json()
        .then((v) => v.balance),
    )
    .toBe(505);
  await page.goto("/wallet");
  await expect(page.locator(".wallet-banner strong")).toHaveText("¥ 5.05");
  await expect(page.locator(".ledger-list")).toContainText("履约结算");
  await page.reload();
  await expect(page.locator(".wallet-banner strong")).toHaveText("¥ 5.05");
  expect(errors).toEqual([]);
});

test("页面取消：全额退款、恢复余额和退款流水", async ({ page, request }) => {
  const publisher = await student(request);
  await visit(page, publisher, "/wallet");
  await recharge(page);
  const order = await publish(page, `退款联调${randomInt(100000)}`);
  await page.goto("/orders");
  await open(page, order);
  await page.getByLabel("取消原因").fill("浏览器退款联调");
  await page.getByRole("button", { name: "取消订单", exact: true }).click();
  await expect
    .poll(async () =>
      (
        await request.get(`/api/orders/${order.orderId}`, {
          headers: auth(publisher),
        })
      )
        .json()
        .then((v) => v.refundStatus),
    )
    .toBe("succeeded");
  await page.getByRole("button", { name: "刷新订单" }).click();
  await expect(page.locator(".detail dl")).toContainText("已退款");
  await page.goto("/wallet");
  await expect(page.locator(".wallet-banner strong")).toHaveText("¥ 10.00");
  await expect(page.locator(".ledger-list")).toContainText("订单退款");
});

test("充值响应丢失后同键重试只入账一次", async ({ page, request }) => {
  const publisher = await student(request);
  await visit(page, publisher, "/wallet");
  await page.getByRole("button", { name: "模拟充值", exact: true }).click();
  await page.getByLabel("充值金额（元）").fill("10");
  await page.getByRole("button", { name: "去支付", exact: true }).click();
  const keys = [];
  let first = true;
  await page.route("**/api/wallet/recharge/*/confirm", async (route) => {
    keys.push(route.request().headers()["idempotency-key"]);
    if (first) {
      first = false;
      await route.fetch();
      await route.abort("failed");
    } else await route.continue();
  });
  await page.getByRole("button", { name: /我已支付/ }).click();
  await expect(page.getByRole("alert")).toBeVisible();
  await page.getByRole("button", { name: /我已支付/ }).click();
  await expect(page.getByRole("status")).toContainText("充值成功");
  expect(keys).toHaveLength(2);
  expect(keys[0]).toBeTruthy();
  expect(keys[1]).toBe(keys[0]);
  await page.reload();
  await expect(page.locator(".wallet-banner strong")).toHaveText("¥ 10.00");
  await expect(page.locator(".ledger-list li")).toHaveCount(1);
});

test("390px 钱包：充值确认防连点、刷新余额与布局", async ({
  page,
  request,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const publisher = await student(request);
  await visit(page, publisher, "/wallet");
  await page.getByRole("button", { name: "模拟充值", exact: true }).click();
  await page.getByLabel("充值金额（元）").fill("10");
  await page.getByRole("button", { name: "去支付", exact: true }).click();
  let release;
  const gate = new Promise((resolve) => {
    release = resolve;
  });
  let count = 0;
  await page.route("**/api/wallet/recharge/*/confirm", async (route) => {
    count++;
    await gate;
    await route.continue();
  });
  const button = page.getByRole("button", { name: /我已支付/ });
  await button.click();
  try {
    await expect(button).toBeDisabled();
    await button.dispatchEvent("click");
    expect(count).toBe(1);
  } finally {
    release();
  }
  await expect(page.getByRole("status")).toContainText("充值成功");
  await page.reload();
  await expect(page.locator(".wallet-banner strong")).toHaveText("¥ 10.00");
  await expect(page.locator(".ledger-list li")).toHaveCount(1);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: "test-results/finance-wallet-mobile.png",
    fullPage: true,
  });
});
