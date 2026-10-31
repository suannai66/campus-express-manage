<script setup>
import { onMounted, onBeforeUnmount, ref } from "vue";
import PageHeading from "../../components/PageHeading.vue";
import VerificationPhoto from "./VerificationPhoto.vue";
import { verificationApi, statusLabels, formatTime } from "./verification-api";
const data = ref(null),
  selected = ref(null),
  status = ref("pending"),
  reason = ref(""),
  error = ref(""),
  message = ref("");
const admin = ref(false),
  loading = ref(false),
  busy = ref(false),
  photo = ref(null);
let generation = 0,
  listGeneration = 0,
  disposed = false;
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
    data.value = result;
  } catch (cause) {
    if (!disposed && version === listGeneration) error.value = cause.message;
  } finally {
    if (version === listGeneration) loading.value = false;
  }
}
async function detail(id) {
  const version = ++generation;
  selected.value = null;
  reason.value = "";
  error.value = "";
  try {
    const result = await verificationApi.detail(id);
    if (!disposed && version === generation) selected.value = result;
  } catch (cause) {
    if (!disposed) error.value = cause.message;
  }
}
async function review(decision) {
  if (busy.value || !selected.value) return;
  if (decision === "rejected" && !reason.value.trim()) {
    error.value = "驳回时请填写具体理由。";
    return;
  }
  busy.value = true;
  error.value = "";
  message.value = "";
  const id = selected.value.applicationId;
  try {
    await verificationApi.review(id, {
      decision,
      rejectReason: decision === "rejected" ? reason.value.trim() : null,
      version: selected.value.version,
    });
    message.value = "审核结果已保存，已通知申请人。";
    selected.value = null;
    reason.value = "";
    await load(data.value?.page || 1);
  } catch (cause) {
    error.value = cause.message;
    if (cause.status === 409) {
      await detail(id);
      error.value = cause.message;
    }
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
  <p v-if="error" class="notice" role="alert">{{ error }}</p>
  <p v-if="message" class="notice" role="status">{{ message }}</p>
  <template v-if="admin">
    <section class="panel review-panel">
      <div class="review-tools">
        <label
          >审核状态<select
            v-model="status"
            :disabled="busy || loading"
            @change="
              selected = null;
              load();
            "
          >
            <option value="pending">待审核</option>
            <option value="approved">已通过</option>
            <option value="rejected">已驳回</option>
            <option value="">全部状态</option>
          </select></label
        ><button
          class="outline-button"
          :disabled="busy || loading"
          @click="load(data?.page || 1)"
        >
          刷新申请列表
        </button>
      </div>
      <p v-if="loading">正在加载申请…</p>
      <p v-else-if="data && !data.items.length">当前没有匹配的认证申请</p>
      <ul v-if="data" class="application-list">
        <li v-for="item in data.items" :key="item.applicationId">
          <div>
            <strong>{{ item.realName }}</strong> · {{ item.studentNo }}
            <p>
              {{ statusLabels[item.status] }} · {{ formatTime(item.createdAt) }}
            </p>
          </div>
          <button
            class="text-button"
            :disabled="busy"
            @click="detail(item.applicationId)"
          >
            查看申请详情
          </button>
        </li>
      </ul>
      <div v-if="data && data.total > 20" class="review-tools">
        <button
          :disabled="busy || loading || data.page === 1"
          @click="load(data.page - 1)"
        >
          上一页</button
        ><span>第 {{ data.page }} 页 / 共 {{ data.total }} 条</span
        ><button
          :disabled="busy || loading || data.page * 20 >= data.total"
          @click="load(data.page + 1)"
        >
          下一页
        </button>
      </div>
    </section>
    <section v-if="selected" class="panel review-panel" aria-label="申请详情">
      <h2>申请详情</h2>
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
      <button class="outline-button" @click="photo = selected.applicationId">
        查看证件照片
      </button>
      <form
        v-if="selected.status === 'pending'"
        @submit.prevent="review('rejected')"
      >
        <label
          >驳回理由<textarea
            v-model="reason"
            maxlength="500"
            rows="3"
            :disabled="busy"
            placeholder="驳回时必填，例如证件上的学号不清晰"
          />
        </label>
        <div class="review-tools">
          <button
            class="primary-button"
            type="button"
            :disabled="busy"
            @click="review('approved')"
          >
            通过认证</button
          ><button class="outline-button" type="submit" :disabled="busy">
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
</style>
