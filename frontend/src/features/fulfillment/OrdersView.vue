<script setup>
import { ref } from "vue";
import PageHeading from "../../components/PageHeading.vue";
import EmptyState from "../../components/EmptyState.vue";
const selected = ref("全部");
const statuses = [
  "全部",
  "待支付",
  "待接单",
  "已接单",
  "取件中",
  "配送中",
  "已送达",
];
</script>
<template>
  <PageHeading
    title="每一份托付，都有迹可循"
    subtitle="查看发布与接取的订单，关注包裹的每一步。"
    eyebrow="MY ORDERS"
  />
  <section class="panel">
    <div class="tabs" aria-label="订单状态">
      <button
        v-for="status in statuses"
        :key="status"
        :class="{ active: status === selected }"
        @click="selected = status"
      >
        {{ status }}
      </button>
    </div>
    <EmptyState
      :title="`${selected}订单尚未加载`"
      description="登录并接入订单服务后，即可查看自己的订单与履约进度。"
      ><RouterLink to="/login" class="primary-button"
        >去登录</RouterLink
      ></EmptyState
    >
  </section>
</template>
