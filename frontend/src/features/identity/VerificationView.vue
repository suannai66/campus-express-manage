<script setup>
import { computed, onMounted, onBeforeUnmount, ref } from "vue";
import { ShieldCheck } from "@lucide/vue";
import PageHeading from "../../components/PageHeading.vue";
import VerificationRecords from "./VerificationRecords.vue";
import VerificationPhoto from "./VerificationPhoto.vue";
import { verificationApi, statusLabels } from "./verification-api";
const state = ref(null),
  demoEnabled = ref(false),
  history = ref(null),
  notifications = ref(null),
  busy = ref(false),
  loading = ref(true);
const error = ref(""),
  message = ref(""),
  name = ref(""),
  number = ref(""),
  file = ref(null),
  input = ref(null),
  photo = ref(null);
const canSubmit = computed(
  () =>
    state.value && ["not_submitted", "rejected"].includes(state.value.status),
);
let timer,
  generation = 0,
  disposed = false;
async function refresh() {
  if (disposed) return;
  const version = ++generation;
  loading.value = true;
  error.value = "";
  try {
    const result = await Promise.all([
      verificationApi.status(),
      verificationApi.history(history.value?.page || 1),
      verificationApi.notifications(notifications.value?.page || 1),
    ]);
    if (!disposed && version === generation)
      [state.value, history.value, notifications.value] = result;
  } catch (cause) {
    if (!disposed && version === generation) error.value = cause.message;
  } finally {
    if (!disposed && version === generation) loading.value = false;
  }
}
function choose(event) {
  file.value = null;
  error.value = "";
  const value = event.target.files[0];
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
async function demoApprove() {
  if (busy.value || loading.value || state.value?.status !== "pending") return;
  busy.value = true;
  error.value = "";
  message.value = "";
  try {
    await verificationApi.demoApprove();
    message.value = "演示审核已通过，可以发布需求和接单了。";
    await refresh();
  } catch (cause) {
    await refresh();
    error.value = cause.message;
  } finally {
    busy.value = false;
  }
}
async function submit() {
  if (busy.value || loading.value || !canSubmit.value) return;
  error.value = "";
  message.value = "";
  if (!name.value.trim() || !number.value.trim() || !file.value) {
    error.value = "请填写姓名、学号并选择证件照片。";
    return;
  }
  busy.value = true;
  try {
    const body = new FormData();
    body.append("realName", name.value.trim());
    body.append("studentNo", number.value.trim());
    body.append("photo", file.value);
    const result = await verificationApi.submit(body);
    if (disposed) return;
    state.value = { ...result, verified: false, rejectReason: null };
    message.value = "认证资料已提交，请等待管理员审核。";
    file.value = null;
    if (input.value) input.value.value = "";
    history.value = null;
    await refresh();
  } catch (cause) {
    if (!disposed) {
      error.value = cause.message;
      if (cause.status === 409) await refresh();
    }
  } finally {
    busy.value = false;
  }
}
async function page(kind, value) {
  try {
    if (kind === "history")
      history.value = await verificationApi.history(value);
    else notifications.value = await verificationApi.notifications(value);
  } catch (cause) {
    error.value = cause.message;
  }
}
function refreshPending() {
  if (
    !document.hidden &&
    !busy.value &&
    !loading.value &&
    state.value?.status === "pending"
  )
    refresh();
}
onMounted(() => {
  verificationApi
    .demoCapability()
    .then((result) => {
      if (!disposed) demoEnabled.value = result.enabled;
    })
    .catch(() => {});
  refresh();
  timer = setInterval(refreshPending, 10000);
  document.addEventListener("visibilitychange", refreshPending);
});
onBeforeUnmount(() => {
  disposed = true;
  generation++;
  clearInterval(timer);
  document.removeEventListener("visibilitychange", refreshPending);
});
</script>
<template>
  <PageHeading
    title="确认校园身份，让互助更安心"
    subtitle="学生认证是发布需求和接单的必要条件，接单还需满足信用等规则。"
    eyebrow="STUDENT VERIFICATION"
  >
    <button
      v-if="demoEnabled"
      class="primary-button"
      :disabled="busy || loading || state?.status !== 'pending'"
      @click="demoApprove"
    >
      {{ busy ? "正在处理…" : "自动审核（演示）" }}
    </button>
  </PageHeading>
  <p v-if="error" role="alert" class="notice">{{ error }}</p>
  <p v-if="message" role="status" class="notice">{{ message }}</p>
  <section class="panel form-panel">
    <div class="verification-banner">
      <span class="quick-icon mint"><ShieldCheck /></span>
      <div>
        <h2>学生身份认证</h2>
        <p>提交资料 → 管理员审核 → 查看结果</p>
      </div>
      <span class="soft-tag">{{
        state ? statusLabels[state.status] : "正在查询认证状态"
      }}</span>
    </div>
    <button class="text-button" :disabled="busy || loading" @click="refresh">
      刷新认证结果
    </button>
    <p v-if="state?.status === 'pending'" class="notice">
      资料正在审核，请等待结果，期间不能修改或重复提交。
    </p>
    <p v-if="state?.status === 'approved'" class="notice">
      认证已通过。<RouterLink to="/publish">去发布代取需求</RouterLink>
    </p>
    <p v-if="state?.rejectReason" class="notice">
      驳回理由：{{ state.rejectReason }}。请更正资料后重新提交。
    </p>
    <form v-if="canSubmit" @submit.prevent="submit">
      <fieldset :disabled="busy || loading" class="verification-fields">
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
            ref="input"
            type="file"
            accept="image/jpeg,image/png"
            required
            @change="choose"
          /><span>{{ file ? file.name : "选择清晰、完整的证件照片" }}</span
          ><small
            >JPEG / PNG，单张不超过 5 MB、2500
            万像素。仅本人及审核管理员可查看；课程演示请使用虚构资料。</small
          ></label
        >
        <button class="primary-button" type="submit">
          {{
            busy
              ? "正在提交…"
              : state?.status === "rejected"
                ? "重新提交认证"
                : "提交认证申请"
          }}
        </button>
      </fieldset>
    </form>
  </section>
  <VerificationRecords
    :history="history"
    :notifications="notifications"
    :busy="busy || loading"
    @history-page="page('history', $event)"
    @notification-page="page('notifications', $event)"
    @photo="photo = $event"
  />
  <VerificationPhoto :application-id="photo" @close="photo = null" />
</template>
<style scoped>
.verification-fields {
  border: 0;
  padding: 0;
  margin: 24px 0 0;
  min-width: 0;
}
.verification-banner {
  flex-wrap: wrap;
}
.form-panel {
  overflow-wrap: anywhere;
}
</style>
