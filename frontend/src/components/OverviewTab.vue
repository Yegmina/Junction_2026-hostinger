<script setup>
import { ref } from "vue";
import { derived, eur, pct, store } from "../store.js";
import CiteChips from "./CiteChips.vue";
import ProbabilityRing from "./ProbabilityRing.vue";
import Skeleton from "./Skeleton.vue";

const done = ref({});
const stanceIcon = { back: "👍", conditional: "🤔", pass: "👎" };
</script>

<template>
  <div class="overview">
    <section class="card verdict-card">
      <template v-if="store.plan">
        <ProbabilityRing :value="store.plan.event.probability" :low="store.plan.event.low" :high="store.plan.event.high" />
        <div class="verdict-body">
          <p class="eyebrow">Chance to close {{ eur(store.submitted.targetAmountEur) }} {{ store.submitted.stage }} within {{ store.submitted.horizonMonths }} months</p>
          <p class="verdict">{{ store.plan.verdict || store.plan.event.explanation }}</p>
          <p class="muted small">Range across scenarios {{ pct(store.plan.event.low) }}–{{ pct(store.plan.event.high) }} ·
            <button type="button" class="link" @click="store.tab = 'scenarios'">how it is calculated</button></p>
        </div>
      </template>
      <Skeleton v-else :lines="3" label="Building scenarios from Cala evidence…" />
    </section>

    <div class="kpis">
      <div class="kpi"><b>{{ store.evidence.length }}</b><span>sourced facts</span></div>
      <div class="kpi"><b>{{ derived.sourceCount }}</b><span>sources</span></div>
      <div class="kpi"><b>{{ store.plan?.drivers.length ?? "–" }}</b><span>drivers</span></div>
      <div class="kpi"><b>{{ store.committee?.investorTargets.length ?? "–" }}</b><span>leads found</span></div>
    </div>

    <div class="grid2">
      <section class="card">
        <header class="card-head"><h3>Most likely future</h3>
          <button v-if="store.plan" type="button" class="link" @click="store.tab = 'scenarios'">All 4 scenarios →</button></header>
        <template v-if="derived.mostLikely">
          <p class="scen-name">{{ derived.mostLikely.name }} <span class="pill">{{ pct(derived.mostLikely.probability) }} likely</span></p>
          <p>{{ derived.mostLikely.oneLiner || derived.mostLikely.narrative }}</p>
          <p class="muted small">In this future your round closes with {{ pct(derived.mostLikely.eventProbabilityIfScenario) }} probability.</p>
        </template>
        <Skeleton v-else :lines="2" />
      </section>

      <section class="card">
        <header class="card-head"><h3>Committee says</h3>
          <button v-if="store.committee" type="button" class="link" @click="store.tab = 'investors'">Full debate →</button></header>
        <template v-if="store.committee">
          <ul class="mini-members">
            <li v-for="m in store.committee.members" :key="m.persona">
              <span :class="['stance', m.stance]">{{ stanceIcon[m.stance] }}</span>
              <span><b>{{ m.persona.split(" (")[0] }}:</b> {{ m.headline || m.stance }}</span>
            </li>
          </ul>
        </template>
        <Skeleton v-else :lines="3" :label="store.plan ? 'Committee is debating…' : ''" />
      </section>
    </div>

    <section class="card">
      <header class="card-head"><h3>Who to pitch first</h3>
        <button v-if="store.committee" type="button" class="link" @click="store.tab = 'investors'">All leads →</button></header>
      <div v-if="store.committee" class="lead-row">
        <article v-for="(t, i) in store.committee.investorTargets.slice(0, 3)" :key="t.name" class="lead-mini">
          <span class="rank">#{{ i + 1 }}</span>
          <div>
            <b>{{ t.name }}</b>
            <div class="fitbar"><span :style="{ width: pct(t.fitScore) }" /></div>
            <p class="small">{{ t.why }}</p>
            <CiteChips :ids="t.evidence.slice(0, 3)" />
          </div>
        </article>
        <p v-if="!store.committee.investorTargets.length" class="muted">No investor in the Cala evidence matched well enough.</p>
      </div>
      <Skeleton v-else :lines="2" />
    </section>

    <section v-if="store.committee?.nextActions.length" class="card">
      <h3>Your next steps</h3>
      <ul class="checklist">
        <li v-for="(a, i) in store.committee.nextActions" :key="a">
          <label :class="{ checked: done[i] }"><input v-model="done[i]" type="checkbox" /> {{ a }}</label>
        </li>
      </ul>
    </section>
  </div>
</template>
