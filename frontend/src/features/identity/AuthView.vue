<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from "vue";
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
const phoneInput = ref(null),
  codeInput = ref(null);
const busy = ref(false),
  sending = ref(false),
  retryAt = ref(0),
  clock = ref(Date.now());
const fields = ref({});
const register = computed(() => route.path === "/register");
const phonePattern = /^1[3-9][0-9]{9}$/;
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
async function focusIfStillThere(element, origin) {
  await nextTick();
  if (element?.isConnected && document.activeElement === origin)
    element.focus();
}
function report(cause, origin) {
  error.value = cause.message;
  fields.value = cause.fields || {};
  if (cause.status === 429) {
    const seconds = Number(cause.fields?.retryAfter || 60);
    retryAt.value = Date.now() + seconds * 1000;
    error.value = `${cause.message}，${seconds} 秒后可重新获取。`;
  }
  const invalidInput = fields.value.phone
    ? phoneInput.value
    : fields.value.code
      ? codeInput.value
      : null;
  if (invalidInput) void focusIfStillThere(invalidInput, origin);
}
async function sendCode(event) {
  if (sending.value || busy.value || remaining.value) return;
  const origin = event.currentTarget;
  error.value = "";
  message.value = "";
  fields.value = {};
  if (!phonePattern.test(phone.value.trim())) {
    report(
      {
        message: "请检查手机号。",
        fields: { phone: "请输入正确的 11 位手机号" },
      },
      origin,
    );
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
    message.value = `验证码已准备好，有效期 5 分钟。${result.retryAfter} 秒后可重新获取。课程演示请使用维护者提供的演示验证码，不会发送真实短信。`;
    void focusIfStillThere(codeInput.value, origin);
  } catch (cause) {
    report(cause, origin);
  } finally {
    sending.value = false;
  }
}
async function submit() {
  if (busy.value || sending.value) return;
  const origin = document.activeElement;
  error.value = "";
  message.value = "";
  fields.value = {};
  const body = { phone: phone.value.trim(), code: code.value.trim() };
  const invalid = {};
  if (!phonePattern.test(body.phone))
    invalid.phone = "请输入正确的 11 位手机号";
  if (!/^[0-9]{6}$/.test(body.code)) invalid.code = "请输入 6 位验证码";
  if (invalid.phone || invalid.code) {
    report({ message: "请检查表单中的输入。", fields: invalid }, origin);
    return;
  }
  busy.value = true;
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
    report(cause, origin);
  } finally {
    busy.value = false;
  }
}
</script>
<template>
  <div class="auth-layout">
    <div class="auth-copy">
      <span class="eyebrow" lang="en">WELCOME TO CAMPUS EXPRESS</span>
      <p class="auth-intro">让每一份托付，<br />都有温暖的回应。</p>
      <p>一个账号，连接校园里的顺路与善意。</p>
      <p class="auth-trust">
        <ShieldCheck :size="20" aria-hidden="true" />学生实名 · 校园互助 ·
        安心送达
      </p>
    </div>
    <form
      class="panel auth-card"
      aria-labelledby="auth-title"
      novalidate
      @submit.prevent="submit"
    >
      <p class="eyebrow" lang="en">
        {{ register ? "CREATE ACCOUNT" : "WELCOME BACK" }}
      </p>
      <h1 id="auth-title">{{ register ? "注册账号" : "登录" }}</h1>
      <p class="muted">
        {{
          register
            ? "使用手机号注册，开启校园互助。"
            : "使用已注册的手机号和验证码登录。"
        }}
      </p>
      <div class="auth-field">
        <label for="auth-phone">手机号</label>
        <input
          id="auth-phone"
          ref="phoneInput"
          v-model="phone"
          autocomplete="tel"
          inputmode="tel"
          pattern="1[3-9][0-9]{9}"
          maxlength="11"
          required
          :readonly="busy || sending"
          placeholder="请输入 11 位手机号"
          :aria-invalid="!!fields.phone"
          :aria-describedby="fields.phone ? 'auth-phone-error' : undefined"
        />
        <small v-if="fields.phone" id="auth-phone-error" class="field-error">{{
          fields.phone
        }}</small>
      </div>
      <div class="auth-field">
        <label for="auth-code">验证码</label>
        <div class="code-field">
          <input
            id="auth-code"
            ref="codeInput"
            v-model="code"
            autocomplete="one-time-code"
            inputmode="numeric"
            pattern="[0-9]{6}"
            maxlength="6"
            required
            :readonly="busy || sending"
            placeholder="6 位验证码"
            :aria-invalid="!!fields.code"
            :aria-describedby="fields.code ? 'auth-code-error' : undefined"
          />
          <button
            type="button"
            class="text-button"
            :aria-disabled="busy || sending || remaining > 0"
            @click="sendCode"
          >
            获取验证码
            <span
              v-if="sending || remaining"
              class="button-feedback"
              aria-hidden="true"
            >
              {{ sending ? "正在获取…" : `${remaining} 秒后重试` }}
            </span>
          </button>
        </div>
        <small v-if="fields.code" id="auth-code-error" class="field-error">{{
          fields.code
        }}</small>
      </div>
      <p role="alert" class="form-message field-error auth-alert">
        {{ error }}
      </p>
      <button
        class="primary-button full-width"
        type="submit"
        :aria-disabled="busy || sending"
      >
        {{ register ? "注册账号" : "登录" }}
        <span v-if="busy" class="button-feedback" aria-hidden="true"
          >正在处理…</span
        >
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

<style scoped>
.auth-alert {
  min-height: 0;
}
.auth-alert:empty {
  margin: 0;
}
.button-feedback {
  display: block;
  font-size: 0.85em;
}
button[aria-disabled="true"] {
  cursor: not-allowed;
}
</style>
