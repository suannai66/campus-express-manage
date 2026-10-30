<script setup>
import { onMounted, ref } from "vue";
import { X } from "@lucide/vue";
import PageHeading from "../../components/PageHeading.vue";
import EmptyState from "../../components/EmptyState.vue";
import { request } from "../../services/http";

// TODO(F1 接入后) 开发期占位身份：登录后由统一会话/JWT 提供，此处仅本地演示用。
// 身份头只在钱包页自己的请求里携带，不修改公共 http.js。
const uid = "u1";

const balance = ref(null); // 可用余额（分）
const ledger = ref(null); // 流水分页结果
const message = ref("");
const error = ref("");
const rechargeOpen = ref(false);
const rechargeAmount = ref("");
const cashierOrder = ref(null); // 待支付充值单（模拟收银台）
const withdrawOpen = ref(false);
const withdrawAmount = ref("");

const BIZ_LABELS = { RECHARGE: "充值入账", WITHDRAW: "提现扣款" };
const yuan = (cents) => (cents / 100).toFixed(2);
const authHeaders = () => ({ "X-User-Id": uid });

async function loadBalance() {
  try {
    const data = await request("/wallet/balance", { headers: authHeaders() });
    balance.value = data.available_cent;
  } catch (err) {
    error.value = err.message;
    balance.value = null;
  }
}

async function loadLedger() {
  try {
    ledger.value = await request("/wallet/ledger?page=1&page_size=20", {
      headers: authHeaders(),
    });
  } catch (err) {
    error.value = err.message;
  }
}

function refreshAll() {
  loadBalance();
  loadLedger();
}

onMounted(refreshAll);

async function submitRecharge() {
  const cents = Math.round(Number(rechargeAmount.value) * 100);
  if (!cents || cents <= 0) {
    message.value = "请输入大于 0 的金额";
    return;
  }
  error.value = "";
  try {
    const order = await request("/wallet/recharge", {
      method: "POST",
      headers: authHeaders(),
      body: JSON.stringify({ amount_cent: cents }),
    });
    cashierOrder.value = order;
  } catch (err) {
    error.value = err.message;
  }
}

async function confirmPaid() {
  // 模拟收银台"我已支付"：触发渠道回调（真实渠道由服务端适配器验签，前端只提交订单号）
  error.value = "";
  try {
    await request("/wallet/recharge/callback", {
      method: "POST",
      body: JSON.stringify({ out_trade_no: cashierOrder.value.out_trade_no }),
    });
    const amount = yuan(cashierOrder.value.amount_cent);
    cashierOrder.value = null;
    rechargeOpen.value = false;
    rechargeAmount.value = "";
    message.value = `充值成功 +¥${amount}`;
    refreshAll();
  } catch (err) {
    error.value = err.message;
  }
}

async function submitWithdraw() {
  const cents = Math.round(Number(withdrawAmount.value) * 100);
  if (!cents || cents <= 0) {
    message.value = "请输入大于 0 的金额";
    return;
  }
  error.value = "";
  try {
    const order = await request("/wallet/withdraw", {
      method: "POST",
      headers: authHeaders(),
      body: JSON.stringify({ amount_cent: cents }),
    });
    withdrawOpen.value = false;
    withdrawAmount.value = "";
    message.value = "提现申请已提交，模拟银行处理中…";
    // 模拟渠道延迟到账：稍后查询提现单触发服务端惰性流转，再刷新余额与流水
    setTimeout(async () => {
      try {
        await request(`/wallet/withdraw/${order.withdraw_no}`, {
          headers: authHeaders(),
        });
        message.value = `提现成功 ¥${yuan(cents)}（模拟渠道已到账）`;
        refreshAll();
      } catch (err) {
        error.value = err.message;
      }
    }, 2500);
  } catch (err) {
    error.value = err.message;
  }
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
      <button class="light-button" @click="rechargeOpen = true">
        模拟充值</button
      ><button class="hero-link" @click="withdrawOpen = true">模拟提现 ↗</button>
    </div>
  </section>
  <p v-if="message" role="status" class="notice">{{ message }}</p>
  <p v-if="error" role="alert" class="notice">{{ error }}</p>
  <div class="section-heading">
    <h2>收支流水</h2>
    <span class="soft-tag">模拟钱包</span>
  </div>
  <EmptyState
    v-if="ledger && !ledger.items.length"
    class="panel"
    title="还没有收支记录"
    description="完成一笔模拟充值或提现后，流水会出现在这里。"
  />
  <ul v-else-if="ledger" class="ledger-list panel">
    <li v-for="item in ledger.items" :key="item.id">
      <span class="ledger-type">{{ BIZ_LABELS[item.biz_type] || item.biz_type }}</span>
      <span class="ledger-time">{{ new Date(item.created_at).toLocaleString() }}</span>
      <strong :class="item.delta >= 0 ? 'ledger-in' : 'ledger-out'"
        >{{ item.delta >= 0 ? "+" : "" }}{{ yuan(item.delta) }}</strong
      ><small>余额 {{ yuan(item.balance_after) }}</small>
    </li>
  </ul>

  <!-- 充值弹窗 -->
  <div v-if="rechargeOpen" class="dialog-backdrop" @click.self="rechargeOpen = false">
    <section class="dialog" role="dialog" aria-modal="true" aria-labelledby="recharge-title">
      <button class="dialog-close icon-button" aria-label="关闭" @click="rechargeOpen = false">
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
      ><button class="primary-button full-width" @click="submitRecharge">去支付</button>
    </section>
  </div>

  <!-- 模拟收银台（演的，触发回调即完成支付） -->
  <div v-if="cashierOrder" class="dialog-backdrop">
    <section class="dialog" role="dialog" aria-modal="true" aria-labelledby="cashier-title">
      <p class="eyebrow">MOCK CASHIER</p>
      <h2 id="cashier-title">模拟收银台</h2>
      <p>充值单 {{ cashierOrder.out_trade_no }}</p>
      <p>应付金额：¥{{ yuan(cashierOrder.amount_cent) }}（模拟支付，不会真实扣款）</p>
      <button class="primary-button full-width" @click="confirmPaid">
        我已支付（触发模拟回调）
      </button>
    </section>
  </div>

  <!-- 提现弹窗 -->
  <div v-if="withdrawOpen" class="dialog-backdrop" @click.self="withdrawOpen = false">
    <section class="dialog" role="dialog" aria-modal="true" aria-labelledby="withdraw-title">
      <button class="dialog-close icon-button" aria-label="关闭" @click="withdrawOpen = false">
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
      ><button class="primary-button full-width" @click="submitWithdraw">确认提现</button>
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