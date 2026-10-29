<script setup>
defineProps({
  title: String,
  subtitle: String,
  eyebrow: { type: String, default: "CAMPUS EXPRESS" },
});
</script>
<template>
  <div class="page-heading">
    <div>
      <p class="eyebrow">{{ eyebrow }}</p>
      <h1>{{ title }}</h1>
      <p class="muted">{{ subtitle }}</p>
    </div>
    <slot />
  </div>
</template>
