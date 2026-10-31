import { test, expect } from "@playwright/test";
import { randomInt } from "node:crypto";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const fixture = fileURLToPath(
  new URL("./fixtures/学生证样例.png", import.meta.url),
);
const code = "482917";
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
async function submitUI(page, name) {
  await page.getByLabel("真实姓名", { exact: true }).fill(name);
  await page.getByLabel("学号", { exact: true }).fill("202600123456");
  await page.locator("input[type=file]").setInputFiles(fixture);
  await page
    .getByRole("button", { name: /^(提交认证申请|重新提交认证)$/ })
    .click();
  await expect(page.getByText("待审核", { exact: true }).first()).toBeVisible();
}

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
  await page.getByLabel("真实姓名", { exact: true }).fill("虚构学生");
  await page.getByLabel("学号", { exact: true }).fill("202600001");
  await page.locator("input[type=file]").setInputFiles({
    name: "fake.png",
    mimeType: "image/png",
    buffer: Buffer.from("not-image"),
  });
  await page.getByRole("button", { name: "提交认证申请", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("照片内容无效");
  await expect(page.getByText("未提交认证", { exact: true })).toBeVisible();
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
  await page.screenshot({
    path: "test-results/verification-mobile.png",
    fullPage: true,
  });
});
