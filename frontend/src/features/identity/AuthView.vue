<script setup>
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ShieldCheck } from "@lucide/vue";
import { request, safeRedirect } from "../../services/http";
import { login } from "../../services/session";

const route = useRoute(),
  router = useRouter();
const phone = ref(""),
  code = ref(""),
  message = ref(""),
  error = ref("");
const busy = ref(false),
  sending = ref(false),
  retryAt = ref(0),
  clock = ref(Date.now());
const fields = ref({});
const register = computed(() => route.path === "/register");
const remaining = computed(() =>
  Math.max(0, Math.ceil((retryAt.value - clock.value) / 1000)),
);
const timer = setInterval(() => {
  clock.value = Date.now();
}, 500);
onBeforeUnmount(() => clearInterval(timer));
watch(
  () => route.path,
  () => {
    code.value = "";
    message.value = "";
    error.value = "";
    fields.value = {};
    retryAt.value = 0;
  },
);
function report(cause) {
  error.value = cause.message;
  fields.value = cause.fields || {};
  if (cause.status === 429)
    retryAt.value = Date.now() + Number(cause.fields?.retryAfter || 60) * 1000;
}
async function sendCode() {
  if (sending.value || busy.value || remaining.value) return;
  error.value = "";
  message.value = "";
  fields.value = {};
  if (!/^1[3-9][0-9]{9}$/.test(phone.value.trim())) {
    error.value = "请输入正确的 11 位手机号";
    return;
  }
  sending.value = true;
  try {
    const result = await request("/auth/codes", {
      method: "POST",
      body: JSON.stringify({
        phone: phone.value.trim(),
        purpose: register.value ? "register" : "login",
      }),
    });
    retryAt.value = Date.now() + result.retryAfter * 1000;
    message.value =
      "验证码已准备好，有效期 5 分钟。课程演示请使用维护者提供的演示验证码，不会发送真实短信。";
  } catch (cause) {
    report(cause);
  } finally {
    sending.value = false;
  }
}
async function submit() {
  if (busy.value || sending.value) return;
  busy.value = true;
  error.value = "";
  message.value = "";
  fields.value = {};
  const body = { phone: phone.value.trim(), code: code.value.trim() };
  try {
    if (register.value) {
      await request("/auth/register", {
        method: "POST",
        body: JSON.stringify(body),
      });
      await router.push({
        path: "/login",
        query: { redirect: safeRedirect(route.query.redirect) },
      });
      message.value = "注册成功，请获取登录验证码后登录。";
    } else {
      await login(body);
      await router.replace(safeRedirect(route.query.redirect));
    }
  } catch (cause) {
    report(cause);
  } finally {
    busy.value = false;
  }
}
</script>
<template>
  <div class="auth-layout">
    <div class="auth-copy">
      <span class="eyebrow">WELCOME TO CAMPUS EXPRESS</span>
      <h1>让每一份托付，<br />都有温暖的回应。</h1>
      <p>一个账号，连接校园里的顺路与善意。</p>
      <p class="auth-trust">
        <ShieldCheck :size="20" />学生实名 · 校园互助 · 安心送达
      </p>
    </div>
    <form class="panel auth-card" @submit.prevent="submit">
      <p class="eyebrow">{{ register ? "CREATE ACCOUNT" : "WELCOME BACK" }}</p>
      <h2>{{ register ? "加入校园速递" : "欢迎回来" }}</h2>
      <p class="muted">
        {{
          register
            ? "使用手机号注册，开启校园互助。"
            : "使用已注册的手机号和验证码登录。"
        }}
      </p>
      <label
        >手机号<input
          v-model="phone"
          autocomplete="tel"
          inputmode="tel"
          pattern="1[3-9][0-9]{9}"
          maxlength="11"
          required
          :disabled="busy || sending"
          placeholder="请输入 11 位手机号"
          :aria-invalid="!!fields.phone"
      /></label>
      <small v-if="fields.phone" class="field-error">{{ fields.phone }}</small>
      <label
        >验证码
        <div class="code-field">
          <input
            aria-label="验证码"
            v-model="code"
            autocomplete="one-time-code"
            inputmode="numeric"
            pattern="[0-9]{6}"
            maxlength="6"
            required
            :disabled="busy || sending"
            placeholder="6 位验证码"
            :aria-invalid="!!fields.code"
          />
          <button
            type="button"
            class="text-button"
            :disabled="busy || sending || remaining > 0"
            @click="sendCode"
          >
            {{
              sending
                ? "正在获取…"
                : remaining
                  ? `${remaining} 秒后重试`
                  : "获取验证码"
            }}
          </button>
        </div>
      </label>
      <small v-if="fields.code" class="field-error">{{ fields.code }}</small>
      <p v-if="error" role="alert" class="form-message field-error">
        {{ error }}
      </p>
      <button
        class="primary-button full-width"
        type="submit"
        :disabled="busy || sending"
      >
        {{ busy ? "正在处理…" : register ? "注册账号" : "登录" }}
      </button>
      <p role="status" class="form-message">
        {{ message || "课程演示使用模拟验证码，不发送真实短信。" }}
      </p>
      <p class="auth-switch">
        {{ register ? "已有账号？" : "还没有账号？" }}
        <RouterLink
          :to="{
            path: register ? '/login' : '/register',
            query: { redirect: safeRedirect(route.query.redirect) },
          }"
          >{{ register ? "去登录" : "立即注册" }}</RouterLink
        >
      </p>
    </form>
  </div>
</template>
