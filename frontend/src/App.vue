<script setup>
import {
  computed,
  nextTick,
  onBeforeUnmount,
  onMounted,
  ref,
  watch,
} from "vue";
import { useRoute, useRouter } from "vue-router";
import { auth, restoreSession, logout } from "./services/session";
import {
  Package,
  LayoutDashboard,
  Compass,
  Plus,
  ClipboardList,
  Star,
  Wallet,
  ShieldCheck,
  ArrowUpRight,
  Menu,
  X,
  ChevronRight,
} from "@lucide/vue";
const route = useRoute();
const router = useRouter();
const exiting = ref(false);
const retryingSession = ref(false);
const sessionError = ref("");
const viewport = window.matchMedia("(max-width: 640px)");
const compact = ref(viewport.matches);
const open = ref(false);
const sidebar = ref(null);
const main = ref(null);
const identityPages = new Set([
  "/login",
  "/register",
  "/verification",
  "/admin/verification",
]);
const identityPage = computed(() => identityPages.has(route.path));

function updateViewport(event) {
  closeNavigation();
  compact.value = event.matches;
}
onMounted(() => {
  viewport.addEventListener("change", updateViewport);
  restoreSession().catch(() => {});
});
onBeforeUnmount(() => viewport.removeEventListener("change", updateViewport));

function focusMain() {
  main.value?.focus();
}
function openNavigation() {
  if (!compact.value || open.value) return;
  sidebar.value.showModal();
  open.value = true;
}
function closeNavigation() {
  if (compact.value && sidebar.value?.open) sidebar.value.close();
  open.value = false;
}
function closeOnBackdrop(event) {
  if (!compact.value) return;
  const bounds = event.currentTarget.getBoundingClientRect();
  if (event.clientX < bounds.left || event.clientX > bounds.right) {
    closeNavigation();
  }
}
function selectCurrentPage(path) {
  if (open.value && path === route.path) {
    closeNavigation();
    focusMain();
  }
}
watch(
  () => [route.path, route.matched.length],
  async ([path], [previous, previousMatches]) => {
    if (!previousMatches) {
      if (path === "/login" && route.query.redirect) {
        await nextTick();
        focusMain();
      }
      return;
    }
    if (path === previous) return;
    const wasOpen = open.value;
    closeNavigation();
    sessionError.value = "";
    if (wasOpen || identityPages.has(path) || identityPages.has(previous)) {
      await nextTick();
      focusMain();
    }
  },
);

async function signOut() {
  if (exiting.value || retryingSession.value) return;
  exiting.value = true;
  sessionError.value = "";
  try {
    await logout();
    const alreadyOnLogin = route.path === "/login";
    await router.push("/login");
    if (alreadyOnLogin) focusMain();
  } catch (error) {
    sessionError.value = `退出失败：${error.message}，请重试。`;
  } finally {
    exiting.value = false;
  }
}
async function retrySession(event) {
  if (retryingSession.value || exiting.value) return;
  const origin = event.currentTarget;
  retryingSession.value = true;
  try {
    await restoreSession();
  } catch {
    // The stable session announcement displays the verification error.
  } finally {
    retryingSession.value = false;
    if (auth.status !== "unavailable") {
      await nextTick();
      if (
        document.activeElement === origin ||
        document.activeElement === document.body
      ) {
        focusMain();
      }
    }
  }
}
const navigation = computed(() => [
  { to: "/", label: "首页概览", icon: LayoutDashboard },
  { to: "/tasks", label: "代取大厅", icon: Compass },
  { to: "/publish", label: "发布代取", icon: Plus },
  { to: "/orders", label: "我的订单", icon: ClipboardList },
  { to: "/reviews", label: "评价与信用", icon: Star },
  { to: "/wallet", label: "我的钱包", icon: Wallet },
  { to: "/verification", label: "学生认证", icon: ShieldCheck },
  ...(auth.user?.role === "admin"
    ? [{ to: "/admin/verification", label: "认证审核", icon: ShieldCheck }]
    : []),
]);
</script>
<template>
  <a class="skip" href="#main" @click.prevent="focusMain">跳到主要内容</a>
  <component
    :is="compact ? 'dialog' : 'aside'"
    id="site-navigation"
    ref="sidebar"
    class="sidebar"
    :aria-label="compact ? '导航菜单' : undefined"
    @click.self="closeOnBackdrop"
    @close="open = false"
  >
    <button
      v-if="compact"
      type="button"
      class="icon-button drawer-close"
      autofocus
      @click="closeNavigation"
    >
      <X :size="20" aria-hidden="true" /> 关闭导航
    </button>
    <RouterLink to="/" class="brand" @click="selectCurrentPage('/')"
      ><span class="brand-icon"><Package :size="25" aria-hidden="true" /></span
      ><span>校园速递<small>CAMPUS EXPRESS</small></span></RouterLink
    >
    <p class="nav-caption">校园服务</p>
    <nav aria-label="主导航">
      <RouterLink
        v-for="item in navigation"
        :key="item.to"
        :to="item.to"
        class="nav-link"
        :class="{ selected: route.path === item.to }"
        @click="selectCurrentPage(item.to)"
        ><component :is="item.icon" :size="19" aria-hidden="true" />{{
          item.label
        }}<ChevronRight
          v-if="route.path === item.to"
          :size="15"
          class="nav-arrow"
          aria-hidden="true"
      /></RouterLink>
    </nav>
    <div class="sidebar-bottom">
      <div class="help-card">
        <span class="help-symbol" aria-hidden="true">↗</span
        ><strong>一份托付，一路安心</strong>
        <p>让顺路的善意，连接校园的你我。</p>
        <RouterLink to="/tasks" @click="selectCurrentPage('/tasks')"
          >去发现顺路任务 <ArrowUpRight :size="15" aria-hidden="true"
        /></RouterLink>
      </div>
      <div class="sidebar-foot">
        <span class="dot"></span>校园互助 · 温暖同行
      </div>
    </div>
  </component>
  <div class="workspace" :class="{ 'identity-page': identityPage }">
    <header class="topbar">
      <div class="topbar-left">
        <button
          class="icon-button mobile-menu"
          type="button"
          aria-label="切换导航"
          aria-controls="site-navigation"
          aria-haspopup="dialog"
          :aria-expanded="open"
          @click="openNavigation"
        >
          <Menu :size="22" aria-hidden="true" /></button
        ><span class="breadcrumb"
          >校园速递 <ChevronRight :size="14" aria-hidden="true" />
          <strong>{{
            route.path === "/" ? "首页概览" : route.meta.title
          }}</strong></span
        >
      </div>
      <div class="topbar-right">
        <span class="preview-label">{{
          [
            "/login",
            "/register",
            "/verification",
            "/admin/verification",
          ].includes(route.path)
            ? "身份认证服务"
            : ["/publish", "/tasks"].includes(route.path)
              ? `${route.meta.title} · 订单服务`
              : ["/orders", "/reviews"].includes(route.path)
                ? `${route.meta.title} · 履约服务`
                : "界面预览 · 示例数据"
        }}</span>
        <template v-if="auth.user">
          <span class="user-link"
            ><span class="avatar" aria-hidden="true">{{
              auth.user.nickname?.[0] || "同"
            }}</span
            ><span>{{ auth.user.nickname || auth.user.phone }}</span></span
          >
          <button
            type="button"
            class="text-button"
            :aria-disabled="exiting"
            @click="signOut"
          >
            退出登录<span v-if="exiting" aria-hidden="true">（正在退出…）</span>
          </button>
        </template>
        <template v-else-if="auth.status === 'unavailable' || retryingSession">
          <button
            type="button"
            class="text-button"
            :aria-disabled="retryingSession || exiting"
            @click="retrySession"
          >
            重试会话核验<span v-if="retryingSession" aria-hidden="true"
              >（正在核验…）</span
            >
          </button>
          <button
            type="button"
            class="text-button"
            :aria-disabled="exiting || retryingSession"
            @click="signOut"
          >
            退出登录<span v-if="exiting" aria-hidden="true">（正在退出…）</span>
          </button>
        </template>
        <RouterLink v-else to="/login" class="user-link"
          ><span class="avatar" aria-hidden="true">访</span
          ><span>登录 / 注册</span></RouterLink
        >
      </div>
    </header>
    <main id="main" ref="main" tabindex="-1" aria-label="主要内容">
      <p
        id="session-alert"
        :class="{ notice: sessionError || auth.error }"
        aria-live="assertive"
        aria-atomic="true"
      >
        {{ sessionError || auth.error }}
      </p>
      <RouterView />
    </main>
    <footer class="page-footer">
      <span>校园速递 CAMPUS EXPRESS</span
      ><span>每一份托付，都值得认真对待。</span>
    </footer>
  </div>
</template>
