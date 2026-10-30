import { request } from "../../services/http";

export const orderApi = {
  hall: (params) =>
    request(`/orders?${new URLSearchParams({ status: "pending", ...params })}`),
  hallDetail: (id) => request(`/orders/hall/${encodeURIComponent(id)}`),
  seedHall: () => request("/orders/demo/seed-hall", { method: "POST" }),
  demoStatus: (id, status) =>
    request(`/orders/demo/hall/${encodeURIComponent(id)}/status`, {
      method: "POST",
      body: JSON.stringify({ status }),
    }),
  context: () => request("/orders/integration-context"),
  demoSession: (state) =>
    request("/orders/demo/session", {
      method: "POST",
      body: JSON.stringify({ state }),
    }),
  quote: (draft) =>
    request("/orders/quote", { method: "POST", body: JSON.stringify(draft) }),
  create: (draft, key) =>
    request("/orders", {
      method: "POST",
      headers: { "Idempotency-Key": key },
      body: JSON.stringify(draft),
    }),
  detail: (id) => request(`/orders/${encodeURIComponent(id)}`),
  mine: () => request("/orders/mine"),
  prepay: (id) =>
    request(`/orders/${encodeURIComponent(id)}/prepay`, { method: "POST" }),
  demoPay: (id) =>
    request(`/orders/${encodeURIComponent(id)}/demo-pay`, { method: "POST" }),
};
