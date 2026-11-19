import { randomInt } from "node:crypto";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";

const photoFixture = fileURLToPath(
  new URL("./fixtures/学生证样例.png", import.meta.url),
);
const code = "482917";

async function openVerification(page, request) {
  const phone = `139${String(randomInt(100000000)).padStart(8, "0")}`;
  for (const purpose of ["register", "login"]) {
    const issued = await request.post("/api/auth/codes", {
      data: { phone, purpose },
    });
    expect(issued.status()).toBe(200);
    const response = await request.post(`/api/auth/${purpose}`, {
      data: { phone, code },
    });
    expect(response.status()).toBe(purpose === "register" ? 201 : 200);
    if (purpose === "login") {
      const { accessToken } = await response.json();
      await page.addInitScript(
        (token) => sessionStorage.setItem("accessToken", token),
        accessToken,
      );
    }
  }
  await page.goto("/verification");
  await expect(page.getByText("未提交认证", { exact: true })).toBeVisible();
}

test("强制颜色下用键盘核对并提交认证，关闭照片后回到触发按钮", async ({
  page,
  request,
}) => {
  await page.emulateMedia({ forcedColors: "active" });
  await openVerification(page, request);
  expect(
    await page.evaluate(() => matchMedia("(forced-colors: active)").matches),
  ).toBe(true);

  const heading = page.getByRole("heading", { name: "学生身份认证" });
  const refresh = page.getByRole("button", { name: "刷新认证结果" });
  const name = page.getByLabel("真实姓名", { exact: true });
  const studentNo = page.getByLabel("学号", { exact: true });
  const photo = page.getByLabel("学生证 / 校园卡照片", { exact: true });
  const next = page.getByRole("button", { name: "提交认证申请", exact: true });
  const confirmation = page.getByRole("heading", { name: "确认认证资料" });
  const edit = page.getByRole("button", { name: "返回修改" });
  const confirm = page.getByRole("button", { name: "确认提交" });
  await expect(photo).toHaveAccessibleDescription(/单张不超过 5 MB/);

  await heading.focus();
  await page.keyboard.press("Tab");
  await expect(refresh).toBeFocused();
  const refreshResponse = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === "/api/auth/verify-status",
  );
  await page.keyboard.press("Enter");
  expect((await refreshResponse).status()).toBe(200);
  await expect(refresh).toBeEnabled();
  await expect(refresh).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(name).toBeFocused();
  await expect(name).not.toHaveCSS("outline-style", "none");
  await page.keyboard.type("Keyboard Student");
  await page.keyboard.press("Tab");
  await expect(studentNo).toBeFocused();
  await page.keyboard.type("202600654321");
  await page.keyboard.press("Tab");
  await expect(photo).toBeFocused();
  const fileChooser = page.waitForEvent("filechooser");
  await page.keyboard.press("Enter");
  await (await fileChooser).setFiles(photoFixture);

  await page.keyboard.press("Tab");
  await expect(next).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(confirmation).toBeFocused();
  await expect(
    page.getByRole("region", { name: "确认认证资料" }),
  ).toContainText("学生证样例.png");
  await page.keyboard.press("Tab");
  await expect(edit).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(next).toBeFocused();
  await expect(name).toHaveValue("Keyboard Student");
  await page.keyboard.press("Enter");
  await expect(confirmation).toBeFocused();
  await page.keyboard.press("Tab");
  await page.keyboard.press("Tab");
  await expect(confirm).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("status")).toContainText("认证资料已提交");
  await expect(heading).toBeFocused();
  await expect(heading).toHaveAccessibleDescription("待审核");

  const historyPhoto = page.getByRole("button", { name: "查看本次证件照片" });
  await expect(historyPhoto).toBeEnabled();
  await expect(historyPhoto).toHaveAccessibleDescription(/Keyboard Student/);
  await page.keyboard.press("Tab");
  await expect(refresh).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(historyPhoto).toBeFocused();
  await page.keyboard.press("Space");
  const dialog = page.getByRole("dialog", { name: "证件照片" });
  await expect(dialog.getByRole("button", { name: "关闭照片" })).toBeFocused();
  await expect(dialog.getByRole("img", { name: /证件照片/ })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await expect(historyPhoto).toBeFocused();
});

test("选择无效照片时控件名称稳定且错误与文件输入关联", async ({
  page,
  request,
}) => {
  await openVerification(page, request);
  const photo = page.getByLabel("学生证 / 校园卡照片", { exact: true });
  await photo.setInputFiles({
    name: "无效照片.txt",
    mimeType: "text/plain",
    buffer: Buffer.from("非图片内容"),
  });
  await expect(photo).toHaveAttribute("aria-invalid", "true");
  await expect(photo).toHaveAccessibleDescription(/请选择不超过 5 MB/);
  await expect(page.getByRole("alert")).toContainText("不超过 5 MB");
  await photo.setInputFiles(photoFixture);
  await expect(photo).not.toHaveAttribute("aria-invalid", "true");
  await expect(page.getByRole("alert")).toBeEmpty();
});
