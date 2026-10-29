<script setup>
import { computed, ref } from "vue";
import PageHeading from "../../components/PageHeading.vue";
import TaskCard from "../../components/TaskCard.vue";
import TaskDialog from "../../components/TaskDialog.vue";
import EmptyState from "../../components/EmptyState.vue";
import { demoTasks } from "../../data/demo";
const station = ref(""),
  building = ref(""),
  reward = ref(""),
  selected = ref(null);
const tasks = computed(() =>
  demoTasks.filter(
    (t) =>
      (!station.value || t.station === station.value) &&
      (!building.value || t.building.includes(building.value)) &&
      (!reward.value || t.reward >= Number(reward.value)),
  ),
);
</script>
<template>
  <PageHeading
    title="顺路带一件，温暖多一点"
    subtitle="发现校园里的代取需求，找到属于你的顺路任务。"
    eyebrow="TASK HALL"
  />
  <div class="filter-bar panel">
    <label
      >取件点<select v-model="station">
        <option value="">全部取件点</option>
        <option>菜鸟驿站</option>
        <option>顺丰服务点</option>
      </select></label
    ><label
      >送达区域<select v-model="building">
        <option value="">全部宿舍</option>
        <option value="沁园">沁园</option>
        <option value="竹园">竹园</option>
      </select></label
    ><label
      >小费范围<select v-model="reward">
        <option value="">不限金额</option>
        <option value="3">3 元及以上</option>
        <option value="5">5 元及以上</option>
      </select></label
    ><button
      class="text-button"
      @click="
        station = '';
        building = '';
        reward = '';
      "
    >
      重置筛选
    </button>
  </div>
  <div class="section-heading">
    <h2>
      待接单任务 <span class="soft-tag">{{ tasks.length }} 条示例</span>
    </h2>
    <span class="muted">仅展示虚构数据，不开放真实接单</span>
  </div>
  <div v-if="tasks.length" class="task-grid">
    <TaskCard
      v-for="task in tasks"
      :key="task.id"
      :task="task"
      @details="selected = $event"
    />
  </div>
  <EmptyState
    v-else
    class="panel"
    title="暂时没有匹配的任务"
    description="试试选择其他取件点或调整小费范围。"
  /><TaskDialog :task="selected" @close="selected = null" />
</template>
