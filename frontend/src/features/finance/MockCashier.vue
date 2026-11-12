<script setup>
import { computed, onBeforeUnmount, ref, watch } from "vue";
import FinanceDialog from "./FinanceDialog.vue";
import { X, ShieldCheck, MessageCircle, Wallet } from "@lucide/vue";
import QRCode from "qrcode";

// 统一展示入口；不持有凭证、不调用资金接口，确认仍由父用例负责。
const props = defineProps({
  operation: { type: String, required: true },
  reference: { type: String, required: true },
  amount: { type: Number, required: true },
  pending: Boolean,
  error: { type: String, default: "" },
});
const emit = defineEmits(["confirm", "close"]);
const channel = ref("wechat");
const qr = ref("");
const qrError = ref("");
const isRecharge = computed(() => props.operation === "recharge");
const channelName = computed(() =>
  channel.value === "wechat" ? "微信" : "支付宝",
);
const money = computed(() => (props.amount / 100).toFixed(2));
let generation = 0;
watch(
  () => [props.reference, props.operation, channel.value],
  async () => {
    const current = ++generation;
    qr.value = "";
    qrError.value = "";
    try {
      // 只编码模拟凭证，不包含 Token、UID、真实收款地址或可执行确认链接。
      const value = await QRCode.toDataURL(
        `mock-wallet:v1:${props.operation}:${props.reference}:${channel.value}`,
        {
          width: 208,
          margin: 2,
          errorCorrectionLevel: "M",
          color: { dark: "#163c32", light: "#ffffff" },
        },
      );
      if (current === generation) qr.value = value;
    } catch {
      if (current === generation)
        qrError.value = "模拟凭证生成失败，请关闭后重试。";
    }
  },
  { immediate: true },
);
function close() {
  if (!props.pending) emit("close");
}
onBeforeUnmount(() => {
  generation++;
});
</script>

<template>
  <FinanceDialog
    class="cashier"
    labelledby="mock-cashier-title"
    describedby="mock-cashier-amount"
    :pending="pending"
    @dismiss="close"
  >
    <button
      class="dialog-close icon-button"
      aria-label="关闭模拟收银台"
      :disabled="pending"
      @click="close"
    >
      <X :size="20" />
    </button>
    <p class="eyebrow">CAMPUS · DEMO CASHIER</p>
    <h2 id="mock-cashier-title" tabindex="-1" data-initial-focus>
      {{ isRecharge ? "模拟充值收银台" : "模拟提现确认" }}
    </h2>
    <p class="cashier-caption">
      {{ isRecharge ? "选择模拟支付方式" : "选择模拟到账方式，无需付款" }}
    </p>
    <strong id="mock-cashier-amount" class="cashier-amount"
      >金额 {{ money }} 元</strong
    >
    <fieldset class="channels" :disabled="pending">
      <legend class="sr-label">模拟渠道</legend>
      <label :class="{ selected: channel === 'wechat' }"
        ><input
          v-model="channel"
          type="radio"
          value="wechat"
          name="mock-channel"
        /><MessageCircle :size="22" class="wechat" /><span>微信</span></label
      >
      <label :class="{ selected: channel === 'alipay' }"
        ><input
          v-model="channel"
          type="radio"
          value="alipay"
          name="mock-channel"
        /><Wallet :size="22" class="alipay" /><span>支付宝</span></label
      >
    </fieldset>
    <div class="qr-panel">
      <img
        v-if="qr"
        :src="qr"
        :alt="`${channelName}模拟${isRecharge ? '充值' : '提现'}凭证二维码`"
        width="208"
        height="208"
      />
      <p v-else>{{ qrError || "正在生成模拟凭证…" }}</p>
      <span
        >{{ channelName }} ·
        {{ isRecharge ? "模拟支付凭证" : "模拟收款凭证" }}</span
      >
    </div>
    <p class="reference">
      {{ isRecharge ? "充值单" : "模拟凭证" }} {{ reference }}
    </p>
    <p class="demo-note">
      <ShieldCheck
        :size="17"
      />仅课堂演示，不连接微信或支付宝。二维码只包含模拟标识，扫码不会付款或入账。
    </p>
    <div role="alert" class="cashier-error">
      {{ error || qrError }}
    </div>
    <div aria-live="polite">{{ pending ? "正在处理，请稍候。" : "" }}</div>
    <button
      class="primary-button full-width"
      :disabled="pending || !qr"
      :aria-label="isRecharge ? '我已支付（模拟确认）' : '确认模拟提现'"
      @click="emit('confirm', channel)"
    >
      {{
        pending
          ? "正在处理…"
          : isRecharge
            ? "我已支付（模拟确认）"
            : "确认模拟提现"
      }}
    </button>
    <button class="text-button full-width" :disabled="pending" @click="close">
      稍后处理
    </button>
  </FinanceDialog>
</template>

<style scoped>
.cashier {
  width: min(440px, calc(100vw - 32px));
  max-height: calc(100dvh - 32px);
  overflow-y: auto;
  text-align: center;
}
.cashier-caption {
  color: var(--muted);
  margin-bottom: 8px;
}
.cashier-amount {
  display: block;
  font-size: 38px;
  margin: 8px 0 20px;
}
.channels {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
  border: 0;
  padding: 0;
  margin: 0 0 16px;
}
.channels label {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 12px 6px;
  border: 1px solid var(--border);
  border-radius: 12px;
  cursor: pointer;
}
.channels label.selected {
  background: #edf6f0;
  border-color: #367a60;
}
.channels input {
  width: auto;
  margin: 0;
  accent-color: #267454;
}
.wechat {
  color: #198744;
}
.alipay {
  color: #1677d2;
}
.qr-panel {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  padding: 10px;
  border-radius: 16px;
  background: #f5f8f6;
  min-height: 246px;
}
.qr-panel img {
  max-width: 100%;
  object-fit: contain;
}
.qr-panel span {
  color: var(--muted);
  font-size: 13px;
}
.reference {
  overflow-wrap: anywhere;
  font-size: 12px;
  color: var(--muted);
}
.demo-note {
  display: flex;
  gap: 7px;
  text-align: left;
  color: var(--muted);
  font-size: 12px;
  line-height: 1.6;
}
.demo-note svg {
  flex-shrink: 0;
  margin-top: 2px;
}
.cashier-error {
  color: #a23b35;
  text-align: left;
}
.full-width {
  margin-top: 10px;
}
.sr-label {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip-path: inset(50%);
}
</style>
