// 唯一请求入口。公共鉴权接入后，在此统一处理凭证与 401。
export async function request(path, options = {}) {
  const headers = new Headers(options.headers);
  if (options.body && !(options.body instanceof FormData))
    headers.set("Content-Type", "application/json");
  const response = await fetch(`/api${path}`, {
    ...options,
    headers,
    credentials: "same-origin",
  });
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const error = new Error(
      typeof data?.detail === "string"
        ? data.detail
        : `请求失败（${response.status}）`,
    );
    error.status = response.status;
    throw error;
  }
  return data;
}
