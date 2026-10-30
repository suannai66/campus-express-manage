<script setup>
import {
  computed,
  onMounted,
  onBeforeUnmount,
  reactive,
  ref,
  watch,
} from "vue";
import { useRoute, useRouter } from "vue-router";
import { Package, MapPin, ShieldCheck, Clock, X } from "@lucide/vue";
import PageHeading from "../../components/PageHeading.vue";
import { orderApi, sizeLabels, formatTime } from "./api";
const route = useRoute(),
  router = useRouter();
const freshDraft = () => ({
  company: "",
  code: "",
  stationId: "",
  deliveryAreaId: "",
  address: "",
  size: "small",
  weight: "1",
  time: "",
  tip: "0",
  note: "",
});
const draft = reactive(freshDraft());
const context = ref(null),
  locations = ref({ stations: [], deliveryAreas: [] });
const order = ref(null),
  recent = ref([]),
  fees = ref(null),
  loading = ref(true),
  busy = ref(false),
  error = ref(""),
  quoteError = ref(""),
  submitted = ref(false),
  fields = ref({}),
  paymentDialog = ref(null);
let quoteTimer,
  pollTimer,
  generation = 0,
  orderGeneration = 0,
  disposed = false,
  requestKey = "",
  snapshot = "",
  reserveKey = "",
  payKey = "";
const canPublish = computed(() => context.value?.verified === true);
const money = (value) => (Number(value) / 100).toFixed(2);
const localTime = (value) =>
  new Date(`${value}${value.length === 16 ? ":00" : ""}+08:00`);
const errors = computed(() => {
  const result = { ...fields.value };
  for (const [key, label] of Object.entries({
    company: "快递公司",
    code: "取件码",
    stationId: "取件点",
    deliveryAreaId: "送达区域",
    address: "送达地址",
  }))
    if (!draft[key].trim()) result[key] = `请填写${label}`;
  if (
    !/^\d+(\.\d{1,2})?$/.test(String(draft.weight)) ||
    Number(draft.weight) <= 0 ||
    Number(draft.weight) > 30
  )
    result.weight = "重量需大于 0 且不超过 30 kg，最多两位小数";
  if (!/^\d+(\.\d{1,2})?$/.test(String(draft.tip)) || Number(draft.tip) > 999)
    result.tip = "请输入 0 至 999 元，最多两位小数";
  const time = localTime(draft.time).getTime();
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
  stationId: draft.stationId,
  deliveryAreaId: draft.deliveryAreaId,
  address: draft.address.trim(),
  size: draft.size,
  weight: String(draft.weight),
  expectedAt: localTime(draft.time).toISOString(),
  tip: Math.round(Number(draft.tip) * 100),
  note: draft.note.trim(),
});
const statusLabels = {
  pending_payment: "待支付",
  pending: "待接单",
  accepted: "已接单",
  picking_up: "取件中",
  delivering: "配送中",
  delivered: "已送达",
  cancelled: "已取消",
};
const statusText = computed(() =>
  order.value?.paymentStatus === "paying"
    ? "支付处理中"
    : statusLabels[order.value?.status],
);
const feeDisplay = computed(() => order.value || fees.value);
const sections = computed(() => [
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
      { key: "stationId", label: "取件点", options: locations.value.stations },
      {
        key: "code",
        label: "取件码",
        max: 50,
        placeholder: "请填写完整取件码",
      },
      {
        key: "size",
        label: "包裹规格",
        options: Object.entries(sizeLabels).map(([id, name]) => ({ id, name })),
      },
      {
        key: "weight",
        label: "包裹重量（kg）",
        type: "number",
        min: 0.01,
        limit: 30,
      },
    ],
  },
  {
    title: "送到哪里",
    description: "选择区域，再写清宿舍楼与门牌",
    icon: MapPin,
    fields: [
      {
        key: "deliveryAreaId",
        label: "送达区域",
        options: locations.value.deliveryAreas,
      },
      {
        key: "address",
        label: "详细送达地址",
        max: 200,
        placeholder: "例如：沁园 3 栋 302 室",
      },
      {
        key: "time",
        label: "期望送达时间",
        type: "datetime-local",
        help: "新加坡时间（UTC+8），未来七天内",
      },
      {
        key: "tip",
        label: "小费金额（元）",
        type: "number",
        min: 0,
        limit: 999,
        help: "可填 0 元",
      },
    ],
  },
]);
function report(cause) {
  error.value = cause.message;
  fields.value = { ...(cause.fields || {}) };
  if (fields.value.expectedAt) {
    fields.value.time = fields.value.expectedAt;
    delete fields.value.expectedAt;
  }
  if (cause.code === "VERIFICATION_REQUIRED" && context.value)
    context.value.verified = false;
}
async function loadOrder(id) {
  generation++;
  clearTimeout(quoteTimer);
  const version = ++orderGeneration;
  if (id !== order.value?.orderId) {
    reserveKey = "";
    payKey = "";
  }
  order.value = null;
  if (!id) return;
  busy.value = true;
  try {
    const result = await orderApi.detail(id);
    if (!disposed && version === orderGeneration) order.value = result;
  } catch (cause) {
    if (!disposed && version === orderGeneration) report(cause);
  } finally {
    if (version === orderGeneration) busy.value = false;
  }
}
function scheduleQuote() {
  clearTimeout(quoteTimer);
  const version = ++generation;
  fees.value = null;
  quoteError.value = "";
  if (!canPublish.value || order.value || Object.keys(errors.value).length)
    return;
  quoteTimer = setTimeout(async () => {
    try {
      const result = await orderApi.quote(payload());
      if (version === generation && !disposed) fees.value = result;
    } catch (cause) {
      if (version === generation && !disposed) quoteError.value = cause.message;
    }
  }, 350);
}
async function submit() {
  if (busy.value) return;
  submitted.value = true;
  fields.value = {};
  error.value = "";
  if (!canPublish.value || Object.keys(errors.value).length) return;
  busy.value = true;
  generation++;
  clearTimeout(quoteTimer);
  try {
    const body = payload(),
      serialized = JSON.stringify(body);
    if (snapshot !== serialized) {
      snapshot = serialized;
      requestKey = crypto.randomUUID();
    }
    order.value = await orderApi.create(body, requestKey);
    await router.replace({
      path: "/publish",
      query: { orderId: order.value.orderId },
    });
    recent.value = (await orderApi.mine()).items;
  } catch (cause) {
    report(cause);
  } finally {
    busy.value = false;
  }
}
async function pay() {
  busy.value = true;
  error.value = "";
  try {
    reserveKey ||= crypto.randomUUID();
    const reservation =
      order.value.paymentStatus === "paying" && order.value.paymentRequestId
        ? { paymentRequestId: order.value.paymentRequestId }
        : await orderApi.reservePayment(
            order.value.orderId,
            order.value.version,
            reserveKey,
          );
    order.value = { ...order.value, ...reservation };
    payKey ||= crypto.randomUUID();
    const result = await orderApi.prepay(
      order.value.orderId,
      reservation.paymentRequestId,
      payKey,
    );
    paymentDialog.value.close();
    if (result.status === "failed")
      error.value =
        result.code === "INSUFFICIENT_BALANCE"
          ? "余额不足，请到钱包充值，等待支付失败状态同步后重试。"
          : "支付未完成，请刷新状态后重试。";
    else error.value = "支付结果正在同步，请等待订单状态更新。";
    await refreshOrder();
  } catch (cause) {
    report(cause);
    await refreshOrder();
  } finally {
    busy.value = false;
  }
}
async function refreshOrder() {
  if (!order.value || disposed) return;
  try {
    const id = order.value.orderId,
      latest = await orderApi.detail(id);
    if (disposed || order.value?.orderId !== id) return;
    if (
      latest.paymentStatus === "unpaid" &&
      order.value.paymentStatus === "paying"
    ) {
      reserveKey = "";
      payKey = "";
    }
    order.value = latest;
    if (latest.paymentStatus === "paid") error.value = "";
  } catch (cause) {
    if (!disposed) report(cause);
  }
}
async function newOrder() {
  order.value = null;
  reserveKey = "";
  payKey = "";
  requestKey = "";
  snapshot = "";
  Object.assign(draft, freshDraft());
  submitted.value = false;
  fields.value = {};
  error.value = "";
  await router.replace("/publish");
  scheduleQuote();
}
watch(draft, () => {
  fields.value = {};
  scheduleQuote();
});
watch(
  () => route.query.orderId,
  (id) => {
    if (id !== order.value?.orderId)
      loadOrder(typeof id === "string" ? id : null);
  },
);
onMounted(async () => {
  try {
    locations.value = await orderApi.locations();
    context.value = await orderApi.context();
    recent.value = (await orderApi.mine()).items;
    if (route.query.orderId) await loadOrder(String(route.query.orderId));
  } catch (cause) {
    report(cause);
  } finally {
    loading.value = false;
  }
  pollTimer = setInterval(() => {
    if (
      !document.hidden &&
      !busy.value &&
      order.value?.paymentStatus === "paying"
    )
      refreshOrder();
  }, 3000);
});
onBeforeUnmount(() => {
  disposed = true;
  generation++;
  clearTimeout(quoteTimer);
  clearInterval(pollTimer);
});
</script>
<template>
  <PageHeading
    title="把取件这件事，交给顺路的同学"
    subtitle="填写取件信息，确认费用后再支付。"
    eyebrow="NEW REQUEST"
  />
  <div v-if="loading" class="notice" role="status">正在读取发布信息…</div>
  <div v-if="error" class="error-banner" role="alert">
    {{ error }}
    <button v-if="!context" class="text-button" @click="router.go(0)">
      重新加载
    </button>
  </div>
  <div v-if="context && !canPublish" class="notice identity-notice">
    <ShieldCheck :size="22" />
    <div>
      <strong>完成学生认证后，即可发布需求</strong>
      <p>认证让每一份校园托付更安心。</p>
    </div>
    <RouterLink class="primary-button" to="/verification?redirect=%2Fpublish"
      >去认证</RouterLink
    >
  </div>
  <div class="publish-layout">
    <form
      v-if="!order"
      class="panel publish-form"
      novalidate
      @submit.prevent="submit"
    >
      <fieldset :disabled="loading || busy || !canPublish">
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
            <label v-for="field in section.fields" :key="field.key"
              >{{ field.label }} <span class="required">*</span>
              <select
                :aria-label="field.label"
                v-if="field.options"
                v-model="draft[field.key]"
                :aria-invalid="submitted && !!errors[field.key]"
                :aria-describedby="field.key + '-help'"
              >
                <option value="" disabled>请选择</option>
                <option
                  v-for="option in field.options"
                  :key="option.id"
                  :value="option.id"
                >
                  {{ option.name }}
                </option>
              </select>
              <input
                :aria-label="field.label"
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
                aria-label="备注"
                v-model="draft.note"
                maxlength="200"
                rows="3"
                placeholder="例如：包裹易碎，请轻拿轻放"
              /><small class="field-hint"
                >请勿填写手机号、取件码或门牌号。{{ draft.note.length }} /
                200</small
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
      <div class="result-symbol"><Clock :size="28" /></div>
      <span class="soft-tag">{{ statusText }}</span>
      <h2 id="order-result-title">
        {{
          order.status === "pending_payment"
            ? "订单已创建，支付后发布"
            : "需求状态已更新"
        }}
      </h2>
      <p class="result-description">
        {{
          order.paymentStatus === "paying"
            ? "支付正在处理，请勿重复付款。超时后可回来继续查询。"
            : order.status === "pending"
              ? "需求已发布，等待同学接单。"
              : "取件信息与费用已保存。"
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
          <dd>{{ order.stationName }} / {{ order.code }}</dd>
        </div>
        <div>
          <dt>包裹规格</dt>
          <dd>{{ sizeLabels[order.size] }} / {{ order.weight }} kg</dd>
        </div>
        <div>
          <dt>送达地址</dt>
          <dd>{{ order.deliveryAreaName }} / {{ order.address }}</dd>
        </div>
        <div>
          <dt>期望送达</dt>
          <dd>{{ formatTime(order.expectedAt) }}</dd>
        </div>
        <div v-if="order.note">
          <dt>备注</dt>
          <dd>{{ order.note }}</dd>
        </div>
      </dl>
      <div class="result-actions">
        <button
          v-if="order.status === 'pending_payment'"
          class="primary-button"
          :disabled="busy"
          @click="paymentDialog.showModal()"
        >
          {{
            order.paymentStatus === "paying"
              ? "查询并继续支付"
              : "去支付 ¥" + money(order.amount)
          }}</button
        ><button class="outline-button" :disabled="busy" @click="refreshOrder">
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
            feeDisplay ? "¥" + money(feeDisplay.baseFee) : "待计算"
          }}</strong>
        </div>
        <div class="fee-line">
          <span>给同学的小费</span
          ><strong>{{ feeDisplay ? "¥" + money(feeDisplay.tip) : "—" }}</strong>
        </div>
        <div class="fee-total">
          <span>合计</span
          ><strong>{{
            feeDisplay ? "¥" + money(feeDisplay.amount) : "—"
          }}</strong>
        </div>
        <p class="fee-help" role="status">
          {{
            order
              ? "费用已随订单保存。"
              : quoteError ||
                (fees
                  ? "创建订单时会重新报价并确认费用。"
                  : "填完必填信息后，自动计算费用。")
          }}
        </p>
        <p v-if="feeDisplay?.demo" class="demo-pricing">
          演示计费与模拟资金，不产生真实扣款。
        </p>
      </section>
      <section class="publish-guide">
        <ShieldCheck :size="21" />
        <h3>把托付说清楚</h3>
        <p>
          取件码与详细地址仅向你和接单后的同学提供。请在备注中避免填写敏感信息。
        </p>
      </section>
      <section v-if="recent.length" class="recent-orders">
        <h3>最近发布</h3>
        <RouterLink
          v-for="item in recent.slice(0, 5)"
          :key="item.orderId"
          :to="{ path: '/publish', query: { orderId: item.orderId } }"
          ><span
            >{{ item.company }}<small>{{ item.deliveryAreaName }}</small></span
          ><span
            >{{ statusLabels[item.status]
            }}<small>¥{{ money(item.amount) }}</small></span
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
    ><span class="soft-tag">{{ order?.demo ? "模拟资金" : "订单支付" }}</span>
    <h2 id="payment-title">确认这份校园托付</h2>
    <p>使用钱包余额支付，付款结果以订单状态为准。</p>
    <strong class="payment-amount">¥{{ money(order?.amount || 0) }}</strong>
    <p v-if="error" role="alert">{{ error }}</p>
    <button class="primary-button" :disabled="busy" @click="pay">
      {{ busy ? "正在处理…" : "确认支付" }}</button
    ><RouterLink class="text-button later-button" to="/wallet"
      >前往钱包</RouterLink
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
