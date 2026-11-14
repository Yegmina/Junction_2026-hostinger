<script setup>
import { computed, ref } from "vue";
import { cancelAnalysis, clock, derived, store } from "../store.js";

const expanded = ref(false);
const progress = computed(() => (store.steps.length ? derived.doneSteps / store.steps.length : 0));
const groups = computed(() => {
  const out = [];
  for (const step of store.steps) {
    let g = out.find((x) => x.name === step.group);
    if (!g) out.push((g = { name: step.group, steps: [] }));
    g.steps.push(step);
  }
  return out;
});
const current = computed(() => store.steps.find((s) => s.state === "running"));
const calaRunning = computed(() => store.steps.some((s) => s.id.startsWith("cala:") && s.state === "running"));
const latest = computed(() => store.evidence.slice(-3).reverse());
const secs = (s) => s.seconds ?? (s.state === "running" && s.startedAt ? (store.now - s.startedAt) / 1000 : null);
const showDetail = computed(() => store.running || expanded.value);
</script>

<template>
  <section :class="['card', 'progress', { compact: !store.running }]" aria-live="polite">
    <header class="progress-head">
      <div>
        <h2 v-if="store.running">{{ current ? current.label : "Starting" }}…</h2>
        <h2 v-else-if="store.error">Stopped</h2>
        <h2 v-else>Done in {{ clock(derived.elapsed) }}</h2>
        <p class="muted small">
          {{ derived.doneSteps }}/{{ store.steps.length }} steps · {{ store.evidence.length }} sourced facts ·
          {{ derived.sourceCount }} sources
        </p>
      </div>
      <div class="progress-actions">
        <span v-if="store.running" class="clock">{{ clock(derived.elapsed) }}</span>
        <button v-if="store.running" type="button" class="ghost small-btn" @click="cancelAnalysis">Cancel</button>
        <button v-else type="button" class="ghost small-btn" @click="expanded = !expanded">{{ expanded ? "Hide steps" : "Show steps" }}</button>
      </div>
    </header>
    <div :class="['pbar', { live: store.running }]"><span :style="{ width: `${Math.max(progress, store.running ? 0.04 : 0) * 100}%` }" /></div>

    <Transition name="fold">
      <div v-if="showDetail" class="pdetail">
        <div class="pgroups">
          <div v-for="g in groups" :key="g.name" class="pgroup">
            <h3>{{ g.name }}</h3>
            <ul>
              <li v-for="s in g.steps" :key="s.id" :class="['pstep', s.state]">
                <span class="picon" aria-hidden="true">{{ { done: "✓", failed: "✕", pending: "○" }[s.state] || "" }}</span>
                <span class="plabel">{{ s.label }}<small v-if="s.detail"> · {{ s.detail }}</small></span>
                <span class="ptime">{{ secs(s) != null ? `${secs(s).toFixed(0)}s` : "" }}</span>
              </li>
            </ul>
          </div>
        </div>
        <p v-if="calaRunning" class="muted small">Cala is searching its knowledge graph live. This usually takes 40–70 seconds.</p>
        <TransitionGroup v-if="store.running && latest.length" tag="div" name="tick" class="ticker">
          <p v-for="f in latest" :key="f.id" class="tick"><b>{{ f.id }}</b>{{ f.title }}</p>
        </TransitionGroup>
      </div>
    </Transition>
  </section>
</template>
