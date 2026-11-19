<script setup>
import { formatTime, statusLabels } from "./verification-api";
defineProps({ history: Object, notifications: Object, busy: Boolean });
defineEmits(["history-page", "notification-page", "photo"]);
</script>
<template>
  <section class="panel records" aria-labelledby="verification-history-title">
    <h2 id="verification-history-title">申请历史</h2>
    <p v-if="!history">申请历史尚未加载</p>
    <p v-else-if="!history.items.length">还没有认证申请</p>
    <ul v-else class="record-list" role="list">
      <li v-for="item in history.items" :key="item.applicationId">
        <div>
          <strong :id="`verification-history-context-${item.applicationId}`"
            >{{ item.realName }} · {{ item.studentNo }}</strong
          ><span class="soft-tag">{{ statusLabels[item.status] }}</span>
        </div>
        <p>
          {{ formatTime(item.createdAt) }} · 申请编号 {{ item.applicationId }}
        </p>
        <p v-if="item.rejectReason">驳回理由：{{ item.rejectReason }}</p>
        <button
          class="text-button"
          type="button"
          :disabled="busy"
          :aria-describedby="`verification-history-context-${item.applicationId}`"
          @click="$emit('photo', item.applicationId)"
        >
          查看本次证件照片
        </button>
      </li>
    </ul>
    <div
      v-if="history && history.total > 20"
      class="pager"
      role="group"
      aria-label="申请历史分页"
    >
      <button
        :disabled="busy || history.page === 1"
        @click="$emit('history-page', history.page - 1)"
      >
        上一页申请
      </button>
      <span aria-live="polite">
        第 {{ history.page }} 页 / 共 {{ history.total }} 条
      </span>
      <button
        :disabled="busy || history.page * 20 >= history.total"
        @click="$emit('history-page', history.page + 1)"
      >
        下一页申请
      </button>
    </div>
  </section>
  <section
    class="panel records"
    aria-labelledby="verification-notifications-title"
  >
    <h2 id="verification-notifications-title">审核结果通知</h2>
    <p v-if="!notifications">通知尚未加载</p>
    <p v-else-if="!notifications.items.length">暂无审核结果通知</p>
    <ul v-else class="record-list" role="list">
      <li v-for="item in notifications.items" :key="item.notificationId">
        <strong>{{ statusLabels[item.status] }}</strong>
        <p>
          {{
            item.rejectReason || "你的学生身份认证已通过，可以发布代取需求。"
          }}
        </p>
        <small
          >{{ formatTime(item.createdAt) }} · 申请编号
          {{ item.applicationId }}</small
        >
      </li>
    </ul>
    <div
      v-if="notifications && notifications.total > 20"
      class="pager"
      role="group"
      aria-label="审核结果通知分页"
    >
      <button
        :disabled="busy || notifications.page === 1"
        @click="$emit('notification-page', notifications.page - 1)"
      >
        上一页通知
      </button>
      <span aria-live="polite"
        >第 {{ notifications.page }} 页 / 共 {{ notifications.total }} 条</span
      >
      <button
        :disabled="busy || notifications.page * 20 >= notifications.total"
        @click="$emit('notification-page', notifications.page + 1)"
      >
        下一页通知
      </button>
    </div>
  </section>
</template>
<style scoped>
.records {
  padding: 24px;
  margin-top: 24px;
}
.records h2 {
  margin: 0 0 20px;
}
.record-list {
  list-style: none;
  padding: 0;
  margin: 0;
}
.record-list li {
  padding: 18px 0;
  border-bottom: 1px solid var(--border);
  overflow-wrap: anywhere;
}
.record-list li > div {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: center;
}
.record-list p,
.record-list small {
  color: var(--muted);
  font-size: 13px;
}
.pager {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
  align-items: center;
  margin-top: 20px;
}
.pager button {
  padding: 8px;
}
</style>
