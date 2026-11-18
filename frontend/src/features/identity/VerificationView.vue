<script setup>
import {
  computed,
  nextTick,
  onMounted,
  onBeforeUnmount,
  ref,
  watch,
} from "vue";
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
  checking = ref(false),
  loading = ref(true);
const error = ref(""),
  message = ref(""),
  name = ref(""),
  number = ref(""),
  file = ref(null),
  input = ref(null),
  photo = ref(null),
  confirmation = ref(null),
  confirmTitle = ref(null),
  submitButton = ref(null);
const canSubmit = computed(
  () =>
    state.value && ["not_submitted", "rejected"].includes(state.value.status),
);
let timer,
  generation = 0,
  previewUrl = "",
  disposed = false;
function clearConfirmation() {
  confirmation.value = null;
  if (previewUrl) URL.revokeObjectURL(previewUrl);
  previewUrl = "";
}
watch(canSubmit, (allowed) => {
  if (!allowed) clearConfirmation();
});
async function returnToEdit() {
  if (busy.value) return;
  clearConfirmation();
  error.value = "";
  await nextTick();
  submitButton.value?.focus();
}
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
async function prepareConfirmation() {
  if (
    busy.value ||
    checking.value ||
    loading.value ||
    !canSubmit.value ||
    confirmation.value
  )
    return;
  error.value = "";
  message.value = "";
  if (!name.value.trim() || !number.value.trim() || !file.value) {
    error.value = "请填写姓名、学号并选择证件照片。";
    return;
  }
  checking.value = true;
  const draft = {
    realName: name.value.trim(),
    studentNo: number.value.trim(),
    photo: file.value,
  };
  previewUrl = URL.createObjectURL(draft.photo);
  try {
    const image = new Image();
    image.src = previewUrl;
    await image.decode();
    if (image.naturalWidth * image.naturalHeight > 25_000_000) {
      throw new Error("照片像素过大，请选择不超过2500万像素的照片。");
    }
    if (disposed || !canSubmit.value) {
      clearConfirmation();
      return;
    }
    confirmation.value = { ...draft, previewUrl };
    await nextTick();
    confirmTitle.value?.focus();
  } catch (cause) {
    clearConfirmation();
    if (!disposed)
      error.value = cause.message.includes("像素")
        ? cause.message
        : "照片内容无效或无法预览，请重新选择清晰的JPEG / PNG照片。";
  } finally {
    checking.value = false;
  }
}
async function submit() {
  if (
    busy.value ||
    checking.value ||
    loading.value ||
    !canSubmit.value ||
    !confirmation.value
  )
    return;
  const draft = confirmation.value;
  error.value = "";
  message.value = "";
  busy.value = true;
  try {
    const body = new FormData();
    body.append("realName", draft.realName);
    body.append("studentNo", draft.studentNo);
    body.append("photo", draft.photo);
    const result = await verificationApi.submit(body);
    if (disposed) return;
    state.value = { ...result, verified: false, rejectReason: null };
    clearConfirmation();
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
  clearConfirmation();
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
    <button
      class="text-button"
      :disabled="busy || checking || loading"
      @click="refresh"
    >
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
    <form
      v-if="canSubmit"
      v-show="!confirmation"
      @submit.prevent="prepareConfirmation"
    >
      <fieldset
        :disabled="busy || checking || loading"
        class="verification-fields"
      >
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
        <button ref="submitButton" class="primary-button" type="submit">
          {{
            checking
              ? "正在检查照片…"
              : state?.status === "rejected"
                ? "重新提交认证"
                : "提交认证申请"
          }}
        </button>
      </fieldset>
    </form>
    <section
      v-if="confirmation"
      aria-labelledby="verification-confirm-title"
      class="verification-confirmation"
    >
      <h3 id="verification-confirm-title" ref="confirmTitle" tabindex="-1">
        确认认证资料
      </h3>
      <p>
        请核对以下资料。确认提交后进入管理员审核，待审核期间不能修改或重复提交。
      </p>
      <dl>
        <dt>真实姓名</dt>
        <dd>{{ confirmation.realName }}</dd>
        <dt>学号</dt>
        <dd>{{ confirmation.studentNo }}</dd>
      </dl>
      <img :src="confirmation.previewUrl" alt="本次待提交的学生证件照片" />
      <p class="muted">仅本人及审核管理员可查看认证资料。</p>
      <div class="confirmation-actions">
        <button
          type="button"
          class="outline-button"
          :disabled="busy"
          @click="returnToEdit"
        >
          返回修改
        </button>
        <button
          type="button"
          class="primary-button"
          :disabled="busy || loading"
          @click="submit"
        >
          {{ busy ? "正在提交…" : "确认提交" }}
        </button>
      </div>
    </section>
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
.verification-confirmation {
  margin-top: 24px;
}
.verification-confirmation dl {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 12px 20px;
  margin: 20px 0;
}
.verification-confirmation dd {
  margin: 0;
}
.verification-confirmation img {
  display: block;
  max-width: 100%;
  max-height: 360px;
  object-fit: contain;
  margin: 20px 0;
}
.confirmation-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 20px;
}
</style>
