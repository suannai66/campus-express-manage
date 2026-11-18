import { test, expect } from "@playwright/test";
import { randomInt } from "node:crypto";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const fixture = fileURLToPath(
  new URL("./fixtures/学生证样例.png", import.meta.url),
);
const code = "482917";

test("演示按钮手动通过本人申请并刷新历史和通知", async ({ page, request }) => {
  const user = await student(request);
  await use(page, user);
  const button = page.getByRole("button", { name: "自动审核（演示）" });
  await expect(button).toBeVisible();
  await expect(button).toBeDisabled();
  await submitUI(page, "演示同学");
  await expect(button).toBeEnabled();
  await button.click();
  await expect(
    page.getByText("认证已通过。", { exact: false }).first(),
  ).toBeVisible();
  await expect(button).toBeDisabled();
  await expect(page.getByRole("status")).toContainText("演示审核已通过");
  const status = await request.get("/api/auth/verify-status", {
    headers: { Authorization: `Bearer ${user.accessToken}` },
  });
  expect((await status.json()).verified).toBe(true);
  await page.reload();
  await expect(button).toBeDisabled();
  await expect(
    page.getByText("认证已通过。", { exact: false }).first(),
  ).toBeVisible();
});
async function credentials(request, phone) {
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
  return { phone, ...(await credentials(request, phone)) };
}
async function use(page, account, path = "/verification") {
  await page.goto("/login");
  await page.evaluate(
    (token) => sessionStorage.setItem("accessToken", token),
    account.accessToken,
  );
  await page.goto(path);
}
async function fillApplication(page, name) {
  await page.getByLabel("真实姓名", { exact: true }).fill(name);
  await page.getByLabel("学号", { exact: true }).fill("202600123456");
  await page.locator("input[type=file]").setInputFiles(fixture);
}
async function openConfirmation(page) {
  await page
    .getByRole("button", { name: /^(提交认证申请|重新提交认证)$/ })
    .click();
  await expect(
    page.getByRole("heading", { name: "确认认证资料", exact: true }),
  ).toBeFocused();
}
async function submitUI(page, name) {
  await fillApplication(page, name);
  await openConfirmation(page);
  await page.getByRole("button", { name: "确认提交", exact: true }).click();
  await expect(page.getByText("待审核", { exact: true }).first()).toBeVisible();
}

test("真实认证用户支付后经公共投递器自动发布，重试不重复扣款", async ({
  page,
  request,
}) => {
  const user = await student(request),
    admin = await credentials(request, "13900999998");
  const auth = { Authorization: `Bearer ${user.accessToken}` };
  const keyed = () => ({ ...auth, "Idempotency-Key": crypto.randomUUID() });
  const application = await request.post(
    "/api/auth/verification-applications",
    {
      headers: auth,
      multipart: {
        realName: "事件联调学生",
        studentNo: "202600123456",
        photo: {
          name: "sample.png",
          mimeType: "image/png",
          buffer: readFileSync(fixture),
        },
      },
    },
  );
  expect(application.status()).toBe(201);
  const review = await request.post(
    `/api/admin/verification-applications/${(await application.json()).applicationId}/review`,
    {
      headers: { Authorization: `Bearer ${admin.accessToken}` },
      data: { decision: "approved", rejectReason: null, version: 1 },
    },
  );
  expect(review.status()).toBe(200);
  const recharge = await request.post("/api/wallet/recharge", {
    headers: keyed(),
    data: { amount: 1000 },
  });
  expect(recharge.status()).toBe(201);
  expect(
    (
      await request.post(
        `/api/wallet/recharge/${(await recharge.json()).rechargeId}/confirm`,
        { headers: keyed() },
      )
    ).status(),
  ).toBe(200);
  await use(page, user, "/publish");
  await page.getByLabel(/快递公司/).fill("中通快递");
  await page.getByLabel(/^取件点/).selectOption("station_cainiao");
  await page.getByLabel(/^取件码/).fill("A-1234");
  await page.getByLabel(/送达区域/).selectOption("zone_qinyuan");
  await page.getByLabel(/详细送达地址/).fill("测试楼101");
  await page
    .getByLabel(/期望送达时间/)
    .fill(new Date(Date.now() + 11 * 3600000).toISOString().slice(0, 16));
  await page.getByLabel(/小费金额/).fill("2.35");
  await expect(page.locator(".fee-total")).toContainText("4.35");
  await page.getByRole("button", { name: "创建订单", exact: true }).click();
  await expect(page.locator(".order-result")).toBeVisible();
  await page.getByRole("button", { name: /去支付/ }).click();
  const paymentRequest = page.waitForRequest(
    (req) => new URL(req.url()).pathname === "/api/pay/prepay",
  );
  await page.getByRole("button", { name: "确认支付", exact: true }).click();
  const body = (await paymentRequest).postDataJSON();
  await expect(page.locator(".order-result .soft-tag")).toHaveText("待接单", {
    timeout: 10000,
  });
  const replay = await request.post("/api/pay/prepay", {
    headers: keyed(),
    data: body,
  });
  expect(replay.status()).toBe(200);
  expect((await replay.json()).status).toBe("succeeded");
  expect(
    (await (await request.get("/api/wallet", { headers: auth })).json())
      .balance,
  ).toBe(565);
  const transactions = await request.get(
    "/api/wallet/transactions?type=payment",
    { headers: auth },
  );
  expect((await transactions.json()).total).toBe(1);
  await page.reload();
  await expect(page.locator(".order-result .soft-tag")).toHaveText("待接单");
});

test("提交、驳回、重提、通过与订单准入闭环", async ({
  page,
  request,
  browser,
}) => {
  const user = await student(request),
    name = `演示学生${randomInt(100000)}`;
  await use(page, user);
  await submitUI(page, name);
  await expect(page.getByLabel("真实姓名", { exact: true })).toHaveCount(0);
  const adminContext = await browser.newContext(),
    adminPage = await adminContext.newPage();
  const admin = await credentials(request, "13900999999");
  await use(adminPage, admin, "/admin/verification");
  await adminPage
    .locator(".application-list li")
    .filter({ hasText: name })
    .getByRole("button", { name: "查看申请详情" })
    .click();
  await adminPage
    .getByRole("button", { name: "查看证件照片", exact: true })
    .click();
  await expect(adminPage.getByRole("dialog").getByRole("img")).toBeVisible();
  expect(
    await adminPage.getByRole("dialog").getByRole("img").getAttribute("src"),
  ).toMatch(/^blob:/);
  await adminPage.getByRole("button", { name: "关闭照片" }).click();
  await adminPage
    .getByLabel("驳回理由", { exact: true })
    .fill("请上传清晰证件照片");
  await adminPage
    .getByRole("button", { name: "驳回申请", exact: true })
    .click();
  await expect(adminPage.getByRole("status")).toContainText("已通知申请人");
  await page.getByRole("button", { name: "刷新认证结果" }).click();
  await expect(
    page.getByText("认证已驳回", { exact: true }).first(),
  ).toBeVisible();
  await expect(
    page.getByText("请上传清晰证件照片", { exact: true }),
  ).toBeVisible();
  await submitUI(page, name);
  await adminPage.getByRole("button", { name: "刷新申请列表" }).click();
  await adminPage
    .locator(".application-list li")
    .filter({ hasText: name })
    .getByRole("button", { name: "查看申请详情" })
    .click();
  await adminPage
    .getByRole("button", { name: "通过认证", exact: true })
    .click();
  await expect(adminPage.getByRole("status")).toContainText("已通知申请人");
  await page.getByRole("button", { name: "刷新认证结果" }).click();
  await expect(
    page.getByText("认证已通过", { exact: true }).first(),
  ).toBeVisible();
  await expect(
    page.locator(".records").first().locator(".record-list li"),
  ).toHaveCount(2);
  await expect(
    page.locator(".records").last().locator(".record-list li"),
  ).toHaveCount(2);
  await page.getByRole("link", { name: "去发布代取需求" }).click();
  await expect(
    page.getByRole("button", { name: "创建订单", exact: true }),
  ).toBeEnabled();
  await adminContext.close();
});

test("普通用户不能查看审核资料，照片越权返回 404", async ({
  page,
  request,
}) => {
  const user = await student(request),
    other = await student(request);
  const result = await request.post("/api/auth/verification-applications", {
    headers: { Authorization: `Bearer ${user.accessToken}` },
    multipart: {
      realName: "隐私演示",
      studentNo: "202600999999",
      photo: {
        name: "sample.png",
        mimeType: "image/png",
        buffer: readFileSync(fixture),
      },
    },
  });
  expect(result.status()).toBe(201);
  const application = await result.json();
  expect(
    (
      await request.get(
        `/api/auth/verification-applications/${application.applicationId}/photo`,
        { headers: { Authorization: `Bearer ${other.accessToken}` } },
      )
    ).status(),
  ).toBe(404);
  await use(page, other, "/admin/verification");
  await expect(page.getByRole("alert")).toContainText("仅管理员");
  await expect(page.getByText("隐私演示", { exact: true })).toHaveCount(0);
});

test("上传失败显示错误，认证状态保持未提交", async ({ page, request }) => {
  await use(page, await student(request));
  let submissions = 0;
  page.on("request", (r) => {
    if (
      r.method() === "POST" &&
      new URL(r.url()).pathname === "/api/auth/verification-applications"
    )
      submissions++;
  });
  await page.getByLabel("真实姓名", { exact: true }).fill("虚构学生");
  await page.getByLabel("学号", { exact: true }).fill("202600001");
  await page.locator("input[type=file]").setInputFiles({
    name: "fake.png",
    mimeType: "image/png",
    buffer: Buffer.from("not-image"),
  });
  await page.getByRole("button", { name: "提交认证申请", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("照片内容无效");
  await expect(page.getByRole("region", { name: "确认认证资料" })).toHaveCount(
    0,
  );
  await expect(page.getByText("未提交认证", { exact: true })).toBeVisible();
  expect(submissions).toBe(0);
});

test("移动端申请页面无横向溢出", async ({ page, request }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await use(page, await student(request));
  await expect(
    page.getByRole("button", { name: "提交认证申请", exact: true }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBeTruthy();
  await fillApplication(page, "移动端同学");
  await openConfirmation(page);
  await expect(
    page.getByRole("region", { name: "确认认证资料" }).getByRole("img"),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBeTruthy();
  await page.screenshot({
    path: "test-results/verification-mobile.png",
    fullPage: true,
  });
});

test("确认前不提交，返回保留资料，修改后的内容及照片与正式申请一致", async ({
  page,
  request,
}) => {
  const user = await student(request);
  const headers = { Authorization: `Bearer ${user.accessToken}` };
  await page.addInitScript(() => {
    const revoke = URL.revokeObjectURL.bind(URL);
    window.revokedPreviews = [];
    URL.revokeObjectURL = (url) => {
      window.revokedPreviews.push(url);
      revoke(url);
    };
  });
  await use(page, user);
  let submissions = 0;
  page.on("request", (r) => {
    if (
      r.method() === "POST" &&
      new URL(r.url()).pathname === "/api/auth/verification-applications"
    )
      submissions++;
  });
  await fillApplication(page, " 核对同学 ");
  await openConfirmation(page);
  const summary = page.getByRole("region", { name: "确认认证资料" });
  await expect(summary).toContainText("核对同学");
  await expect(summary).toContainText("202600123456");
  const preview = await summary.getByRole("img").getAttribute("src");
  expect(preview).toMatch(/^blob:/);
  await expect(summary.getByRole("img")).toBeVisible();
  expect(
    (await (await request.get("/api/auth/verify-status", { headers })).json())
      .status,
  ).toBe("not_submitted");
  expect(
    (
      await (
        await request.get("/api/auth/verification-applications", { headers })
      ).json()
    ).total,
  ).toBe(0);
  expect(submissions).toBe(0);
  // 键盘返回后恢复表单焦点，文件及文字均可继续修改。
  await summary.getByRole("button", { name: "返回修改" }).focus();
  await page.keyboard.press("Enter");
  await expect(
    page.getByRole("button", { name: "提交认证申请", exact: true }),
  ).toBeFocused();
  await expect(page.getByLabel("真实姓名", { exact: true })).toHaveValue(
    " 核对同学 ",
  );
  expect(
    await page.locator("input[type=file]").evaluate((el) => el.files.length),
  ).toBe(1);
  expect(
    await page.evaluate((url) => window.revokedPreviews.includes(url), preview),
  ).toBe(true);
  await page.getByLabel("真实姓名", { exact: true }).fill("修改后同学");
  await page.getByLabel("学号", { exact: true }).fill("202600987654");
  await openConfirmation(page);
  await expect(summary).toContainText("修改后同学");
  await expect(summary).toContainText("202600987654");
  const secondPreview = await summary.getByRole("img").getAttribute("src");
  const sent = page.waitForResponse(
    (r) =>
      r.request().method() === "POST" &&
      new URL(r.url()).pathname === "/api/auth/verification-applications",
  );
  await summary.getByRole("button", { name: "确认提交", exact: true }).click();
  expect((await sent).status()).toBe(201);
  await expect(page.getByText("待审核", { exact: true }).first()).toBeVisible();
  expect(submissions).toBe(1);
  const history = await (
    await request.get("/api/auth/verification-applications", { headers })
  ).json();
  expect(history.total).toBe(1);
  expect(history.items[0].realName).toBe("修改后同学");
  expect(history.items[0].studentNo).toBe("********7654");
  const photo = await request.get(
    `/api/auth/verification-applications/${history.items[0].applicationId}/photo`,
    { headers },
  );
  expect(await photo.body()).toEqual(readFileSync(fixture));
  expect(
    await page.evaluate(
      (url) => window.revokedPreviews.includes(url),
      secondPreview,
    ),
  ).toBe(true);
});

test("确认提交失败后保留资料可重试，连续点击只创建一份申请", async ({
  page,
  request,
}) => {
  const user = await student(request);
  await use(page, user);
  await fillApplication(page, "失败重试同学");
  await openConfirmation(page);
  const summary = page.getByRole("region", { name: "确认认证资料" });
  let attempts = 0,
    release;
  const waiting = new Promise((resolve) => {
    release = resolve;
  });
  await page.route("**/api/auth/verification-applications", async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    attempts++;
    if (attempts === 1)
      return route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({
          code: "DEPENDENCY_UNAVAILABLE",
          detail: "提交暂不可用，请重试",
          fields: {},
        }),
      });
    await waiting;
    await route.continue();
  });
  await summary.getByRole("button", { name: "确认提交", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("提交暂不可用");
  await expect(summary).toContainText("失败重试同学");
  await expect(summary.getByRole("img")).toBeVisible();
  expect(
    (
      await (
        await request.get("/api/auth/verification-applications", {
          headers: { Authorization: `Bearer ${user.accessToken}` },
        })
      ).json()
    ).total,
  ).toBe(0);
  await summary
    .getByRole("button", { name: "确认提交", exact: true })
    .evaluate((button) => {
      button.click();
      button.click();
    });
  await expect(
    summary.getByRole("button", { name: "正在提交…", exact: true }),
  ).toBeDisabled();
  await expect(
    summary.getByRole("button", { name: "返回修改" }),
  ).toBeDisabled();
  expect(attempts).toBe(2);
  release();
  await expect(page.getByText("待审核", { exact: true }).first()).toBeVisible();
  expect(
    (
      await (
        await request.get("/api/auth/verification-applications", {
          headers: { Authorization: `Bearer ${user.accessToken}` },
        })
      ).json()
    ).total,
  ).toBe(1);
  expect(attempts).toBe(2);
});

test("空字段、错误类型和超过5MB照片不能进入确认或创建申请", async ({
  page,
  request,
}) => {
  const user = await student(request);
  await use(page, user);
  await fillApplication(page, "   ");
  await page.getByRole("button", { name: "提交认证申请", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("请填写姓名");
  await expect(page.getByRole("region", { name: "确认认证资料" })).toHaveCount(
    0,
  );
  await page.getByLabel("真实姓名", { exact: true }).fill("文件检查同学");
  for (const file of [
    {
      name: "invalid.gif",
      mimeType: "image/gif",
      buffer: Buffer.from("GIF89a"),
    },
    {
      name: "oversize.png",
      mimeType: "image/png",
      buffer: Buffer.alloc(5 * 1024 * 1024 + 1),
    },
  ]) {
    await page.locator("input[type=file]").setInputFiles(file);
    await expect(page.getByRole("alert")).toContainText("不超过 5 MB");
    await page
      .getByRole("button", { name: "提交认证申请", exact: true })
      .click();
    await expect(
      page.getByRole("region", { name: "确认认证资料" }),
    ).toHaveCount(0);
  }
  expect(
    (
      await (
        await request.get("/api/auth/verification-applications", {
          headers: { Authorization: `Bearer ${user.accessToken}` },
        })
      ).json()
    ).total,
  ).toBe(0);
});

test("确认期间会话失效时跳转登录且不创建申请，离开页面释放预览", async ({
  page,
  request,
}) => {
  const user = await student(request);
  await page.addInitScript(() => {
    const revoke = URL.revokeObjectURL.bind(URL);
    window.revokedPreviews = [];
    URL.revokeObjectURL = (url) => {
      window.revokedPreviews.push(url);
      revoke(url);
    };
  });
  await use(page, user);
  await fillApplication(page, "会话检查同学");
  await openConfirmation(page);
  const preview = await page
    .getByRole("region", { name: "确认认证资料" })
    .getByRole("img")
    .getAttribute("src");
  await page
    .getByRole("link", { name: "代取大厅", exact: true })
    .first()
    .click();
  await expect(page).toHaveURL(/\/tasks$/);
  await expect
    .poll(() =>
      page.evaluate((url) => window.revokedPreviews.includes(url), preview),
    )
    .toBe(true);
  await page.goto("/verification");
  await fillApplication(page, "会话检查同学");
  await openConfirmation(page);
  const headers = { Authorization: `Bearer ${user.accessToken}` };
  expect((await request.post("/api/auth/logout", { headers })).status()).toBe(
    200,
  );
  const rejected = page.waitForResponse(
    (r) =>
      r.request().method() === "POST" &&
      new URL(r.url()).pathname === "/api/auth/verification-applications",
  );
  await page.getByRole("button", { name: "确认提交", exact: true }).click();
  expect((await rejected).status()).toBe(401);
  await expect(page).toHaveURL(/\/login\?redirect=/);
  expect(
    await page.evaluate(() => sessionStorage.getItem("accessToken")),
  ).toBeNull();
});

test("确认期间另一页面已提交时，以服务端状态为准并拒绝额外申请", async ({
  page,
  request,
}) => {
  const user = await student(request);
  const headers = { Authorization: `Bearer ${user.accessToken}` };
  await use(page, user);
  await fillApplication(page, "状态竞争同学");
  await openConfirmation(page);
  expect(
    (
      await request.post("/api/auth/verification-applications", {
        headers,
        multipart: {
          realName: "另一页面同学",
          studentNo: "202600123456",
          photo: {
            name: "sample.png",
            mimeType: "image/png",
            buffer: readFileSync(fixture),
          },
        },
      })
    ).status(),
  ).toBe(201);
  await page.getByRole("button", { name: "确认提交", exact: true }).click();
  await expect(page.getByText("待审核", { exact: true }).first()).toBeVisible();
  await expect(page.getByRole("region", { name: "确认认证资料" })).toHaveCount(
    0,
  );
  const history = await (
    await request.get("/api/auth/verification-applications", { headers })
  ).json();
  expect(history.total).toBe(1);
  expect(history.items[0].realName).toBe("另一页面同学");
});
