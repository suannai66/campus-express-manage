<script setup>
import { onMounted, ref } from "vue";
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
const sessionError = ref("");
onMounted(() => restoreSession().catch(() => {}));
async function signOut() {
  exiting.value = true;
  sessionError.value = "";
  try {
    await logout();
    await router.push("/login");
  } catch (error) {
    sessionError.value = `退出失败：${error.message}，请重试。`;
  } finally {
    exiting.value = false;
  }
}
const open = ref(false);
const navigation = [
  { to: "/", label: "首页概览", icon: LayoutDashboard },
  { to: "/tasks", label: "代取大厅", icon: Compass },
  { to: "/publish", label: "发布代取", icon: Plus },
  { to: "/orders", label: "我的订单", icon: ClipboardList },
  { to: "/reviews", label: "评价与信用", icon: Star },
  { to: "/wallet", label: "我的钱包", icon: Wallet },
  { to: "/verification", label: "学生认证", icon: ShieldCheck },
];
</script>
<template>
  <a class="skip" href="#main">跳到主要内容</a>
  <aside class="sidebar" :class="{ expanded: open }">
    <RouterLink to="/" class="brand" @click="open = false"
      ><span class="brand-icon"><Package :size="25" /></span
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
        @click="open = false"
        ><component :is="item.icon" :size="19" />{{ item.label
        }}<ChevronRight
          v-if="route.path === item.to"
          :size="15"
          class="nav-arrow"
      /></RouterLink>
    </nav>
    <div class="sidebar-bottom">
      <div class="help-card">
        <span class="help-symbol">↗</span><strong>一份托付，一路安心</strong>
        <p>让顺路的善意，连接校园的你我。</p>
        <RouterLink to="/tasks"
          >去发现顺路任务 <ArrowUpRight :size="15"
        /></RouterLink>
      </div>
      <div class="sidebar-foot">
        <span class="dot"></span>校园互助 · 温暖同行
      </div>
    </div>
  </aside>
  <div v-if="open" class="overlay" @click="open = false"></div>
  <div class="workspace">
    <header class="topbar">
      <div class="topbar-left">
        <button
          class="icon-button mobile-menu"
          aria-label="切换导航"
          @click="open = !open"
        >
          <component :is="open ? X : Menu" :size="22" /></button
        ><span class="breadcrumb"
          >校园速递 <ChevronRight :size="14" />
          <strong>{{
            route.path === "/" ? "首页概览" : route.meta.title
          }}</strong></span
        >
      </div>
      <div class="topbar-right">
        <span class="preview-label">{{
          ["/login", "/register"].includes(route.path)
            ? "账号服务"
            : ["/publish", "/tasks"].includes(route.path)
              ? `${route.meta.title} · 订单服务`
              : "界面预览 · 示例数据"
        }}</span>
        <template v-if="auth.user">
          <span class="user-link"
            ><span class="avatar">{{ auth.user.nickname?.[0] || "同" }}</span
            ><span>{{ auth.user.nickname || auth.user.phone }}</span></span
          >
          <button class="text-button" :disabled="exiting" @click="signOut">
            {{ exiting ? "正在退出…" : "退出登录" }}
          </button>
        </template>
        <template v-else-if="auth.status === 'unavailable'">
          <button class="text-button" @click="restoreSession().catch(() => {})">
            重试会话核验
          </button>
          <button class="text-button" :disabled="exiting" @click="signOut">
            退出登录
          </button>
        </template>
        <RouterLink v-else to="/login" class="user-link"
          ><span class="avatar">访</span><span>登录 / 注册</span></RouterLink
        >
      </div>
    </header>
    <main id="main" tabindex="-1">
      <p v-if="sessionError || auth.error" class="notice" role="alert">
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
