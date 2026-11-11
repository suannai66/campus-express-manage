<script setup>
import { MapPin, ArrowDown, Clock3, ArrowUpRight } from "@lucide/vue";
defineProps({ task: Object });
defineEmits(["details"]);
const money = (cents) => (cents / 100).toFixed(2);
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
        <span class="reward-label">{{ task.live ? "总费用" : "代取小费" }}</span
        ><strong class="reward"
          ><small>¥</small
          >{{ task.live ? money(task.amount) : task.reward.toFixed(2) }}</strong
        >
        <details v-if="task.live" class="fee-breakdown">
          <summary>费用明细</summary>
          <div class="fee-popover">
            <p>
              <span>运费</span><strong>¥{{ money(task.baseFee) }}</strong>
            </p>
            <p>
              <span>小费</span><strong>¥{{ money(task.tip) }}</strong>
            </p>
            <p class="fee-total">
              <span>总费用</span><strong>¥{{ money(task.amount) }}</strong>
            </p>
          </div>
        </details>
      </div>
      <button class="outline-button" @click="$emit('details', task)">
        查看详情 <ArrowUpRight :size="15" />
      </button>
    </div>
  </article>
</template>
<style scoped>
.fee-breakdown {
  position: relative;
  display: inline-block;
  margin-left: 12px;
  vertical-align: middle;
  font-size: 12px;
}
.fee-breakdown summary {
  cursor: pointer;
  color: var(--green, #24594b);
  padding: 6px 0;
}
.fee-popover {
  position: absolute;
  bottom: calc(100% + 8px);
  left: -60px;
  z-index: 2;
  width: 190px;
  padding: 14px;
  background: white;
  border: 1px solid var(--border);
  border-radius: 12px;
  box-shadow: 0 8px 24px #163e2920;
}
.fee-popover p {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  margin: 0;
  padding: 6px 0;
}
.fee-total {
  border-top: 1px solid var(--border);
}
</style>
