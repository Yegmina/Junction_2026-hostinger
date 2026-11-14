<script setup>
defineProps({ lines: { type: Number, default: 3 }, label: { type: String, default: "" } });
</script>

<template>
  <div class="skeleton" aria-busy="true">
    <p v-if="label" class="muted small">{{ label }}</p>
    <span v-for="n in lines" :key="n" class="sk-line" :style="{ width: `${95 - n * 12}%` }" />
  </div>
</template>
