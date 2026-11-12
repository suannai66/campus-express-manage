<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from "vue";

const props = defineProps({
  pending: Boolean,
  labelledby: { type: String, required: true },
  describedby: { type: String, default: undefined },
});
const emit = defineEmits(["dismiss"]);
const dialog = ref(null);

function dismiss() {
  if (!props.pending) emit("dismiss");
}

function handleBackdrop(event) {
  if (event.target !== dialog.value) return;
  const bounds = dialog.value.getBoundingClientRect();
  if (
    event.clientX < bounds.left ||
    event.clientX > bounds.right ||
    event.clientY < bounds.top ||
    event.clientY > bounds.bottom
  )
    dismiss();
}

function handleTab(event) {
  const controls = [...dialog.value.querySelectorAll("button, input")].filter(
    (control) =>
      !control.matches(":disabled") &&
      (control.type !== "radio" || control.checked),
  );
  const index = controls.indexOf(document.activeElement);
  if (
    !controls.length ||
    index === -1 ||
    (event.shiftKey ? index === 0 : index === controls.length - 1)
  ) {
    event.preventDefault();
    const target = event.shiftKey ? controls.at(-1) : controls[0];
    (target ?? dialog.value.querySelector("[data-initial-focus]"))?.focus();
  }
}

onMounted(() => {
  dialog.value.showModal();
  dialog.value.querySelector("[data-initial-focus]")?.focus();
});

watch(
  () => props.pending,
  (pending) => {
    if (pending && !dialog.value.contains(document.activeElement)) {
      dialog.value.querySelector("[data-initial-focus]")?.focus();
    }
  },
  { flush: "post" },
);

onBeforeUnmount(() => dialog.value?.close());
</script>

<template>
  <dialog
    ref="dialog"
    class="dialog finance-dialog"
    :aria-labelledby="labelledby"
    :aria-describedby="describedby"
    @cancel.prevent="dismiss"
    @click="handleBackdrop"
    @keydown.tab="handleTab"
  >
    <slot />
  </dialog>
</template>

<style scoped>
.finance-dialog {
  width: min(500px, calc(100% - 32px));
  max-height: calc(100dvh - 32px);
  margin: auto;
  overflow: auto;
  border: 1px solid transparent;
}
.finance-dialog::backdrop {
  background: #12322480;
  backdrop-filter: blur(4px);
}
.finance-dialog :deep(:focus-visible) {
  outline: 3px solid #275e46;
  outline-offset: 3px;
}
.finance-dialog :deep(p) {
  color: #47584a;
}
@media (forced-colors: active) {
  .finance-dialog {
    border-color: CanvasText;
  }
  .finance-dialog :deep(:focus-visible) {
    outline-color: Highlight;
  }
  .finance-dialog :deep(button) {
    border: 1px solid ButtonText;
  }
}
</style>
