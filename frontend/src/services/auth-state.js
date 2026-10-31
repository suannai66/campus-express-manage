import { reactive } from "vue";

export const auth = reactive({ user: null, status: "anonymous", error: "" });
export const accessToken = () => sessionStorage.getItem("accessToken");
export function clearSession() {
  sessionStorage.removeItem("accessToken");
  auth.user = null;
  auth.status = "anonymous";
  auth.error = "";
}
export function saveToken(token) {
  sessionStorage.setItem("accessToken", token);
}
