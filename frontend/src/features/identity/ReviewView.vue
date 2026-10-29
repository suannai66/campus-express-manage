<script setup>
import PageHeading from "../../components/PageHeading.vue";
import EmptyState from "../../components/EmptyState.vue";
</script>
<template>
  <PageHeading
    title="学生认证审核"
    subtitle="审核姓名、学号与证件信息；驳回时需填写具体理由。"
    eyebrow="ADMINISTRATION"
  />
  <div class="notice">
    管理员审核入口预留。尚未接入账号权限和认证申请，当前不显示任何学生资料。
  </div>
  <EmptyState
    class="panel"
    title="审核服务尚未连接"
    description="接入后仅向具有审核权限的管理员展示待审核申请。"
  />
</template>
