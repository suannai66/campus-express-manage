<script setup>
import { computed, nextTick, onMounted, onBeforeUnmount, ref } from "vue";
import PageHeading from "../../components/PageHeading.vue";
import VerificationPhoto from "./VerificationPhoto.vue";
import { verificationApi, statusLabels, formatTime } from "./verification-api";
const data = ref(null),
  selected = ref(null),
  status = ref("pending"),
  reason = ref(""),
  reasonError = ref(""),
  error = ref(""),
  message = ref("");
const admin = ref(false),
  loading = ref(false),
  detailLoading = ref(false),
  busy = ref(false),
  photo = ref(null),
  listPanel = ref(null),
  listHeading = ref(null),
  detailPanel = ref(null),
  detailHeading = ref(null),
  reasonInput = ref(null);
let generation = 0,
  listGeneration = 0,
  disposed = false;

const listStatus = computed(() => {
  if (loading.value) return "正在加载申请…";
  if (!data.value) return "";
  return data.value.items.length
    ? `第 ${data.value.page} 页，共 ${data.value.total} 条申请。`
    : "当前没有匹配的认证申请";
});

async function load(page = 1) {
  const version = ++listGeneration;
  loading.value = true;
  error.value = "";
  try {
    const result = await verificationApi.list(page, status.value);
    if (disposed || version !== listGeneration) return;
    const last = Math.max(1, Math.ceil(result.total / 20));
    if (page > last) {
      await load(last);
      return;
    }
    const previousFocus = document.activeElement;
    const focusWasInList = listPanel.value?.contains(previousFocus);
    data.value = result;
    await nextTick();
    if (
      version === listGeneration &&
      focusWasInList &&
      !previousFocus.isConnected &&
      document.activeElement === document.body
    ) {
      listHeading.value?.focus();
    }
  } catch (cause) {
    if (!disposed && version === listGeneration) error.value = cause.message;
  } finally {
    if (version === listGeneration) loading.value = false;
  }
}
function changeStatus() {
  generation++;
  detailLoading.value = false;
  selected.value = null;
  void load();
}

function goToPage(page) {
  if (
    busy.value ||
    loading.value ||
    page < 1 ||
    page > Math.ceil(data.value.total / 20)
  )
    return;
  void load(page);
}

async function detail(id, trigger = null) {
  if (busy.value && trigger) return;
  const version = ++generation;
  const focusWasInDetail = detailPanel.value?.contains(document.activeElement);
  detailLoading.value = true;
  selected.value = null;
  reason.value = "";
  reasonError.value = "";
  error.value = "";
  try {
    const result = await verificationApi.detail(id);
    if (disposed || version !== generation) return;
    selected.value = result;
    await nextTick();
    if (disposed || version !== generation) return;
    // Keep focus where the reviewer moved it while the request was pending.
    if (
      document.activeElement === trigger ||
      (focusWasInDetail && document.activeElement === document.body)
    ) {
      detailHeading.value?.focus();
    }
  } catch (cause) {
    if (!disposed && version === generation) error.value = cause.message;
  } finally {
    if (version === generation) detailLoading.value = false;
  }
}
async function review(decision) {
  if (busy.value || !selected.value) return;
  if (decision === "rejected" && !reason.value.trim()) {
    reasonError.value = "驳回时请填写具体理由。";
    await nextTick();
    reasonInput.value?.focus();
    return;
  }
  busy.value = true;
  error.value = "";
  reasonError.value = "";
  message.value = "";
  const id = selected.value.applicationId;
  try {
    await verificationApi.review(id, {
      decision,
      rejectReason: decision === "rejected" ? reason.value.trim() : null,
      version: selected.value.version,
    });
    if (disposed) return;
    const focusWasInDetail = detailPanel.value?.contains(
      document.activeElement,
    );
    message.value = "审核结果已保存，已通知申请人。";
    selected.value = null;
    reason.value = "";
    await nextTick();
    if (focusWasInDetail && document.activeElement === document.body) {
      listHeading.value?.focus();
    }
    await load(data.value?.page || 1);
  } catch (cause) {
    if (disposed) return;
    if (cause.status === 409) {
      await detail(id);
    }
    if (!disposed) error.value = cause.message;
  } finally {
    busy.value = false;
  }
}
onMounted(async () => {
  try {
    const user = await verificationApi.current();
    if (user.role !== "admin") {
      error.value = "仅管理员可查看和审核认证申请。";
      return;
    }
    admin.value = true;
    await load();
  } catch (cause) {
    error.value = cause.message;
  }
});
onBeforeUnmount(() => {
  disposed = true;
  generation++;
  listGeneration++;
});
</script>
<template>
  <PageHeading
    title="学生认证审核"
    subtitle="核对姓名、学号与证件；驳回时请填写具体理由。"
    eyebrow="ADMINISTRATION"
  />
  <p :class="{ notice: error }" role="alert">{{ error }}</p>
  <p :class="{ notice: message }" role="status">{{ message }}</p>
  <template v-if="admin">
    <section
      ref="listPanel"
      class="panel review-panel"
      aria-labelledby="review-list-heading"
    >
      <h2 id="review-list-heading" ref="listHeading" tabindex="-1">
        认证申请列表
      </h2>
      <div class="review-tools">
        <label
          >审核状态<select
            v-model="status"
            :disabled="busy"
            @change="changeStatus"
          >
            <option value="pending">待审核</option>
            <option value="approved">已通过</option>
            <option value="rejected">已驳回</option>
            <option value="">全部状态</option>
          </select></label
        ><button
          class="outline-button"
          :aria-disabled="busy || loading"
          @click="!busy && !loading && load(data?.page || 1)"
        >
          刷新申请列表
        </button>
      </div>
      <p aria-live="polite" aria-atomic="true">{{ listStatus }}</p>
      <ul
        v-if="data?.items.length"
        class="application-list"
        role="list"
        :aria-busy="loading"
      >
        <li v-for="item in data.items" :key="item.applicationId">
          <div>
            <strong>{{ item.realName }}</strong> · {{ item.studentNo }}
            <p>
              {{ statusLabels[item.status] }} · {{ formatTime(item.createdAt) }}
            </p>
          </div>
          <button
            class="text-button"
            :aria-label="`查看申请详情：${item.realName}，学号 ${item.studentNo}`"
            :aria-disabled="busy"
            @click="detail(item.applicationId, $event.currentTarget)"
          >
            查看申请详情
          </button>
        </li>
      </ul>
      <div v-if="data && data.total > 20" class="review-tools">
        <button
          :aria-disabled="busy || loading || data.page === 1"
          @click="goToPage(data.page - 1)"
        >
          上一页
        </button>
        <button
          :aria-disabled="busy || loading || data.page * 20 >= data.total"
          @click="goToPage(data.page + 1)"
        >
          下一页
        </button>
      </div>
    </section>
    <p aria-live="polite">{{ detailLoading ? "正在加载申请详情…" : "" }}</p>
    <section
      v-if="selected"
      ref="detailPanel"
      class="panel review-panel"
      aria-labelledby="review-detail-heading"
    >
      <h2 id="review-detail-heading" ref="detailHeading" tabindex="-1">
        申请详情
      </h2>
      <dl>
        <dt>真实姓名</dt>
        <dd>{{ selected.realName }}</dd>
        <dt>学号</dt>
        <dd>{{ selected.studentNo }}</dd>
        <dt>申请编号</dt>
        <dd>{{ selected.applicationId }}</dd>
        <dt>状态 / 版本</dt>
        <dd>{{ statusLabels[selected.status] }} / {{ selected.version }}</dd>
        <dt v-if="selected.rejectReason">驳回理由</dt>
        <dd v-if="selected.rejectReason">{{ selected.rejectReason }}</dd>
      </dl>
      <button
        class="outline-button"
        aria-haspopup="dialog"
        :aria-disabled="busy"
        @click="!busy && (photo = selected.applicationId)"
      >
        查看证件照片
      </button>
      <form
        v-if="selected.status === 'pending'"
        :aria-busy="busy"
        @submit.prevent="review('rejected')"
      >
        <label for="review-reason">驳回理由</label>
        <p id="review-reason-hint">驳回时必填，最多 500 字。</p>
        <textarea
          id="review-reason"
          ref="reasonInput"
          v-model="reason"
          maxlength="500"
          rows="3"
          :readonly="busy"
          :aria-invalid="reasonError ? 'true' : undefined"
          :aria-describedby="
            reasonError
              ? 'review-reason-hint review-reason-error'
              : 'review-reason-hint'
          "
          @input="reasonError = ''"
        />
        <p v-if="reasonError" id="review-reason-error" class="notice">
          {{ reasonError }}
        </p>
        <div class="review-tools">
          <button
            class="primary-button"
            type="button"
            :aria-disabled="busy"
            @click="review('approved')"
          >
            通过认证</button
          ><button class="outline-button" type="submit" :aria-disabled="busy">
            驳回申请
          </button>
        </div>
      </form>
    </section>
  </template>
  <VerificationPhoto :application-id="photo" @close="photo = null" />
</template>
<style scoped>
.review-panel {
  padding: 24px;
  margin: 24px 0;
  overflow-wrap: anywhere;
}
.review-panel h2 {
  width: fit-content;
  margin-bottom: 12px;
  scroll-margin-top: 16px;
}
.review-panel h2:focus {
  outline: 2px solid currentColor;
  outline-offset: 3px;
}
.review-panel button[aria-disabled="true"] {
  cursor: not-allowed;
}
.review-tools {
  display: flex;
  gap: 20px;
  align-items: center;
  flex-wrap: wrap;
}
.application-list {
  list-style: none;
  padding: 0;
}
.application-list li {
  display: flex;
  justify-content: space-between;
  gap: 20px;
  align-items: center;
  padding: 18px 0;
  border-bottom: 1px solid var(--border);
}
.application-list p {
  color: var(--muted);
  font-size: 13px;
}
dt {
  font-weight: 600;
  margin-top: 14px;
}
dd {
  margin: 5px 0;
  color: var(--muted);
}
form {
  margin-top: 24px;
}
form .review-tools {
  margin-top: 12px;
}
</style>
