import { request } from "../../services/http";
export { formatTime, sizeLabels } from "../orders/api";
const path = (id) => `/orders/${encodeURIComponent(id)}`;
const post = (url, body, key) =>
  request(url, {
    method: "POST",
    body: JSON.stringify(body),
    ...(key ? { headers: { "Idempotency-Key": key } } : {}),
  });
export const fulfillmentApi = {
  current: () => request("/auth/current"),
  mine: (params) =>
    request(`/orders?${new URLSearchParams({ scope: "mine", ...params })}`),
  detail: (id) => request(path(id)),
  advance: (id, body, key) => post(`${path(id)}/status`, body, key),
  cancel: (id, body, key) => post(`${path(id)}/cancel`, body, key),
  notifications: (id) => request(`${path(id)}/notifications`),
  reviews: (id) => request(`${path(id)}/reviews`),
  review: (id, body) => post(`${path(id)}/reviews`, body),
  credit: (uid) => request(`/users/${encodeURIComponent(uid)}/credit`),
};
export const statusLabels = {
  pending_payment: "待支付",
  pending: "待接单",
  accepted: "已接单",
  picking_up: "取件中",
  delivering: "配送中",
  delivered: "已送达",
  cancelled: "已取消",
};
export const money = (value) => `¥${(value / 100).toFixed(2)}`;
