<script setup>
import { nextTick, onBeforeUnmount, ref, watch } from "vue";
import { verificationApi } from "./verification-api";
const props = defineProps({ applicationId: String });
const emit = defineEmits(["close"]);
const dialog = ref(null),
  url = ref(""),
  error = ref(""),
  loading = ref(false);
let generation = 0;
function revoke() {
  if (url.value) URL.revokeObjectURL(url.value);
  url.value = "";
}
watch(
  () => props.applicationId,
  async (id) => {
    const version = ++generation;
    revoke();
    error.value = "";
    if (!id) {
      dialog.value?.close();
      return;
    }
    await nextTick();
    if (!dialog.value.open) dialog.value.showModal();
    loading.value = true;
    try {
      const blob = await verificationApi.photo(id);
      if (version === generation) url.value = URL.createObjectURL(blob);
    } catch (cause) {
      if (version === generation) error.value = cause.message;
    } finally {
      if (version === generation) loading.value = false;
    }
  },
);
onBeforeUnmount(() => {
  generation++;
  revoke();
  dialog.value?.close();
});
</script>
<template>
  <dialog
    ref="dialog"
    aria-labelledby="verification-photo-title"
    @cancel.prevent="emit('close')"
    @click.self="emit('close')"
  >
    <h2 id="verification-photo-title">证件照片</h2>
    <p v-if="loading">正在读取照片…</p>
    <p v-if="error" role="alert">{{ error }}</p>
    <img v-if="url" :src="url" alt="本次申请提交的学生证件照片" />
    <button class="outline-button" @click="emit('close')">关闭照片</button>
  </dialog>
</template>
<style scoped>
dialog {
  border: 1px solid var(--border);
  border-radius: 16px;
  padding: 24px;
  width: min(660px, calc(100vw - 40px));
  max-height: 90vh;
  overflow: auto;
  color: var(--text);
}
dialog::backdrop {
  background: #173e32a0;
}
img {
  display: block;
  max-width: 100%;
  max-height: 65vh;
  object-fit: contain;
  margin: 16px auto;
}
button {
  margin-top: 16px;
}
</style>
