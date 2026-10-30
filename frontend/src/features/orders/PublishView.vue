<script setup>
import {
  computed,
  nextTick,
  onMounted,
  onBeforeUnmount,
  reactive,
  ref,
  watch,
} from "vue";
import { useRoute, useRouter } from "vue-router";
import { Package, MapPin, ShieldCheck, Check, Clock, X } from "@lucide/vue";
import PageHeading from "../../components/PageHeading.vue";
import { orderApi } from "./api";

const route = useRoute();
const router = useRouter();
const freshDraft = () => ({
  company: "",
  code: "",
  station: "",
  size: "小件",
  weight: "1",
  address: "",
  time: "",
  tip: "0",
  note: "",
});
const draft = reactive(freshDraft());
const context = ref(null),
  loading = ref(true),
  busy = ref(false),
  error = ref("");
const submitted = ref(false),
  fees = ref(null),
  quoteError = ref(""),
  quoting = ref(false);
const order = ref(null),
  recent = ref([]),
  paymentDialog = ref(null),
  paymentError = ref("");
let quoteTimer,
  quoteVersion = 0,
  requestKey = "",
  requestSnapshot = "";
const money = (cents) => (Number(cents) / 100).toFixed(2);
const canPublish = computed(
  () => context.value?.user && context.value?.verified,
);
const demoState = computed(() =>
  !context.value?.user
    ? "guest"
    : context.value.verified
      ? "verified"
      : "unverified",
);
const errors = computed(() => {
  const result = {};
  for (const [key, label] of Object.entries({
    company: "快递公司",
    code: "取件码",
    station: "取件点",
    address: "送达地址",
  })) {
    if (!draft[key].trim()) result[key] = `请填写${label}`;
  }
  if (
    !Number.isFinite(Number(draft.weight)) ||
    Number(draft.weight) <= 0 ||
    Number(draft.weight) > 30 ||
    !/^\d+(\.\d{1,2})?$/.test(draft.weight)
  )
    result.weight = "重量需大于 0 且不超过 30 kg，最多两位小数";
  if (!/^\d+(\.\d{1,2})?$/.test(draft.tip) || Number(draft.tip) > 999)
    result.tip = "请输入 0 至 999 元的小费，最多两位小数";
  const time = new Date(draft.time).getTime();
  if (
    !Number.isFinite(time) ||
    time <= Date.now() ||
    time > Date.now() + 7 * 86400000
  )
    result.time = "请选择未来七天内的送达时间";
  return result;
});
const payload = () => ({
  company: draft.company.trim(),
  code: draft.code.trim(),
  station: draft.station.trim(),
  size: draft.size,
  weight: draft.weight,
  address: draft.address.trim(),
  expectedAt: new Date(draft.time).toISOString(),
  tip: draft.tip,
  note: draft.note.trim(),
});
const feeDisplay = computed(() => order.value || fees.value);
const statusLabels = {
  awaiting_payment: "待支付",
  pending: "待接单",
  accepted: "已接单",
  picking_up: "取件中",
  delivering: "配送中",
  delivered: "已送达",
  cancelled: "已取消",
  locked: "已锁定",
};
const statusText = computed(
  () => statusLabels[order.value?.status] || "状态更新中",
);
const resultTitle = computed(
  () =>
    ({
      awaiting_payment: "订单已创建，支付后发布",
      pending: "需求已发布，等待同学接单",
      accepted: "同学已接单，请留意配送进度",
      picking_up: "同学正在取件",
      delivering: "包裹正在送来的路上",
      delivered: "包裹已送达",
      cancelled: "订单已取消",
      locked: "订单已锁定，请查看履约通知",
    })[order.value?.status] || "订单状态已更新",
);
const sections = [
  {
    title: "取件信息",
    description: "让同学准确找到你的包裹",
    icon: Package,
    fields: [
      {
        key: "company",
        label: "快递公司",
        max: 30,
        placeholder: "例如：中通快递",
      },
      {
        key: "station",
        label: "取件点",
        max: 60,
        placeholder: "例如：菜鸟驿站",
      },
      {
        key: "code",
        label: "取件码",
        max: 50,
        placeholder: "请填写完整取件码",
      },
      { key: "size", label: "包裹规格", type: "select" },
      {
        key: "weight",
        label: "包裹重量（kg）",
        type: "number",
        min: 0.01,
        limit: 30,
        help: "请估算重量，最大支持 30 kg",
      },
    ],
  },
  {
    title: "送到哪里",
    description: "写清地址，少一次等待",
    icon: MapPin,
    fields: [
      {
        key: "address",
        label: "送达地址",
        max: 200,
        wide: true,
        placeholder: "例如：实验楼 A 座 302 室、图书馆正门、第一饭堂门口",
      },
      {
        key: "time",
        label: "期望送达时间",
        type: "datetime-local",
        help: "请选择未来七天内的时间",
      },
      {
        key: "tip",
        label: "小费金额（元）",
        type: "number",
        min: 0,
        limit: 999,
        help: "可填 0 元，按自己的心意选择",
      },
    ],
  },
];
async function loadContext() {
  context.value = await orderApi.context();
  recent.value = context.value.user ? (await orderApi.mine()).items : [];
}
async function loadOrder(id) {
  error.value = "";
  if (!id) {
    order.value = null;
    return;
  }
  busy.value = true;
  try {
    order.value = await orderApi.detail(id);
  } catch (cause) {
    order.value = null;
    error.value = cause.message;
  } finally {
    busy.value = false;
  }
}
function scheduleQuote() {
  clearTimeout(quoteTimer);
  const version = ++quoteVersion;
  fees.value = null;
  quoteError.value = "";
  quoting.value = false;
  if (!canPublish.value || order.value || Object.keys(errors.value).length)
    return;
  quoting.value = true;
  quoteTimer = setTimeout(async () => {
    try {
      const result = await orderApi.quote(payload());
      if (version === quoteVersion) fees.value = result;
    } catch (cause) {
      if (version === quoteVersion) quoteError.value = cause.message;
    } finally {
      if (version === quoteVersion) quoting.value = false;
    }
  }, 350);
}
async function submit() {
  if (busy.value || order.value) return;
  submitted.value = true;
  error.value = "";
  if (!canPublish.value || Object.keys(errors.value).length) {
    await nextTick();
    document.querySelector('[aria-invalid="true"]')?.focus();
    return;
  }
  busy.value = true;
  try {
    const body = payload(),
      snapshot = JSON.stringify(body);
    if (snapshot !== requestSnapshot) {
      requestKey = crypto.randomUUID();
      requestSnapshot = snapshot;
    }
    order.value = await orderApi.create(body, requestKey);
    await router.replace({
      path: "/publish",
      query: { orderId: order.value.orderId },
    });
    recent.value = (await orderApi.mine()).items;
  } catch (cause) {
    error.value = cause.message;
  } finally {
    busy.value = false;
  }
}
async function switchDemo(event) {
  busy.value = true;
  error.value = "";
  try {
    await orderApi.demoSession(event.target.value);
    await loadContext();
    order.value = null;
    await router.replace("/publish");
    scheduleQuote();
  } catch (cause) {
    error.value = cause.message;
  } finally {
    busy.value = false;
  }
}
async function beginPayment() {
  busy.value = true;
  error.value = "";
  try {
    const result = await orderApi.prepay(order.value.orderId);
    if (result.mode === "demo") {
      paymentError.value = "";
      paymentDialog.value.showModal();
    } else {
      // D 收银台契约落地后在此映射，状态仍只通过服务端支付事件更新。
      error.value = "支付请求已发送，请在支付端完成付款，再点击刷新状态。";
    }
  } catch (cause) {
    error.value = cause.message;
  } finally {
    busy.value = false;
  }
}
async function confirmDemoPayment() {
  busy.value = true;
  paymentError.value = "";
  try {
    order.value = await orderApi.demoPay(order.value.orderId);
    paymentDialog.value.close();
    recent.value = (await orderApi.mine()).items;
  } catch (cause) {
    paymentError.value = cause.message;
  } finally {
    busy.value = false;
  }
}
async function newOrder() {
  Object.assign(draft, freshDraft());
  submitted.value = false;
  fees.value = null;
  await router.replace("/publish");
}
watch(draft, scheduleQuote);
watch(
  () => route.query.orderId,
  (id) => loadOrder(typeof id === "string" ? id : null),
);
onMounted(async () => {
  try {
    await loadContext();
    if (route.query.orderId) await loadOrder(String(route.query.orderId));
  } catch (cause) {
    error.value = `${cause.message}，请确认服务已启动后刷新页面。`;
  } finally {
    loading.value = false;
  }
});
onBeforeUnmount(() => {
  clearTimeout(quoteTimer);
  quoteVersion++;
});
</script>

<template>
  <PageHeading
    title="把取件这件事，交给顺路的同学"
    subtitle="填写取件信息，确认费用后再支付。"
    eyebrow="NEW REQUEST"
  />
  <div v-if="loading" class="notice" role="status">正在读取发布信息…</div>
  <div v-if="context?.mode === 'demo'" class="demo-banner">
    <span
      ><strong>演示模式</strong>
      订单会保存；身份与支付为模拟，不产生真实扣款。</span
    >
    <label
      >体验身份<select :value="demoState" :disabled="busy" @change="switchDemo">
        <option value="verified">已认证同学</option>
        <option value="unverified">未认证同学</option>
        <option value="guest">未登录访客</option>
      </select></label
    >
  </div>
  <div v-if="error" class="error-banner" role="alert">
    {{ error }}
    <button v-if="!context" class="text-button" @click="router.go(0)">
      重新加载
    </button>
  </div>
  <div v-if="context && !canPublish" class="notice identity-notice">
    <ShieldCheck :size="22" />
    <div>
      <strong>{{
        context.user
          ? "完成学生认证后，即可发布需求"
          : "登录后，即可发布代取需求"
      }}</strong>
      <p>
        {{
          context.user
            ? "认证让每一份校园托付更安心。"
            : "登录后会回到当前发布页面。"
        }}
      </p>
    </div>
    <RouterLink
      class="primary-button"
      :to="context.user ? '/verification' : '/login?redirect=%2Fpublish'"
      >{{ context.user ? "去认证" : "去登录" }}</RouterLink
    >
  </div>
  <div class="publish-layout">
    <form
      v-if="!order"
      class="panel publish-form"
      novalidate
      @submit.prevent="submit"
    >
      <fieldset :disabled="busy || loading || !canPublish">
        <section
          v-for="(section, index) in sections"
          :key="section.title"
          class="form-section"
        >
          <div class="section-title">
            <span class="section-icon"
              ><component :is="section.icon" :size="20"
            /></span>
            <div>
              <h2>{{ section.title }}</h2>
              <p>{{ section.description }}</p>
            </div>
          </div>
          <div class="form-grid">
            <label
              v-for="field in section.fields"
              :key="field.key"
              :class="{ 'wide-field': field.wide }"
              >{{ field.label }}
              <span v-if="field.type !== 'select'" class="required">*</span>
              <select v-if="field.type === 'select'" v-model="draft[field.key]">
                <option>小件</option>
                <option>中件</option>
                <option>大件</option>
              </select>
              <input
                v-else
                v-model="draft[field.key]"
                :type="field.type || 'text'"
                :maxlength="field.max"
                :min="field.min"
                :max="field.limit"
                :step="field.type === 'number' ? '0.01' : undefined"
                :placeholder="field.placeholder"
                :aria-invalid="submitted && !!errors[field.key]"
                :aria-describedby="field.key + '-help'"
                autocomplete="off"
              />
              <small
                :id="field.key + '-help'"
                :class="
                  submitted && errors[field.key] ? 'field-error' : 'field-hint'
                "
                >{{
                  submitted && errors[field.key]
                    ? errors[field.key]
                    : field.help
                }}</small
              >
            </label>
            <label v-if="index === 1" class="wide-field"
              >备注<textarea
                v-model="draft.note"
                maxlength="200"
                rows="3"
                placeholder="例如：包裹易碎，请轻拿轻放"
              /><small class="field-hint"
                >{{ draft.note.length }} / 200</small
              ></label
            >
          </div>
        </section>
        <div class="submit-row">
          <span><ShieldCheck :size="16" />支付成功后，需求才会进入大厅</span
          ><button class="primary-button" type="submit">
            {{ busy ? "正在创建…" : "创建订单" }}
          </button>
        </div>
      </fieldset>
    </form>
    <section
      v-else
      class="panel order-result"
      aria-labelledby="order-result-title"
    >
      <div class="result-symbol">
        <Clock v-if="order.status === 'awaiting_payment'" :size="28" /><Check
          v-else
          :size="28"
        />
      </div>
      <span class="soft-tag">{{ statusText }}</span>
      <h2 id="order-result-title">
        {{ resultTitle }}
      </h2>
      <p class="result-description">
        {{
          order.status === "awaiting_payment"
            ? "取件信息已保存，稍后也可以回来继续支付。"
            : "订单已完成支付，当前状态为" + statusText + "。"
        }}
      </p>
      <dl class="order-details">
        <div>
          <dt>订单号</dt>
          <dd>{{ order.orderId }}</dd>
        </div>
        <div>
          <dt>快递公司</dt>
          <dd>{{ order.company }}</dd>
        </div>
        <div>
          <dt>取件信息</dt>
          <dd>{{ order.station }} / {{ order.code }}</dd>
        </div>
        <div>
          <dt>包裹规格</dt>
          <dd>{{ order.size }} / {{ order.weight }} kg</dd>
        </div>
        <div>
          <dt>送达地址</dt>
          <dd>{{ order.address }}</dd>
        </div>
        <div>
          <dt>期望送达</dt>
          <dd>
            {{
              new Date(order.expectedAt).toLocaleString("zh-CN", {
                hour12: false,
              })
            }}
          </dd>
        </div>
        <div v-if="order.note">
          <dt>备注</dt>
          <dd>{{ order.note }}</dd>
        </div>
      </dl>
      <div class="result-actions">
        <button
          v-if="order.status === 'awaiting_payment'"
          class="primary-button"
          :disabled="busy"
          @click="beginPayment"
        >
          {{
            busy ? "正在处理…" : "去支付 ¥" + money(order.amountCents)
          }}</button
        ><button
          class="outline-button"
          :disabled="busy"
          @click="loadOrder(order.orderId)"
        >
          刷新状态</button
        ><button class="text-button" :disabled="busy" @click="newOrder">
          再发一单
        </button>
      </div>
    </section>
    <aside class="publish-aside">
      <section class="panel fee-panel">
        <h2>费用明细</h2>
        <div class="fee-line">
          <span>基础运费</span
          ><strong>{{
            feeDisplay ? "¥" + money(feeDisplay.baseFeeCents) : "待计算"
          }}</strong>
        </div>
        <div class="fee-line">
          <span>给同学的小费</span
          ><strong>{{
            feeDisplay ? "¥" + money(feeDisplay.tipCents) : "—"
          }}</strong>
        </div>
        <div class="fee-total">
          <span>合计</span
          ><strong>{{
            feeDisplay ? "¥" + money(feeDisplay.amountCents) : "—"
          }}</strong>
        </div>
        <p class="fee-help" role="status">
          {{
            order
              ? "费用已随订单保存。"
              : quoting
                ? "正在计算费用…"
                : quoteError ||
                  (feeDisplay
                    ? "创建订单时会再次确认费用。"
                    : "填完必填信息后，自动计算费用。")
          }}
        </p>
        <p v-if="context?.mode === 'demo'" class="demo-pricing">
          演示运费：小 / 中 / 大件 2 / 3 / 5 元；超过 1 kg，每向上取整增加 1 kg
          加 1 元。
        </p>
      </section>
      <section class="publish-guide">
        <ShieldCheck :size="21" />
        <h3>把托付说清楚</h3>
        <p>请核对取件码与具体送达位置。不要在备注中填写密码或其他敏感信息。</p>
      </section>
      <section v-if="recent.length" class="recent-orders">
        <h3>最近发布</h3>
        <RouterLink
          v-for="item in recent.slice(0, 5)"
          :key="item.orderId"
          :to="{ path: '/publish', query: { orderId: item.orderId } }"
          ><span
            >{{ item.company }}<small>{{ item.address }}</small></span
          ><span
            >{{ statusLabels[item.status] || "状态更新中"
            }}<small>¥{{ money(item.amountCents) }}</small></span
          ></RouterLink
        >
      </section>
    </aside>
  </div>
  <dialog
    ref="paymentDialog"
    class="payment-dialog"
    aria-labelledby="payment-title"
    @cancel="busy && $event.preventDefault()"
  >
    <button
      class="icon-button close-payment"
      aria-label="关闭支付"
      :disabled="busy"
      @click="paymentDialog.close()"
    >
      <X :size="20" /></button
    ><span class="soft-tag">演示支付</span>
    <h2 id="payment-title">确认这份校园托付</h2>
    <p>本次仅模拟支付成功，不扣除真实余额。</p>
    <strong class="payment-amount"
      >¥{{ money(order?.amountCents || 0) }}</strong
    >
    <p v-if="paymentError" class="field-error" role="alert">
      {{ paymentError }}
    </p>
    <button class="primary-button" :disabled="busy" @click="confirmDemoPayment">
      {{ busy ? "正在确认…" : "确认演示支付" }}</button
    ><button
      class="text-button later-button"
      :disabled="busy"
      @click="paymentDialog.close()"
    >
      稍后支付
    </button>
  </dialog>
</template>

<style scoped>
.publish-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 290px;
  gap: 24px;
  align-items: start;
}
.demo-banner {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 18px;
  background: #edf4ef;
  border: 1px solid #dce8df;
  padding: 13px 18px;
  border-radius: 9px;
  margin-bottom: 22px;
  color: #506c5b;
  font-size: 12px;
  line-height: 1.8;
}
.demo-banner strong {
  margin-right: 10px;
  color: #234f41;
}
.demo-banner label {
  display: flex;
  align-items: center;
  gap: 10px;
  white-space: nowrap;
}
.demo-banner select {
  margin: 0;
  width: 140px;
  padding: 7px 10px;
}
.publish-form fieldset {
  border: 0;
  padding: 0;
  margin: 0;
  min-width: 0;
}
.publish-form fieldset:disabled {
  opacity: 0.65;
}
.form-section {
  padding: 28px;
}
.form-section + .form-section {
  border-top: 1px solid var(--border);
}
.section-title {
  display: flex;
  align-items: center;
  gap: 12px;
}
.section-title h2,
.fee-panel h2 {
  font-size: 17px;
}
.section-title p {
  font-size: 11px;
  color: #6d7f74;
  margin-top: 3px;
}
.section-icon {
  display: grid;
  place-items: center;
  width: 40px;
  height: 40px;
  background: #edf4ef;
  border-radius: 10px;
  color: #547961;
}
.publish-form .form-grid {
  gap: 22px 20px;
}
.required {
  color: #9b654c;
}
.wide-field {
  grid-column: 1 / -1;
}
.field-hint,
.field-error {
  display: block;
  font-size: 11px;
  font-weight: 400;
  line-height: 1.7;
  margin-top: 6px;
}
.field-hint {
  color: #6f7e74;
}
.field-error,
.error-banner {
  color: #a33d32;
}
[aria-invalid="true"] {
  border-color: #bd685b;
}
textarea {
  resize: vertical;
  min-height: 85px;
}
textarea:focus-visible {
  outline: 3px solid #89b9a5;
  outline-offset: 3px;
}
.submit-row {
  padding: 22px 28px;
  border-top: 1px solid var(--border);
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
}
.submit-row > span {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  color: #657e69;
}
.primary-button:disabled {
  opacity: 0.6;
}
.publish-aside {
  position: sticky;
  top: 24px;
  min-width: 0;
}
.fee-panel {
  padding: 24px;
}
.fee-panel h2 {
  margin-bottom: 24px;
}
.fee-line,
.fee-total {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
}
.fee-line {
  font-size: 12px;
  color: #68796e;
  margin-top: 17px;
}
.fee-line strong {
  font-weight: 500;
  color: #3a5145;
}
.fee-total {
  margin-top: 24px;
  padding-top: 20px;
  border-top: 1px dashed #dbe4dd;
  font-size: 13px;
}
.fee-total strong {
  font-size: 30px;
  color: #a77a47;
  font-weight: 600;
}
.fee-help,
.demo-pricing {
  font-size: 11px;
  color: #6d7e71;
  margin-top: 16px;
}
.demo-pricing {
  border-top: 1px solid var(--border);
  padding-top: 15px;
}
.publish-guide {
  padding: 24px 6px;
  color: #67815d;
}
.publish-guide h3 {
  display: inline;
  margin-left: 8px;
  font-size: 13px;
}
.publish-guide p {
  margin-top: 12px;
  font-size: 12px;
  color: #6c7c6b;
}
.recent-orders {
  padding: 18px 0;
  border-top: 1px solid var(--border);
}
.recent-orders h3 {
  font-size: 13px;
  margin-bottom: 10px;
}
.recent-orders a {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  padding: 13px 0;
  font-size: 12px;
  border-bottom: 1px solid var(--border);
}
.recent-orders a > span:last-child {
  text-align: right;
  white-space: nowrap;
}
.recent-orders small {
  display: block;
  color: #738273;
  margin-top: 5px;
  font-size: 11px;
}
.identity-notice {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
}
.identity-notice p {
  font-size: 11px;
}
.identity-notice .primary-button {
  margin-left: auto;
}
.error-banner {
  margin: 16px 0;
  padding: 14px 18px;
  background: #fff2ef;
  border: 1px solid #efd5cd;
  border-radius: 9px;
  font-size: 13px;
  line-height: 1.8;
}
.order-result {
  padding: 34px;
}
.result-symbol {
  width: 58px;
  height: 58px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  background: #edf4ef;
  color: #547961;
  margin-bottom: 18px;
}
.order-result h2 {
  font-size: 22px;
  margin-top: 16px;
}
.result-description {
  font-size: 12px;
  color: #697e70;
  margin-top: 10px;
}
.order-details {
  margin: 28px 0;
}
.order-details div {
  display: grid;
  grid-template-columns: 85px minmax(0, 1fr);
  padding: 14px 0;
  border-bottom: 1px solid var(--border);
  font-size: 12px;
  line-height: 1.8;
}
.order-details dt {
  color: #6d7e71;
}
.order-details dd {
  margin: 0;
  overflow-wrap: anywhere;
  white-space: pre-wrap;
}
.result-actions {
  display: flex;
  gap: 16px;
  align-items: center;
  flex-wrap: wrap;
}
.payment-dialog {
  border: 1px solid var(--border);
  border-radius: 16px;
  padding: 36px;
  width: min(430px, calc(100vw - 36px));
  color: #253c36;
}
.payment-dialog::backdrop {
  background: #12322480;
  backdrop-filter: blur(4px);
}
.close-payment {
  position: absolute;
  top: 12px;
  right: 12px;
}
.payment-dialog h2 {
  margin-top: 18px;
}
.payment-dialog p {
  font-size: 12px;
  color: #667b6b;
  margin-top: 12px;
}
.payment-amount {
  display: block;
  font-size: 38px;
  color: #a77a47;
  margin: 28px 0;
}
.payment-dialog > .primary-button {
  width: 100%;
}
.later-button {
  display: block;
  margin: 18px auto 0;
}
@media (max-width: 1100px) {
  .publish-layout {
    grid-template-columns: minmax(0, 1fr);
  }
  .publish-aside {
    position: static;
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 20px;
  }
  .recent-orders {
    grid-column: 1 / -1;
  }
}
@media (max-width: 640px) {
  .demo-banner {
    align-items: start;
    flex-direction: column;
    gap: 10px;
  }
  .form-section {
    padding: 22px;
  }
  .submit-row {
    padding: 20px 22px;
    align-items: stretch;
    flex-direction: column;
  }
  .publish-aside {
    display: block;
  }
  .order-result {
    padding: 24px;
  }
  .order-result h2 {
    font-size: 20px;
  }
}
</style>
