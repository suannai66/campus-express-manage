<script setup>
import { computed, ref } from "vue";
import { useRoute } from "vue-router";
import { ShieldCheck } from "@lucide/vue";
const route = useRoute(),
  phone = ref(""),
  code = ref(""),
  message = ref("");
const register = computed(() => route.path === "/register");
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
    <form
      class="panel auth-card"
      @submit.prevent="
        message = '界面校验通过。账号服务尚未接入，当前未建立登录会话。'
      "
    >
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
          placeholder="请输入 11 位手机号" /></label
      ><label
        >验证码
        <div class="code-field">
          <input
            v-model="code"
            autocomplete="one-time-code"
            inputmode="numeric"
            pattern="[0-9]{6}"
            maxlength="6"
            required
            placeholder="6 位验证码"
          /><button
            type="button"
            class="text-button"
            @click="message = '验证码服务尚未接入，当前不会发送短信。'"
          >
            获取验证码
          </button>
        </div></label
      ><button class="primary-button full-width" type="submit">
        {{ register ? "注册账号" : "登录" }}
      </button>
      <p role="status" class="form-message">
        {{ message || "界面预览：尚未提供注册和登录服务。" }}
      </p>
      <p class="auth-switch">
        {{ register ? "已有账号？" : "还没有账号？"
        }}<RouterLink
          :to="register ? '/login' : '/register'"
          @click="
            message = '';
            code = '';
          "
          >{{ register ? "去登录" : "立即注册" }}</RouterLink
        >
      </p>
    </form>
  </div>
</template>
