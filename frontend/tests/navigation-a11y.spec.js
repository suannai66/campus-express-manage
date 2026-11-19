import { expect, test } from "@playwright/test";

test("窄屏导航保持焦点、可退出并将焦点送到目标页主区", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 720 });
  await page.goto("/");
  const main = page.getByRole("main");
  const skip = page.getByRole("link", { name: "跳到主要内容" });
  const toggle = page.getByRole("button", { name: "切换导航" });
  const drawer = page.getByRole("dialog", { name: "导航菜单" });
  const close = drawer.getByRole("button", { name: "关闭导航" });

  await expect(drawer).toHaveCount(0);
  await expect(page.getByRole("navigation", { name: "主导航" })).toHaveCount(0);
  await page.keyboard.press("Tab");
  await expect(skip).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(main).toBeFocused();
  await page.keyboard.press("Shift+Tab");
  await expect(page.getByRole("link", { name: "登录 / 注册" })).toBeFocused();
  await page.keyboard.press("Shift+Tab");
  await expect(toggle).toBeFocused();
  await page.keyboard.press("Space");
  await expect(drawer).toBeVisible();
  await expect(close).toBeFocused();
  await expect(
    page.locator('[aria-controls="site-navigation"]'),
  ).toHaveAttribute("aria-expanded", "true");
  await page.keyboard.press("Escape");
  await expect(toggle).toBeFocused();
  await expect(toggle).toHaveAttribute("aria-expanded", "false");

  await page.keyboard.press("Enter");
  await expect(close).toBeFocused();
  const verification = drawer.getByRole("link", { name: "学生认证" });
  for (let index = 0; index < 8; index++) {
    await page.keyboard.press("Tab");
  }
  await expect(verification).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/login\?redirect=%2Fverification$/);
  await expect(
    page.getByRole("heading", { level: 1, name: "登录" }),
  ).toBeVisible();
  await expect(drawer).toHaveCount(0);
  await expect(main).toBeFocused();
});
