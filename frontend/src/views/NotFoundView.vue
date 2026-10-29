<script setup>
import EmptyState from "../components/EmptyState.vue";
</script>
<template>
  <EmptyState
    class="panel"
    title="这个页面还没有抵达"
    description="请检查地址，或回到首页继续浏览。"
    ><RouterLink to="/" class="primary-button">返回首页</RouterLink></EmptyState
  >
</template>
