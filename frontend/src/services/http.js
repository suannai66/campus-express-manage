// F1 统一凭证由请求入口附加；F3/F4 不持有独立登录状态。
import { accessToken, clearSession } from "./auth-state";
export function safeRedirect(value) {
  if (
    typeof value !== "string" ||
    !value.startsWith("/") ||
    value.startsWith("//") ||
    /[\\\r\n]/.test(value)
  )
    return "/";
  const target = new URL(value, window.location.origin);
  return target.origin === window.location.origin
    ? target.pathname + target.search + target.hash
    : "/";
}

export async function request(path, options = {}) {
  const { responseType, ...fetchOptions } = options;
  const headers = new Headers(options.headers);
  const token = accessToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (options.body && !(options.body instanceof FormData))
    headers.set("Content-Type", "application/json");
  const response = await fetch(`/api${path}`, {
    ...fetchOptions,
    headers,
    credentials: "same-origin",
  });
  const data =
    response.ok && responseType === "blob"
      ? await response.blob()
      : await response.json().catch(() => null);
  if (!response.ok) {
    const error = new Error(
      typeof data?.detail === "string"
        ? data.detail
        : `请求失败（${response.status}）`,
    );
    error.status = response.status;
    error.code = data?.code;
    error.fields = data?.fields || {};
    if (response.status === 401 && accessToken() === token) {
      clearSession();
      if (!["/login", "/register"].includes(location.pathname)) {
        const redirect = safeRedirect(location.pathname + location.search);
        window.location.assign(
          `/login?redirect=${encodeURIComponent(redirect)}`,
        );
      }
    }
    throw error;
  }
  return data;
}
