<script setup>
import { onMounted, ref } from "vue";
import { X } from "@lucide/vue";
import PageHeading from "../../components/PageHeading.vue";
import MockCashier from "./MockCashier.vue";
import EmptyState from "../../components/EmptyState.vue";
import { request } from "../../services/http";

// 身份凭证由公共 http.js 统一附加（sessionStorage accessToken → Authorization: Bearer），
// 页面不携带任何 uid（约定：禁止客户端自报身份）。
const balance = ref(null); // 可用余额（分）
const transactions = ref(null); // 流水分页结果
const message = ref("");
const error = ref("");
const rechargeOpen = ref(false);
const rechargeAmount = ref("");
const rechargeKey = ref(""); // Idempotency-Key：同一弹窗内重复提交返回同一充值单
const cashierOrder = ref(null); // 待确认充值单（模拟收银台）
const withdrawOpen = ref(false);
const withdrawAmount = ref("");
const withdrawKey = ref("");
const rechargePending = ref(false);
const confirmPending = ref(false);
const withdrawPending = ref(false);
const withdrawCashier = ref(null);

const TYPE_LABELS = {
  recharge: "充值入账",
  withdrawal: "提现/回补",
  payment: "订单支付",
  refund: "订单退款",
  settlement: "履约结算",
};
const yuan = (cents) => (cents / 100).toFixed(2);

function openRecharge() {
  rechargeKey.value = crypto.randomUUID();
  rechargeAmount.value = "";
  message.value = "";
  error.value = "";
  rechargeOpen.value = true;
}

function openWithdraw() {
  withdrawKey.value = crypto.randomUUID();
  withdrawAmount.value = "";
  message.value = "";
  error.value = "";
  withdrawOpen.value = true;
}

async function loadBalance() {
  try {
    const data = await request("/wallet");
    balance.value = data.balance;
  } catch (err) {
    error.value = err.message;
    balance.value = null;
  }
}

async function loadTransactions() {
  try {
    transactions.value = await request(
      "/wallet/transactions?page=1&pageSize=20",
    );
  } catch (err) {
    error.value = err.message;
  }
}

function refreshAll() {
  loadBalance();
  loadTransactions();
}

onMounted(refreshAll);

async function submitRecharge() {
  if (rechargePending.value) return;
  const cents = Math.round(Number(rechargeAmount.value) * 100);
  if (!cents || cents <= 0) {
    message.value = "请输入大于 0 的金额";
    return;
  }
  error.value = "";
  rechargePending.value = true;
  try {
    const order = await request("/wallet/recharge", {
      method: "POST",
      headers: { "Idempotency-Key": rechargeKey.value },
      body: JSON.stringify({ amount: cents }),
    });
    cashierOrder.value = order;
  } catch (err) {
    error.value = err.message;
  } finally {
    rechargePending.value = false;
  }
}

async function confirmPaid() {
  if (confirmPending.value || !cashierOrder.value) return;
  // 模拟收银台"我已支付"：调用演示确认接口（真实渠道回调本期不实现，约定 v1.1）
  error.value = "";
  confirmPending.value = true;
  try {
    await request(`/wallet/recharge/${cashierOrder.value.rechargeId}/confirm`, {
      method: "POST",
      headers: {
        "Idempotency-Key": `confirm-${cashierOrder.value.rechargeId}`,
      },
    });
    const amount = yuan(cashierOrder.value.amount);
    cashierOrder.value = null;
    rechargeOpen.value = false;
    message.value = `充值成功 +¥${amount}`;
    refreshAll();
  } catch (err) {
    error.value = err.message;
  } finally {
    confirmPending.value = false;
  }
}

function prepareWithdraw() {
  const cents = Math.round(Number(withdrawAmount.value) * 100);
  if (!Number.isSafeInteger(cents) || cents < 1 || cents > 100000) {
    error.value = "提现金额须为 0.01 至 1000 元。";
    return;
  }
  error.value = "";
  withdrawCashier.value = { amount: cents, reference: withdrawKey.value };
}

async function submitWithdraw() {
  if (withdrawPending.value || !withdrawCashier.value) return;
  const cents = withdrawCashier.value.amount;
  if (!cents || cents <= 0) {
    message.value = "请输入大于 0 的金额";
    return;
  }
  error.value = "";
  withdrawPending.value = true;
  try {
    const order = await request("/wallet/withdraw", {
      method: "POST",
      headers: { "Idempotency-Key": withdrawKey.value },
      body: JSON.stringify({ amount: cents }),
    });
    withdrawOpen.value = false;
    withdrawCashier.value = null;
    message.value = "提现申请已提交，模拟银行处理中…";
    refreshAll();
    pollWithdrawal(order.withdrawId, cents);
  } catch (err) {
    error.value = err.message;
  } finally {
    withdrawPending.value = false;
  }
}

async function pollWithdrawal(withdrawId, cents) {
  // 后台任务最早 3 秒标记 succeeded（约定 v1.1），轮询状态直到到账
  for (let i = 0; i < 12; i += 1) {
    await new Promise((resolve) => setTimeout(resolve, 1000));
    try {
      const order = await request(`/wallet/withdrawals/${withdrawId}`);
      if (order.status === "failed") {
        message.value = "提现失败，金额已退回可用余额。";
        refreshAll();
        return;
      }
      if (order.status === "succeeded") {
        message.value = `提现成功 ¥${yuan(cents)}（模拟渠道已到账）`;
        refreshAll();
        return;
      }
    } catch (err) {
      error.value = err.message;
      return;
    }
  }
  message.value = "提现仍在处理中，请稍后在流水或提现记录中查看。";
  refreshAll();
}
</script>
<template>
  <PageHeading
    title="每一份感谢，都有记录"
    subtitle="查看账户余额、代取收益与收支流水。"
    eyebrow="MY WALLET"
  />
  <section class="wallet-banner">
    <p>可用余额（元）</p>
    <strong>{{ balance === null ? "¥ —" : `¥ ${yuan(balance)}` }}</strong
    ><span>开发演示使用模拟资金，不产生真实交易</span>
    <div class="hero-actions">
      <button class="light-button" @click="openRecharge">模拟充值</button
      ><button class="hero-link" @click="openWithdraw">模拟提现 ↗</button>
    </div>
  </section>
  <p v-if="message" role="status" class="notice">{{ message }}</p>
  <p
    v-if="error && !cashierOrder && !withdrawCashier"
    role="alert"
    class="notice"
  >
    {{ error }}
  </p>
  <div class="section-heading">
    <h2>收支流水</h2>
    <span class="soft-tag">模拟钱包</span>
  </div>
  <EmptyState
    v-if="transactions && !transactions.items.length"
    class="panel"
    title="还没有收支记录"
    description="完成一笔模拟充值或提现后，流水会出现在这里。"
  />
  <ul v-else-if="transactions" class="ledger-list panel">
    <li v-for="item in transactions.items" :key="item.transactionId">
      <span class="ledger-type">{{ TYPE_LABELS[item.type] || item.type }}</span>
      <span class="ledger-time">{{
        new Date(item.createdAt).toLocaleString("zh-CN", {
          timeZone: "Asia/Singapore",
        })
      }}</span>
      <strong :class="item.direction === 'in' ? 'ledger-in' : 'ledger-out'"
        >{{ item.direction === "in" ? "+" : "-"
        }}{{ yuan(item.amount) }}</strong
      ><small>余额 {{ yuan(item.balanceAfter) }}</small>
    </li>
  </ul>

  <!-- 充值弹窗 -->
  <div
    v-if="rechargeOpen && !cashierOrder"
    class="dialog-backdrop"
    @click.self="rechargeOpen = false"
  >
    <section
      class="dialog"
      role="dialog"
      aria-modal="true"
      aria-labelledby="recharge-title"
    >
      <button
        class="dialog-close icon-button"
        aria-label="关闭"
        @click="rechargeOpen = false"
      >
        <X :size="20" />
      </button>
      <p class="eyebrow">MOCK RECHARGE</p>
      <h2 id="recharge-title">模拟充值</h2>
      <p>演示环境使用模拟资金，不产生真实交易。</p>
      <label
        >充值金额（元）<input
          v-model="rechargeAmount"
          type="number"
          min="0.01"
          step="0.01"
          placeholder="0.00" /></label
      ><button
        class="primary-button full-width"
        :disabled="rechargePending"
        @click="submitRecharge"
      >
        去支付
      </button>
    </section>
  </div>

  <MockCashier
    v-if="cashierOrder"
    operation="recharge"
    :reference="cashierOrder.rechargeId"
    :amount="cashierOrder.amount"
    :pending="confirmPending"
    :error="error"
    @confirm="confirmPaid"
    @close="
      cashierOrder = null;
      error = '';
    "
  />
  <MockCashier
    v-if="withdrawCashier"
    operation="withdrawal"
    :reference="withdrawCashier.reference"
    :amount="withdrawCashier.amount"
    :pending="withdrawPending"
    :error="error"
    @confirm="submitWithdraw"
    @close="
      withdrawCashier = null;
      error = '';
    "
  />

  <!-- 提现弹窗 -->
  <div
    v-if="withdrawOpen && !withdrawCashier"
    class="dialog-backdrop"
    @click.self="withdrawOpen = false"
  >
    <section
      class="dialog"
      role="dialog"
      aria-modal="true"
      aria-labelledby="withdraw-title"
    >
      <button
        class="dialog-close icon-button"
        aria-label="关闭"
        @click="withdrawOpen = false"
      >
        <X :size="20" />
      </button>
      <p class="eyebrow">MOCK WITHDRAW</p>
      <h2 id="withdraw-title">模拟提现</h2>
      <p>金额不能超过可用余额；模拟渠道将在数秒内到账。</p>
      <label
        >提现金额（元）<input
          v-model="withdrawAmount"
          type="number"
          min="0.01"
          step="0.01"
          placeholder="0.00" /></label
      ><button
        class="primary-button full-width"
        :disabled="withdrawPending"
        @click="prepareWithdraw"
      >
        确认提现
      </button>
    </section>
  </div>
</template>
<style scoped>
.ledger-list {
  list-style: none;
  margin: 0;
  padding: 0;
}
.ledger-list li {
  display: flex;
  align-items: baseline;
  gap: 14px;
  padding: 14px 18px;
  border-bottom: 1px solid var(--border);
}
.ledger-list li:last-child {
  border-bottom: 0;
}
.ledger-type {
  font-weight: 600;
}
.ledger-time {
  color: var(--muted);
  font-size: 13px;
  flex: 1;
}
.ledger-in {
  color: var(--green);
}
.ledger-out {
  color: #b3544e;
}
.ledger-list small {
  color: var(--muted);
  min-width: 110px;
  text-align: right;
}
</style>
