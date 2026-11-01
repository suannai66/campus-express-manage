<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { accessToken } from "../../services/auth-state";
import EmptyState from "../../components/EmptyState.vue";
import OrderReviews from "./OrderReviews.vue";
import {
  fulfillmentApi as api,
  statusLabels,
  money,
  formatTime,
  sizeLabels,
} from "./api";
const props = defineProps({ reviewOnly: Boolean });
const emit = defineEmits(["reviewed"]);
const user = ref(null),
  items = ref([]),
  total = ref(0),
  page = ref(1),
  role = ref("all");
const status = ref(props.reviewOnly ? "delivered" : ""),
  loading = ref(false),
  listError = ref("");
const selected = ref(null),
  detail = ref(null),
  detailError = ref(""),
  notifications = ref([]);
const code = ref(""),
  reason = ref(""),
  busy = ref(false),
  message = ref(""),
  revision = ref(0);
const loggedIn = !!accessToken(),
  pageSize = 10;
const steps = [
  "pending_payment",
  "pending",
  "accepted",
  "picking_up",
  "delivering",
  "delivered",
];
const next = computed(
  () =>
    ({
      accepted: ["start_pickup", "开始取件"],
      picking_up: ["confirm_pickup", "核验取件码"],
      delivering: ["confirm_delivery", "确认送达"],
    })[detail.value?.status],
);
const canCancel = computed(
  () =>
    detail.value?.publisherUid === user.value?.uid &&
    ["pending_payment", "pending"].includes(detail.value?.status) &&
    detail.value?.paymentStatus !== "paying" &&
    !detail.value?.locked,
);
let alive = true,
  listGeneration = 0,
  detailGeneration = 0,
  polling = false,
  timer;
const keys = new Map();
async function loadList(quiet = false) {
  const current = ++listGeneration;
  if (!quiet) {
    loading.value = true;
    listError.value = "";
  }
  try {
    const result = await api.mine({
      role: role.value,
      ...(status.value ? { status: status.value } : {}),
      page: page.value,
      pageSize,
    });
    if (!alive || current !== listGeneration) return;
    items.value = result.items;
    total.value = result.total;
    listError.value = "";
  } catch (e) {
    if (alive && current === listGeneration) listError.value = e.message;
  } finally {
    if (alive && current === listGeneration) loading.value = false;
  }
}
async function loadDetail(id = selected.value) {
  if (!id) return;
  const current = ++detailGeneration;
  try {
    const [order, notices] = await Promise.all([
      api.detail(id),
      api.notifications(id),
    ]);
    if (!alive || current !== detailGeneration || id !== selected.value) return;
    detail.value = order;
    notifications.value = notices.items;
    detailError.value = "";
    revision.value++;
  } catch (e) {
    if (alive && current === detailGeneration)
      detailError.value = `无法更新订单：${e.message}。请刷新后操作。`;
  }
}
function open(id) {
  selected.value = id;
  detail.value = null;
  code.value = "";
  reason.value = "";
  message.value = "";
  detailError.value = "";
  loadDetail(id);
}
async function act(operation) {
  if (!detail.value || busy.value || detailError.value) return;
  const id = detail.value.orderId;
  const body =
    operation === "cancel"
      ? { version: detail.value.version, reason: reason.value.trim() }
      : {
          version: detail.value.version,
          action: next.value[0],
          ...(next.value[0] === "confirm_pickup"
            ? { code: code.value.trim() }
            : {}),
        };
  const signature = JSON.stringify([id, operation, body]);
  if (!keys.has(signature)) keys.set(signature, crypto.randomUUID());
  busy.value = true;
  message.value = "";
  try {
    await (operation === "cancel" ? api.cancel : api.advance)(
      id,
      body,
      keys.get(signature),
    );
    message.value =
      operation === "cancel"
        ? "订单已取消。已支付订单的退款结果将在此更新。"
        : "履约进度已更新。";
    code.value = "";
  } catch (e) {
    message.value = e.status
      ? e.message
      : "连接中断，操作结果待确认。刷新后可重试。";
  } finally {
    await Promise.all([loadDetail(id), loadList(true)]);
    busy.value = false;
  }
}
async function refresh() {
  if (polling || busy.value || !loggedIn) return;
  polling = true;
  try {
    if (!user.value) {
      const current = await api.current();
      if (!alive) return;
      user.value = current;
    }
    await Promise.all([loadList(true), loadDetail()]);
  } catch (e) {
    if (alive) listError.value = e.message;
  } finally {
    polling = false;
  }
}
watch([role, status], () => {
  page.value = 1;
  loadList();
});
watch(page, () => loadList());
onMounted(() => {
  if (!loggedIn) return;
  loading.value = true;
  refresh().finally(() => {
    if (alive) loading.value = false;
  });
  timer = window.setInterval(() => {
    if (!document.hidden) refresh();
  }, 10000);
});
onBeforeUnmount(() => {
  alive = false;
  listGeneration++;
  detailGeneration++;
  clearInterval(timer);
});
</script>
<template>
  <EmptyState
    v-if="!loggedIn"
    class="panel"
    title="登录后查看我的订单"
    description="跟进履约进度，送达后互相评价。"
    ><RouterLink class="primary-button" to="/login?redirect=/orders"
      >去登录</RouterLink
    ></EmptyState
  >
  <section v-else class="fulfillment-workspace">
    <div class="panel filters">
      <label
        >我的身份<select v-model="role">
          <option value="all">全部参与订单</option>
          <option value="publisher">我发布的</option>
          <option value="courier">我接取的</option>
        </select></label
      >
      <label v-if="!reviewOnly"
        >订单状态<select v-model="status">
          <option value="">全部状态</option>
          <option
            v-for="(label, value) in statusLabels"
            :key="value"
            :value="value"
          >
            {{ label }}
          </option>
        </select></label
      >
      <button
        type="button"
        class="secondary-button"
        :disabled="loading || busy"
        @click="refresh"
      >
        刷新订单
      </button>
    </div>
    <p v-if="listError" class="error" role="alert">{{ listError }}</p>
    <p v-if="loading" role="status">正在加载订单…</p>
    <EmptyState
      v-else-if="!listError && !items.length"
      class="panel"
      title="暂无符合条件的订单"
      description="去大厅接取任务，或发布一份代取需求。"
      ><RouterLink class="primary-button" to="/tasks"
        >前往大厅</RouterLink
      ></EmptyState
    >
    <div v-else class="order-grid">
      <article
        v-for="item in items"
        :key="item.orderId"
        class="panel order-card"
        :class="{ chosen: item.orderId === selected }"
      >
        <div class="card-top">
          <strong>{{ item.company }} · {{ sizeLabels[item.size] }}</strong
          ><span class="badge">{{ statusLabels[item.status] }}</span>
        </div>
        <p>{{ item.stationName }} → {{ item.deliveryAreaName }}</p>
        <small>期望送达 {{ formatTime(item.expectedAt) }}</small>
        <div class="card-bottom">
          <strong>{{ money(item.amount) }}</strong
          ><button
            type="button"
            class="secondary-button"
            :disabled="busy"
            @click="open(item.orderId)"
          >
            {{ reviewOnly ? "查看与评价" : "查看订单" }}
          </button>
        </div>
      </article>
    </div>
    <nav v-if="total > pageSize" class="pagination" aria-label="订单分页">
      <button :disabled="page === 1 || loading" @click="page--">上一页</button
      ><span
        >第 {{ page }} / {{ Math.ceil(total / pageSize) }} 页 ·
        {{ total }} 单</span
      ><button :disabled="page * pageSize >= total || loading" @click="page++">
        下一页
      </button>
    </nav>
    <section v-if="selected" class="panel detail" aria-label="订单详情">
      <h2>订单详情</h2>
      <p class="order-id">{{ selected }}</p>
      <p v-if="detailError" class="error" role="alert">{{ detailError }}</p>
      <p v-if="!detail && !detailError" role="status">正在加载详情…</p>
      <template v-if="detail">
        <ol
          v-if="detail.status !== 'cancelled'"
          class="progress"
          aria-label="履约进度"
        >
          <li
            v-for="(step, index) in steps"
            :key="step"
            :class="{ reached: index <= steps.indexOf(detail.status) }"
            :aria-current="step === detail.status ? 'step' : undefined"
          >
            {{ statusLabels[step] }}
          </li>
        </ol>
        <p v-else class="badge">订单已取消</p>
        <dl>
          <dt>取件位置</dt>
          <dd>{{ detail.stationName }}</dd>
          <dt>送达地址</dt>
          <dd>{{ detail.address }}</dd>
          <dt>取件码</dt>
          <dd>{{ detail.code }}</dd>
          <dt>备注</dt>
          <dd>{{ detail.note || "无" }}</dd>
          <dt>订单金额</dt>
          <dd>
            {{ money(detail.amount) }}（基础费 {{ money(detail.baseFee) }}，打赏
            {{ money(detail.tip) }}）
          </dd>
          <dt>支付 / 退款</dt>
          <dd>
            {{
              { unpaid: "未支付", paying: "支付处理中", paid: "已支付" }[
                detail.paymentStatus
              ]
            }}
            /
            {{
              {
                none: "无需退款",
                processing: "退款处理中",
                succeeded: "已退款",
              }[detail.refundStatus]
            }}
          </dd>
        </dl>
        <p v-if="detail.locked" role="alert" class="error">
          取件码连续错误三次，订单已锁定。请联系维护者处理。
        </p>
        <p v-else-if="detail.pickupFailureCount" role="status">
          取件码已连续错误
          {{ detail.pickupFailureCount }} 次，累计三次将锁定订单。
        </p>
        <ul v-if="notifications.length" class="notices" aria-label="订单通知">
          <li v-for="notice in notifications" :key="notice.notificationId">
            {{ notice.message }}
            <small>{{ formatTime(notice.createdAt) }}</small>
          </li>
        </ul>
        <p v-if="message" role="status">{{ message }}</p>
        <form
          v-if="
            next &&
            detail.courierUid === user?.uid &&
            !detail.locked &&
            !reviewOnly
          "
          class="action-form"
          @submit.prevent="act('advance')"
        >
          <label v-if="detail.status === 'picking_up'"
            >输入取件码<input
              v-model="code"
              required
              maxlength="50"
              autocomplete="off"
              :disabled="busy"
          /></label>
          <button class="primary-button" :disabled="busy || !!detailError">
            {{ busy ? "处理中…" : next[1] }}
          </button>
        </form>
        <RouterLink
          v-if="
            detail.status === 'pending_payment' &&
            detail.publisherUid === user?.uid
          "
          class="secondary-button"
          :to="{ path: '/publish', query: { orderId: detail.orderId } }"
          >{{
            detail.paymentStatus === "paying" ? "查看支付进度" : "继续支付"
          }}</RouterLink
        >
        <form
          v-if="canCancel && !reviewOnly"
          class="action-form cancel-form"
          @submit.prevent="act('cancel')"
        >
          <label
            >取消原因<input
              v-model="reason"
              required
              maxlength="200"
              placeholder="请填写取消原因"
              :disabled="busy" /></label
          ><button class="secondary-button" :disabled="busy || !!detailError">
            取消订单
          </button>
        </form>
        <OrderReviews
          v-if="detail.status === 'delivered'"
          :key="detail.orderId"
          :order-id="detail.orderId"
          :uid="user?.uid"
          :revision="revision"
          @submitted="emit('reviewed')"
        />
      </template>
    </section>
  </section>
</template>
<style scoped>
.fulfillment-workspace {
  display: grid;
  gap: 20px;
  min-width: 0;
  font-size: 13px;
}
.panel {
  padding: 24px;
}
.filters {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  align-items: end;
}
label {
  display: grid;
  gap: 7px;
}
.secondary-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: #f1f6f2;
  border: 1px solid #ceddce;
  color: #345a41;
  padding: 11px 16px;
  border-radius: 8px;
  font-size: 12px;
  line-height: 1.5;
}
select,
input {
  font: inherit;
  padding: 11px;
  border: 1px solid #cad7ce;
  border-radius: 9px;
  min-width: 0;
  max-width: 100%;
}
.order-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 18px;
}
.order-card {
  display: grid;
  gap: 10px;
  border: 1px solid var(--border);
}
.chosen {
  border-color: #60966b;
}
.card-top,
.card-bottom {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.card-bottom {
  margin-top: 12px;
}
.badge {
  background: #edf4e9;
  color: #36623c;
  padding: 5px 10px;
  border-radius: 20px;
  font-size: 13px;
}
.pagination {
  display: flex;
  justify-content: center;
  gap: 16px;
  align-items: center;
  flex-wrap: wrap;
}
.pagination button {
  padding: 9px;
  border-radius: 7px;
  border: 1px solid #ced9ce;
  background: white;
}
.order-id {
  color: #69736a;
  overflow-wrap: anywhere;
  font-size: 13px;
}
.progress {
  display: flex;
  padding: 0;
  list-style: none;
  gap: 8px;
  flex-wrap: wrap;
  margin: 24px 0;
}
.progress li {
  color: #6d786e;
  background: #f1f3f0;
  padding: 8px 12px;
  border-radius: 8px;
}
.progress .reached {
  color: #2e5d37;
  background: #e4efd9;
}
dl {
  display: grid;
  grid-template-columns: 100px minmax(0, 1fr);
  gap: 14px;
}
dt {
  color: #6d786e;
}
dd {
  margin: 0;
  overflow-wrap: anywhere;
}
.action-form {
  display: flex;
  align-items: end;
  flex-wrap: wrap;
  gap: 12px;
  margin: 24px 0;
}
.cancel-form {
  border-top: 1px solid #e3e8e4;
  padding-top: 20px;
}
.action-form label {
  flex: 1;
  max-width: 420px;
}
.error {
  color: #a3342b;
}
.notices {
  background: #fff4df;
  border-radius: 10px;
  padding: 16px 30px;
}
small {
  color: #66766a;
}
button:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}
@media (max-width: 650px) {
  .order-grid {
    grid-template-columns: 1fr;
  }
  .filters {
    align-items: stretch;
  }
  .filters label {
    flex: 1 1 100%;
  }
  dl {
    grid-template-columns: 78px minmax(0, 1fr);
  }
  .detail {
    padding: 20px;
  }
  .action-form {
    align-items: stretch;
    flex-direction: column;
  }
}
</style>
