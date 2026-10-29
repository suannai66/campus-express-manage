<script setup>
import { PackageOpen } from "@lucide/vue";
defineProps({ title: String, description: String });
</script>
<template>
  <div class="empty">
    <PackageOpen :size="44" :stroke-width="1.3" />
    <h3>{{ title }}</h3>
    <p>{{ description }}</p>
    <slot />
  </div>
</template>
