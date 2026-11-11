<script setup>
import { onBeforeUnmount, onMounted, ref } from "vue";
import PageHeading from "../../components/PageHeading.vue";
import OrderWorkspace from "./OrderWorkspace.vue";
import { fulfillmentApi as api } from "./api";
import { accessToken } from "../../services/auth-state";
const credit = ref(null),
  error = ref(""),
  busy = ref(false);
let alive = true,
  user,
  timer;
async function load() {
  if (!accessToken() || busy.value) return;
  busy.value = true;
  try {
    user ||= await api.current();
    const result = await api.credit(user.uid);
    if (alive) {
      credit.value = result;
      error.value = "";
    }
  } catch (e) {
    if (alive) error.value = e.message;
  } finally {
    if (alive) busy.value = false;
  }
}
onMounted(() => {
  load();
  timer = setInterval(() => {
    if (!document.hidden) load();
  }, 10000);
});
onBeforeUnmount(() => {
  alive = false;
  clearInterval(timer);
});
</script>
<template>
  <PageHeading
    title="认真对待，每一份信任"
    subtitle="发布者确认收货后可进行评价，信用让校园互助更安心。"
    eyebrow="REVIEWS & CREDIT"
  />
  <div class="summary-grid">
    <div class="panel summary">
      <p>我的信用分</p>
      <strong
        >{{ credit?.score?.toFixed(2) ?? "—" }} <small>/ 5.0</small></strong
      ><span v-if="credit"
        >{{
          {
            new: "新人信用",
            restricted: "限制接单",
            normal: "信用正常",
            good: "信用良好",
          }[credit.level]
        }}
        · 最近 {{ credit.reviewCount }} 条有效评价</span
      ><span v-else>{{ busy ? "正在查询…" : "登录后查询" }}</span
      ><button
        type="button"
        class="secondary-button"
        :disabled="busy"
        @click="load"
      >
        刷新信用
      </button>
    </div>
    <div class="panel summary">
      <p>信用规则</p>
      <h3>最近 30 条取件评价均分</h3>
      <span
        >仅计入作为取件员收到的评价；新人可接单，均分低于 3.0 时限制接单。</span
      >
      <p v-if="credit && !credit.creditEligible" role="status">
        当前信用不足，暂时不能接取新订单，已接订单仍需完成。
      </p>
    </div>
  </div>
  <p v-if="error" role="alert">{{ error }}</p>
  <OrderWorkspace review-only @reviewed="load" />
</template>
<style scoped>
.summary {
  display: flex;
  flex-direction: column;
  align-items: start;
  gap: 10px;
}
.summary strong {
  margin: 4px 0;
}
.summary h3 {
  margin: 10px 0;
}
.summary > span {
  line-height: 1.8;
  font-size: 12px;
  color: #66776c;
}
.secondary-button {
  background: #f1f6f2;
  color: #345a41;
  border: 1px solid #ceddce;
  padding: 9px 14px;
  border-radius: 8px;
  font-size: 12px;
  margin-top: 4px;
}
</style>
