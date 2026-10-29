<script setup>
import { ref } from "vue";
import PageHeading from "../../components/PageHeading.vue";
import EmptyState from "../../components/EmptyState.vue";
const message = ref("");
</script>
<template>
  <PageHeading
    title="每一份感谢，都有记录"
    subtitle="查看账户余额、代取收益与收支流水。"
    eyebrow="MY WALLET"
  />
  <section class="wallet-banner">
    <p>可用余额（元）</p>
    <strong>¥ —</strong><span>登录后查询余额 · 课程演示使用模拟资金</span>
    <div class="hero-actions">
      <button
        class="light-button"
        @click="message = '充值服务尚未接入，当前不会产生交易。'"
      >
        模拟充值</button
      ><button
        class="hero-link"
        @click="message = '提现服务尚未接入，当前不会产生交易。'"
      >
        模拟提现 ↗
      </button>
    </div>
  </section>
  <p v-if="message" role="status" class="notice">{{ message }}</p>
  <div class="section-heading">
    <h2>收支流水</h2>
    <span class="soft-tag">模拟钱包</span>
  </div>
  <EmptyState
    class="panel"
    title="收支流水尚未加载"
    description="接入钱包服务后，可查询充值、提现、支付与结算记录。"
  />
</template>
