<script setup>
import { computed } from "vue";
import { store } from "../store.js";

const parts = computed(() => {
  const u = store.usage;
  if (!u) return [];
  const n = (count, one, many = `${one}s`) => `${count} ${count === 1 ? one : many}`;
  return [
    n(u.searches, "knowledge search", "knowledge searches"),
    n(u.queries, "structured query", "structured queries"),
    n(u.entityLookups, "entity lookup"),
    n(u.relationships, "graph relationship"),
  ];
});
</script>

<template>
  <p v-if="store.usage" class="usage-line small">
    <span class="usage-tag">Powered by Cala</span>
    This report used {{ parts.join(" · ") }}<template v-if="store.usage.cached"> ({{ store.usage.cached }} served from the 24 h cache)</template>.
  </p>
</template>
