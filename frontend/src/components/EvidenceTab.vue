<script setup>
import { computed, ref } from "vue";
import { KIND_LABELS, cleanText, domainOf, store } from "../store.js";

const kind = ref("all");
const query = ref("");
const open = ref("");
const counts = computed(() => {
  const c = { all: store.evidence.length };
  store.evidence.forEach((e) => (c[e.kind] = (c[e.kind] || 0) + 1));
  return c;
});
const shown = computed(() => {
  const q = query.value.toLowerCase();
  return store.evidence.filter(
    (e) => (kind.value === "all" || e.kind === kind.value) && (!q || `${e.title} ${e.text}`.toLowerCase().includes(q)),
  );
});
</script>

<template>
  <section class="card evidence-tab">
    <header class="card-head">
      <h3>Evidence from {{ store.dataMode === "cala" ? (counts.web ? "Cala and the live web" : "Cala") : "demo dataset" }}</h3>
      <input v-model="query" type="search" class="search" placeholder="Search facts" aria-label="Search facts" />
    </header>
    <div class="filters">
      <button v-for="k in ['all', 'competitor', 'funding', 'investor', 'market', 'graph', 'web']" :key="k" type="button"
        :class="['chip', { on: kind === k }]" :disabled="!counts[k]" @click="kind = k">
        {{ k === "all" ? "All" : KIND_LABELS[k] }} <small>{{ counts[k] || 0 }}</small>
      </button>
    </div>
    <p v-for="e in store.evidenceErrors" :key="e" class="warn small">{{ e }}</p>
    <TransitionGroup tag="ul" name="list" class="facts">
      <li v-for="e in shown" :id="`ev-${e.id}`" :key="e.id" :class="{ open: open === e.id }">
        <button type="button" class="fact-row" :aria-expanded="open === e.id" @click="open = open === e.id ? '' : e.id">
          <span class="eid">{{ e.id }}</span>
          <span class="ftitle">{{ e.title }}</span>
          <span class="fdomain">{{ domainOf(e.sources[0]?.url) || e.sources[0]?.name }}</span>
        </button>
        <Transition name="fold">
          <div v-if="open === e.id" class="fact-more">
            <p class="fact-text">{{ cleanText(e.text) }}</p>
            <p class="srcs">
              <template v-for="s in e.sources" :key="s.name + s.url">
                <a v-if="s.url" :href="s.url" target="_blank" rel="noopener noreferrer">{{ s.name }}</a>
                <span v-else>{{ s.name }}</span>
              </template>
            </p>
          </div>
        </Transition>
      </li>
    </TransitionGroup>
    <p v-if="!shown.length" class="muted">No facts match.</p>
  </section>
</template>
