import { request } from "../../services/http";
const post = (path, body, key) =>
  request(path, {
    method: "POST",
    body: JSON.stringify(body),
    ...(key ? { headers: { "Idempotency-Key": key } } : {}),
  });
export const orderApi = {
  current: () => request("/auth/current"),
  locations: () => request("/orders/locations"),
  hall: (params) =>
    request(`/orders?${new URLSearchParams({ scope: "hall", ...params })}`),
  context: async () => {
    const [user, verification] = await Promise.all([
      request("/auth/current"),
      request("/auth/verify-status"),
    ]);
    return { user, verified: verification.verified === true };
  },
  quote: (draft) => post("/orders/quote", draft),
  create: (draft, key) => post("/orders", draft, key),
  detail: (id) => request(`/orders/${encodeURIComponent(id)}`),
  mine: () => request("/orders?scope=mine&role=publisher"),
  reservePayment: (id, version, key) =>
    post(`/orders/${encodeURIComponent(id)}/payment-request`, { version }, key),
  prepay: (orderId, paymentRequestId, key) =>
    post("/pay/prepay", { orderId, paymentRequestId }, key),
  accept: (id, version, key) =>
    post(`/orders/${encodeURIComponent(id)}/accept`, { version }, key),
};
export const sizeLabels = { small: "小件", medium: "中件", large: "大件" };
export const formatTime = (value) =>
  new Date(value).toLocaleString("zh-CN", {
    timeZone: "Asia/Shanghai",
    hour12: false,
  });
