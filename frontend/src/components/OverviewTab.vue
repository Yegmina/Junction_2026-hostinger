<script setup>
import { computed, ref } from "vue";
import { derived, eur, pct, store } from "../store.js";
import InvestorCard from "./InvestorCard.vue";
import ProbabilityRing from "./ProbabilityRing.vue";
import Skeleton from "./Skeleton.vue";

const done = ref({});
// Investors the graph links to competitors: the most useful "who not to pitch" signal.
const avoid = computed(() => {
  const out = [];
  const seen = new Set();
  for (const c of store.graph) {
    for (const b of c.backers) {
      if (seen.has(b) || out.length >= 3) continue;
      seen.add(b);
      out.push({ name: b, company: c.name });
    }
  }
  return out;
});
const verifiedLeads = computed(() => {
  const targets = store.committee?.investorTargets;
  if (!targets) return "–";
  if (!targets.some((t) => t.verification)) return `${targets.length}`;
  return `${targets.filter((t) => t.verification?.verified).length}/${targets.length}`;
});
const stanceIcon = { back: "👍", conditional: "🤔", pass: "👎" };
</script>

<template>
  <div class="overview">
    <section class="card verdict-card" style="order: 1">
      <template v-if="store.plan">
        <ProbabilityRing :value="store.plan.event.probability" :low="store.plan.event.low" :high="store.plan.event.high" />
        <div class="verdict-body">
          <p class="eyebrow">Outlook · chance to close {{ eur(store.submitted.targetAmountEur) }} {{ store.submitted.stage }} within {{ store.submitted.horizonMonths }} months</p>
          <p class="verdict">{{ store.plan.verdict || store.plan.event.explanation }}</p>
          <p class="muted small">Range across scenarios {{ pct(store.plan.event.low) }}–{{ pct(store.plan.event.high) }} ·
            <button type="button" class="link" @click="store.tab = 'scenarios'">how it is calculated</button></p>
        </div>
      </template>
      <Skeleton v-else :lines="3" label="Building scenarios from Cala evidence…" />
    </section>

    <div class="kpis" style="order: 2">
      <div class="kpi"><b>{{ store.evidence.length }}</b><span>sourced facts</span></div>
      <div class="kpi"><b>{{ derived.sourceCount }}</b><span>sources</span></div>
      <div class="kpi"><b>{{ store.plan?.drivers.length ?? "–" }}</b><span>drivers</span></div>
      <div class="kpi"><b>{{ verifiedLeads }}</b><span>leads verified in Cala graph</span></div>
    </div>

    <div class="grid2" style="order: 3">
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

    <!-- Once the shortlist exists it becomes the headline answer; before that the outlook leads. -->
    <section class="card pitch-card" :style="{ order: store.committee ? 0 : 4 }">
      <header class="card-head"><h3>Who to pitch first</h3>
        <button v-if="store.committee" type="button" class="link" @click="store.tab = 'investors'">All leads →</button></header>
      <p v-if="avoid.length" class="avoid small">⚠ Think twice: <span v-for="(a, i) in avoid" :key="a.name"><b>{{ a.name }}</b> backs {{ a.company }}{{ i < avoid.length - 1 ? "; " : "" }}</span>
        <small class="muted"> (Cala graph)</small></p>
      <div v-if="store.committee" class="lead-row">
        <InvestorCard v-for="(t, i) in store.committee.investorTargets.slice(0, 3)" :key="t.name" :target="t" :rank="i + 1" compact />
        <p v-if="!store.committee.investorTargets.length" class="muted">No investor in the Cala evidence matched well enough.</p>
      </div>
      <Skeleton v-else :lines="2" :label="store.plan ? 'Shortlisting investors…' : ''" />
    </section>

    <section v-if="store.committee?.nextActions.length" class="card" style="order: 5">
      <h3>Your next steps</h3>
      <ul class="checklist">
        <li v-for="(a, i) in store.committee.nextActions" :key="a">
          <label :class="{ checked: done[i] }"><input v-model="done[i]" type="checkbox" /> {{ a }}</label>
        </li>
      </ul>
    </section>
  </div>
</template>
