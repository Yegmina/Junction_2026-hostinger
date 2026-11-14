<script setup>
import { computed, onBeforeUnmount, onMounted } from "vue";
import { KIND_LABELS, cleanText, derived, domainOf, store } from "../store.js";

const fact = computed(() => derived.evidenceById[store.openEvidenceId]);
const close = () => (store.openEvidenceId = "");
const onKey = (e) => e.key === "Escape" && close();
onMounted(() => window.addEventListener("keydown", onKey));
onBeforeUnmount(() => window.removeEventListener("keydown", onKey));
</script>

<template>
  <Transition name="drawer">
    <div v-if="fact" class="drawer-wrap" @click.self="close">
      <aside class="drawer" role="dialog" aria-modal="true" :aria-label="`Evidence ${fact.id}`">
        <header>
          <span class="eid">{{ fact.id }}</span>
          <span class="kind-tag">{{ KIND_LABELS[fact.kind] }}</span>
          <button type="button" class="icon-btn" aria-label="Close" @click="close">✕</button>
        </header>
        <h3>{{ fact.title }}</h3>
        <p class="fact-text">{{ cleanText(fact.text) }}</p>
        <h4>Sources</h4>
        <ul class="src-list">
          <li v-for="s in fact.sources" :key="s.name + s.url">
            <a v-if="s.url" :href="s.url" target="_blank" rel="noopener noreferrer">{{ s.name }}</a>
            <span v-else>{{ s.name }}</span>
            <small v-if="s.url" class="muted"> · {{ domainOf(s.url) }}</small>
          </li>
        </ul>
        <button type="button" class="ghost" @click="store.tab = 'evidence'; close()">See all evidence</button>
      </aside>
    </div>
  </Transition>
</template>
