<script setup>
import { onMounted, ref } from "vue";
import { ShieldCheck } from "@lucide/vue";
import PageHeading from "../../components/PageHeading.vue";
import { request } from "../../services/http";
const verification = ref(null),
  statusError = ref("");
const labels = {
  not_submitted: "未提交认证",
  pending: "待审核",
  approved: "认证已通过",
  rejected: "认证已驳回",
};
async function loadStatus() {
  statusError.value = "";
  try {
    verification.value = await request("/auth/verify-status");
  } catch (cause) {
    statusError.value = cause.message;
  }
}
onMounted(loadStatus);
const name = ref(""),
  number = ref(""),
  error = ref(""),
  file = ref(null);
function choose(event) {
  const value = event.target.files[0];
  file.value = null;
  error.value = "";
  if (!value) return;
  if (
    !["image/jpeg", "image/png"].includes(value.type) ||
    value.size > 5 * 1024 * 1024
  ) {
    error.value = "请选择不超过 5 MB 的 JPEG / PNG 照片。";
    event.target.value = "";
    return;
  }
  file.value = value;
}
function submit() {
  error.value = file.value
    ? "认证服务尚未接入，资料未上传，也未进入审核。"
    : "请先选择证件照片。";
}
</script>
<template>
  <PageHeading
    title="确认校园身份，让互助更安心"
    subtitle="学生认证是发布需求和接单的必要条件，接单还需满足信用等规则。"
    eyebrow="STUDENT VERIFICATION"
  />
  <div class="notice">
    当前可查询认证状态；资料提交与审核功能暂未开放，下方资料不会上传或保存。
  </div>
  <p v-if="statusError" role="alert" class="notice">
    {{ statusError }}
    <button class="text-button" @click="loadStatus">重试查询</button>
  </p>
  <p v-if="verification?.rejectReason" role="status" class="notice">
    驳回理由：{{ verification.rejectReason }}
  </p>
  <section class="panel form-panel">
    <div class="verification-banner">
      <span class="quick-icon mint"><ShieldCheck /></span>
      <div>
        <h2>学生身份认证</h2>
        <p class="muted">提交资料 → 管理员审核 → 查看结果</p>
      </div>
      <span class="soft-tag">{{
        verification ? labels[verification.status] : "尚未查询认证状态"
      }}</span>
    </div>
    <form @submit.prevent="submit">
      <div class="form-grid">
        <label
          >真实姓名<input
            v-model="name"
            required
            maxlength="30"
            placeholder="与证件上的姓名保持一致" /></label
        ><label
          >学号<input
            v-model="number"
            required
            maxlength="30"
            placeholder="请输入完整学号"
        /></label>
      </div>
      <label class="upload-area"
        >学生证 / 校园卡照片<input
          type="file"
          accept="image/jpeg,image/png"
          @change="choose"
        /><span>{{ file ? file.name : "选择清晰、完整的证件照片" }}</span
        ><small
          >JPEG / PNG，单张不超过 5
          MB。仅本人及有审核权限的管理员可查看。</small
        ></label
      >
      <div class="form-actions">
        <button class="primary-button">预览认证提交</button>
        <p role="status">{{ error }}</p>
      </div>
    </form>
  </section>
</template>
