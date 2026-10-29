import { createRouter, createWebHistory } from "vue-router";
export const routes = [
  {
    path: "/",
    component: () => import("../views/HomeView.vue"),
    meta: { title: "校园生活，轻松一点" },
  },
  {
    path: "/tasks",
    component: () => import("../features/orders/TaskHallView.vue"),
    meta: { title: "代取大厅" },
  },
  {
    path: "/publish",
    component: () => import("../features/orders/PublishView.vue"),
    meta: { title: "发布代取" },
  },
  {
    path: "/orders",
    component: () => import("../features/fulfillment/OrdersView.vue"),
    meta: { title: "我的订单" },
  },
  {
    path: "/reviews",
    component: () => import("../features/fulfillment/ReviewsView.vue"),
    meta: { title: "评价与信用" },
  },
  {
    path: "/wallet",
    component: () => import("../features/finance/WalletView.vue"),
    meta: { title: "我的钱包" },
  },
  {
    path: "/verification",
    component: () => import("../features/identity/VerificationView.vue"),
    meta: { title: "学生认证" },
  },
  {
    path: "/login",
    component: () => import("../features/identity/AuthView.vue"),
    meta: { title: "登录" },
  },
  {
    path: "/register",
    component: () => import("../features/identity/AuthView.vue"),
    meta: { title: "注册" },
  },
  {
    path: "/admin/verification",
    component: () => import("../features/identity/ReviewView.vue"),
    meta: { title: "认证审核" },
  },
  {
    path: "/:pathMatch(.*)*",
    component: () => import("../views/NotFoundView.vue"),
    meta: { title: "页面未找到" },
  },
];
const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior: () => ({ top: 0 }),
});
router.afterEach((to) => {
  document.title = `${to.meta.title} · 校园速递`;
});
export default router;
