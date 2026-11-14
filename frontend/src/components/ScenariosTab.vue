<script setup>
import { computed, ref } from "vue";
import { derived, pct, store } from "../store.js";
import CiteChips from "./CiteChips.vue";

const selected = ref("");
const plan = computed(() => store.plan);
const cells = computed(() => {
  if (!plan.value) return [];
  const find = (a, b) => plan.value.scenarios.find((s) => s.position[0] === a && s.position[1] === b);
  return [find("low", "high"), find("high", "high"), find("low", "low"), find("high", "low")];
});
const active = computed(() => derived.scenarioById[selected.value] || derived.mostLikely);
</script>

<template>
  <div v-if="plan" class="scenarios">
    <section class="card">
      <header class="card-head"><h3>Four possible futures</h3><span class="muted small">Click a quadrant for details</span></header>
      <p class="yaxis-h small"><b>↑ {{ plan.axes[1].name }}</b>: top row {{ plan.axes[1].highLabel }}, bottom row {{ plan.axes[1].lowLabel }}</p>
      <div class="matrix-wrap">
        <div class="matrix">
          <button v-for="s in cells" :key="s.id" type="button"
            :class="['cell', { on: active?.id === s.id }]" :style="{ '--p': s.probability }" @click="selected = s.id">
            <span class="cell-top"><b>{{ s.name }}</b><span class="pill">{{ pct(s.probability) }}</span></span>
            <span class="cell-line">{{ s.oneLiner }}</span>
            <span class="cell-close">Round closes: <b>{{ pct(s.eventProbabilityIfScenario) }}</b></span>
          </button>
        </div>
        <div class="xaxis"><span>{{ plan.axes[0].lowLabel }}</span><b>{{ plan.axes[0].name }} →</b><span>{{ plan.axes[0].highLabel }}</span></div>
      </div>
    </section>

    <Transition name="fade" mode="out-in">
      <section v-if="active" :key="active.id" class="card">
        <header class="card-head"><h3>{{ active.name }}</h3><span class="pill">{{ pct(active.probability) }} likely</span></header>
        <p>{{ active.narrative }}</p>
        <h4>Signposts to watch</h4>
        <ul class="signposts"><li v-for="sp in active.signposts" :key="sp">{{ sp }}</li></ul>
        <CiteChips :ids="active.evidence" />
      </section>
    </Transition>

    <section class="card">
      <h3>How the {{ pct(plan.event.probability) }} is calculated</h3>
      <p class="muted small">Probability of each future × chance the round closes in it, summed.</p>
      <div class="breakdown">
        <div v-for="b in plan.event.breakdown" :key="b.scenarioId" class="brow">
          <span class="bname">{{ derived.scenarioById[b.scenarioId]?.name }}</span>
          <span class="bmath">{{ pct(b.weight) }} × {{ pct(b.conditional) }}</span>
          <span class="bar"><span :style="{ width: pct(b.contribution / Math.max(plan.event.probability, 0.01)) }" /></span>
          <span class="bval">{{ pct(b.contribution) }}</span>
        </div>
      </div>
      <details class="more"><summary>Analyst reasoning</summary><p>{{ plan.event.explanation }}</p></details>
    </section>
  </div>
</template>
