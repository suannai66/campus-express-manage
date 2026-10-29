<script setup>
import { X } from "@lucide/vue";
import { ref, watch, nextTick } from "vue";
const props = defineProps({ task: Object });
const emit = defineEmits(["close"]);
const dialog = ref(null);
let previousFocus;
watch(
  () => props.task,
  async (task) => {
    if (task) {
      previousFocus = document.activeElement;
      await nextTick();
      dialog.value?.querySelector("button")?.focus();
    } else previousFocus?.focus();
  },
);
function keyboard(event) {
  if (event.key === "Escape") emit("close");
  if (event.key !== "Tab") return;
  const buttons = dialog.value.querySelectorAll("button");
  if (event.shiftKey && document.activeElement === buttons[0]) {
    event.preventDefault();
    buttons[buttons.length - 1].focus();
  } else if (
    !event.shiftKey &&
    document.activeElement === buttons[buttons.length - 1]
  ) {
    event.preventDefault();
    buttons[0].focus();
  }
}
</script>
<template>
  <Teleport to="body"
    ><div
      v-if="task"
      class="dialog-backdrop"
      @click.self="$emit('close')"
      @keydown="keyboard"
    >
      <section
        ref="dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="task-title"
        class="dialog"
      >
        <button
          autofocus
          class="dialog-close icon-button"
          aria-label="关闭详情"
          @click="$emit('close')"
        >
          <X :size="20" />
        </button>
        <p class="eyebrow">示例任务</p>
        <h2 id="task-title">{{ task.station }} → {{ task.building }}</h2>
        <p>{{ task.company }} · {{ task.size }} · {{ task.time }}送达</p>
        <p>{{ task.note }}</p>
        <div class="notice">
          此任务为界面示例。接单将由实名认证、信用校验及订单服务接入后开放。
        </div>
        <button class="primary-button" @click="$emit('close')">知道了</button>
      </section>
    </div></Teleport
  >
</template>
