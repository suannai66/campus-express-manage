<script setup>
import { MapPin, ArrowDown, Clock3, ArrowUpRight } from "@lucide/vue";
defineProps({ task: Object });
defineEmits(["details"]);
</script>
<template>
  <article class="task-card">
    <div class="task-top">
      <span class="courier-icon" :class="task.color">{{ task.initials }}</span>
      <div>
        <strong>{{ task.company }}</strong>
        <p>{{ task.size }}包裹 · 校园代取</p>
      </div>
      <span class="status-pill">待接单</span>
    </div>
    <div class="task-route">
      <p><MapPin :size="15" />{{ task.station }}</p>
      <ArrowDown class="route-down" :size="13" />
      <p><span class="destination-dot"></span>{{ task.building }}</p>
    </div>
    <div class="task-meta">
      <span><Clock3 :size="14" />{{ task.time }}</span
      ><span>{{
        task.live ? (task.demo ? "演示订单" : "已支付") : "示例任务"
      }}</span>
    </div>
    <div class="task-bottom">
      <div>
        <span class="reward-label">代取小费</span
        ><strong class="reward"
          ><small>¥</small>{{ task.reward.toFixed(2) }}</strong
        >
      </div>
      <button class="outline-button" @click="$emit('details', task)">
        查看详情 <ArrowUpRight :size="15" />
      </button>
    </div>
  </article>
</template>
