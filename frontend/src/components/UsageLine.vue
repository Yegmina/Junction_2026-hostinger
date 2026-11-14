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
const web = computed(() => {
  const u = store.usage;
  if (!u) return [];
  const out = [];
  if (u.webSearches || u.webScrapes) out.push(`Oxylabs: ${u.webSearches || 0} searches, ${u.webScrapes || 0} scrapes`);
  if (u.contextDev) out.push(`Context.dev: ${u.contextDev} calls`);
  if (u.nemotron) out.push(`NVIDIA Nemotron: ${u.nemotron} audit call${u.nemotron === 1 ? "" : "s"}`);
  return out;
});
const storage = computed(() => {
  const s = store.modes?.storage;
  if (!s || !store.usage) return "";
  const out = [];
  if (s.reports !== "files") out.push(`report saved in ${s.reports}`);
  if (s.cache !== "files") out.push(`API cache and rate limits in ${s.cache}`);
  return out.join(" · ");
});
</script>

<template>
  <p v-if="store.usage" class="usage-line small">
    <span class="usage-tag">Powered by Cala</span>
    This report used {{ parts.join(" · ") }}<template v-if="store.usage.cached"> ({{ store.usage.cached }} served from the 24 h cache)</template>.
  </p>
  <p v-if="web.length" class="usage-line small"><span class="usage-tag web">Live web</span>{{ web.join(" · ") }}.</p>
  <p v-if="storage" class="usage-line small"><span class="usage-tag store">Storage</span>{{ storage[0].toUpperCase() + storage.slice(1) }}.</p>
</template>
