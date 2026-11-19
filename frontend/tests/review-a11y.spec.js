import { test, expect } from "@playwright/test";
import { randomInt } from "node:crypto";
import { readFileSync } from "node:fs";

const code = "482917";
const sample = new URL("./fixtures/学生证样例.png", import.meta.url);

async function requestCode(request, phone, purpose) {
  const response = await request.post("/api/auth/codes", {
    data: { phone, purpose },
  });
  expect(response.status()).toBe(200);
}

async function signIn(request, phone) {
  await requestCode(request, phone, "login");
  const response = await request.post("/api/auth/login", {
    data: { phone, code },
  });
  expect(response.status()).toBe(200);
  return (await response.json()).accessToken;
}

test("键盘审核可聚焦详情、关闭证件、修正驳回理由并返回列表", async ({
  page,
  request,
}) => {
  const phone = `139${String(randomInt(100000000)).padStart(8, "0")}`;
  await requestCode(request, phone, "register");
  const registered = await request.post("/api/auth/register", {
    data: { phone, code },
  });
  expect(registered.status()).toBe(201);
  const student = await signIn(request, phone);
  const admin = await signIn(request, "13900999999");
  const Authorization = `Bearer ${student}`;
  const application = await request.post(
    "/api/auth/verification-applications",
    {
      headers: { Authorization },
      multipart: {
        realName: "键盘审核测试同学",
        studentNo: "202600123456",
        photo: {
          name: "sample.png",
          mimeType: "image/png",
          buffer: readFileSync(sample),
        },
      },
    },
  );
  expect(application.status()).toBe(201);
  const { applicationId } = await application.json();

  await page.addInitScript(
    (token) => sessionStorage.setItem("accessToken", token),
    admin,
  );
  await page.goto("/admin/verification");
  const trigger = page.getByRole("button", {
    name: /查看申请详情：键盘审核测试同学，学号/,
  });
  const heading = page.getByRole("heading", {
    name: "申请详情",
    exact: true,
  });
  const refresh = page.getByRole("button", { name: "刷新申请列表" });
  await expect(trigger).toBeVisible();

  let release;
  const delayed = new Promise((resolve) => {
    release = resolve;
  });
  await page.route(
    `**/api/admin/verification-applications/${applicationId}`,
    async (route) => {
      await delayed;
      await route.continue();
    },
    { times: 1 },
  );
  try {
    await trigger.focus();
    await page.keyboard.press("Enter");
    await expect(page.getByText("正在加载申请详情…")).toBeVisible();
    await page.keyboard.press("Shift+Tab");
    await expect(refresh).toBeFocused();
  } finally {
    release();
  }
  await expect(heading).toBeVisible();
  await expect(refresh).toBeFocused();

  await trigger.focus();
  await page.keyboard.press("Enter");
  await expect(heading).toBeFocused();
  await page.keyboard.press("Tab");
  const photo = page.getByRole("button", { name: "查看证件照片" });
  await expect(photo).toBeFocused();
  await expect(photo).toHaveAttribute("aria-haspopup", "dialog");
  await page.keyboard.press("Enter");
  const dialog = page.getByRole("dialog", { name: "证件照片" });
  const close = dialog.getByRole("button", { name: "关闭照片" });
  await expect(close).toBeFocused();
  await expect(
    dialog.getByRole("img", { name: /上传的认证证件照片/ }),
  ).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await expect(photo).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(close).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(dialog).toBeHidden();
  await expect(photo).toBeFocused();

  const reason = page.getByRole("textbox", { name: "驳回理由" });
  const approve = page.getByRole("button", { name: "通过认证" });
  const reject = page.getByRole("button", { name: "驳回申请" });
  await page.keyboard.press("Tab");
  await expect(reason).toBeFocused();
  await expect(reason).toHaveAccessibleDescription("驳回时必填，最多 500 字。");
  await page.keyboard.press("Tab");
  await expect(approve).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(reject).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(reason).toBeFocused();
  await expect(reason).toHaveAttribute("aria-invalid", "true");
  await expect(reason).toHaveAccessibleDescription(/驳回时请填写具体理由。/);
  await page.keyboard.insertText("请上传清晰的证件照片");
  await expect(reason).not.toHaveAttribute("aria-invalid", "true");
  await page.keyboard.press("Tab");
  await page.keyboard.press("Tab");
  await expect(reject).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("status")).toContainText("已通知申请人");
  await expect(
    page.getByRole("heading", { name: "认证申请列表" }),
  ).toBeFocused();
  await expect(heading).toHaveCount(0);
  const status = await request.get("/api/auth/verify-status", {
    headers: { Authorization },
  });
  expect(await status.json()).toMatchObject({
    status: "rejected",
    rejectReason: "请上传清晰的证件照片",
  });
});
