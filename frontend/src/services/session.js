import { request } from "./http";
import { auth, accessToken, clearSession, saveToken } from "./auth-state";

export { auth };
export async function restoreSession() {
  if (!accessToken()) {
    clearSession();
    return null;
  }
  auth.status = "loading";
  auth.error = "";
  const token = accessToken();
  try {
    const user = await request("/auth/current");
    if (accessToken() !== token) return null;
    auth.user = user;
    auth.status = "authenticated";
    return user;
  } catch (error) {
    if (accessToken() === token) {
      auth.user = null;
      auth.status = "unavailable";
      auth.error = error.message;
    }
    throw error;
  }
}

export async function login(credentials) {
  const result = await request("/auth/login", {
    method: "POST",
    body: JSON.stringify(credentials),
  });
  saveToken(result.accessToken);
  return restoreSession();
}

export async function logout() {
  // 后端未确认撤销时保留凭证，允许用户再次退出。
  await request("/auth/logout", { method: "POST" });
  clearSession();
}
