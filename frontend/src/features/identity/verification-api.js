import { request } from "../../services/http";

export const statusLabels = {
  not_submitted: "未提交认证",
  pending: "待审核",
  approved: "认证已通过",
  rejected: "认证已驳回",
};
export const formatTime = (value) =>
  value
    ? new Date(value).toLocaleString("zh-CN", {
        timeZone: "Asia/Singapore",
        hour12: false,
      })
    : "—";
export const verificationApi = {
  current: () => request("/auth/current"),
  status: () => request("/auth/verify-status"),
  history: (page) =>
    request(`/auth/verification-applications?page=${page}&pageSize=20`),
  notifications: (page) =>
    request(`/auth/verification-notifications?page=${page}&pageSize=20`),
  submit: (form) =>
    request("/auth/verification-applications", { method: "POST", body: form }),
  list: (page, status) =>
    request(
      `/admin/verification-applications?${new URLSearchParams({ page, pageSize: 20, ...(status ? { status } : {}) })}`,
    ),
  detail: (id) =>
    request(`/admin/verification-applications/${encodeURIComponent(id)}`),
  review: (id, body) =>
    request(
      `/admin/verification-applications/${encodeURIComponent(id)}/review`,
      { method: "POST", body: JSON.stringify(body) },
    ),
  photo: (id) =>
    request(`/auth/verification-applications/${encodeURIComponent(id)}/photo`, {
      responseType: "blob",
    }),
};
