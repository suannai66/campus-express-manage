<script setup>
import PageHeading from "../../components/PageHeading.vue";
import EmptyState from "../../components/EmptyState.vue";
</script>
<template>
  <PageHeading
    title="认真对待，每一份信任"
    subtitle="订单送达后可进行评价，信用让校园互助更安心。"
    eyebrow="REVIEWS & CREDIT"
  />
  <div class="summary-grid">
    <div class="panel summary">
      <p>我的信用分</p>
      <strong>— <small>/ 5.0</small></strong
      ><span>登录后查询，暂无真实数据</span>
    </div>
    <div class="panel summary">
      <p>信用规则</p>
      <h3>近 30 单评价均分</h3>
      <span>信用分低于 3.0 时限制接单</span>
    </div>
  </div>
  <EmptyState
    class="panel"
    title="还未加载评价记录"
    description="评价服务接入后，在此查看已送达订单的评价。"
  />
</template>
