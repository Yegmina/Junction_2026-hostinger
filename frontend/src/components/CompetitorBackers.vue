<script setup>
import { computed } from "vue";
import { store } from "../store.js";

const rows = computed(() => store.graph.filter((c) => c.backers.length));
const shortlisted = computed(() => new Set((store.committee?.investorTargets || []).map((t) => t.name.toLowerCase())));
</script>

<template>
  <section v-if="store.graph.length" class="card">
    <h3>Who backs your competitors</h3>
    <p class="muted small">From INVESTED_IN edges in the Cala knowledge graph. Pitching these investors may mean a conflict of interest.</p>
    <ul class="backers">
      <li v-for="c in rows" :key="c.id">
        <b>{{ c.name }}</b>
        <span class="arrow" aria-hidden="true">←</span>
        <span class="bchips">
          <span v-for="b in c.backers.slice(0, 6)" :key="b" :class="['pchip', { hit: shortlisted.has(b.toLowerCase()) }]">{{ b }}</span>
          <span v-if="c.backers.length > 6" class="muted small">+{{ c.backers.length - 6 }}</span>
        </span>
      </li>
    </ul>
    <p v-if="!rows.length" class="muted small">The graph has no recorded backers for the competitors Cala found.</p>
  </section>
</template>
