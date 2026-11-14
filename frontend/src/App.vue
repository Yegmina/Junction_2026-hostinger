<script setup>
import { computed, onMounted } from "vue";
import { eur, loadHealth, store } from "./store.js";
import DriversTab from "./components/DriversTab.vue";
import EvidenceDrawer from "./components/EvidenceDrawer.vue";
import EvidenceTab from "./components/EvidenceTab.vue";
import InvestorsTab from "./components/InvestorsTab.vue";
import OverviewTab from "./components/OverviewTab.vue";
import ProgressPanel from "./components/ProgressPanel.vue";
import ScenariosTab from "./components/ScenariosTab.vue";
import StartupForm from "./components/StartupForm.vue";

const tabs = computed(() => [
  { id: "overview", label: "Overview", ready: true },
  { id: "scenarios", label: "Scenarios", ready: !!store.plan },
  { id: "drivers", label: "Drivers", ready: !!store.plan, count: store.plan?.drivers.length },
  { id: "investors", label: "Investors", ready: !!store.committee, count: store.committee?.investorTargets.length },
  { id: "evidence", label: "Evidence", ready: store.evidence.length > 0, count: store.evidence.length },
]);
const views = { overview: OverviewTab, scenarios: ScenariosTab, drivers: DriversTab, investors: InvestorsTab, evidence: EvidenceTab };
const hasRun = computed(() => !!store.submitted && !store.editing);

const howItWorks = [
  ["Cala evidence", "Competitors, recent rounds and active lead investors, each with its source."],
  ["Drivers", "The forces that decide your round, mapped by impact and uncertainty."],
  ["Four futures", "A scenario matrix from the two most uncertain, high-impact drivers."],
  ["Your odds", "Chance your round closes, summed across the futures."],
  ["Committee", "Three AI partners debate and shortlist real leads from Cala."],
];

onMounted(loadHealth);
</script>

<template>
  <header class="top">
    <button type="button" class="brand" @click="store.editing = !store.running">
      <span class="logo" aria-hidden="true">🦄</span>
      <span><b>Unicorn Oracle</b><small>Fundraising foresight on Cala data</small></span>
    </button>
    <div v-if="store.modes" class="modes">
      <span :class="['badge', store.modes.dataMode]"><i class="dot-live" />{{ store.modes.dataMode === "cala" ? "Cala live" : "Demo data" }}</span>
      <span :class="['badge', store.modes.analysisMode]">{{ { openai: "OpenAI", gemini: "Gemini", demo: "Demo analysis" }[store.modes.analysisMode] }}</span>
    </div>
  </header>

  <main v-if="!hasRun" class="landing">
    <section class="pitch">
      <p class="eyebrow">For founders raising their next round</p>
      <h1>Will your round close?<br /><span class="accent">Know before you pitch.</span></h1>
      <p class="lede">Unicorn Oracle reads live, sourced Cala data on your competitors, recent rounds and active investors, then forecasts your odds and tells you who to pitch first.</p>
      <ol class="how">
        <li v-for="([title, text], i) in howItWorks" :key="title"><span>{{ i + 1 }}</span><div><b>{{ title }}</b><p>{{ text }}</p></div></li>
      </ol>
      <button v-if="store.submitted" type="button" class="link" @click="store.editing = false">← Back to the {{ store.submitted.name }} report</button>
    </section>
    <StartupForm />
  </main>

  <main v-else class="report">
    <section class="startup-bar card">
      <div>
        <h1>{{ store.submitted.name }}</h1>
        <p class="muted small">{{ store.submitted.sector }} · {{ store.submitted.country }} · {{ store.submitted.stage }} ·
          {{ eur(store.submitted.targetAmountEur) }} in {{ store.submitted.horizonMonths }} months</p>
      </div>
      <button type="button" class="ghost" :disabled="store.running" @click="store.editing = true">New forecast</button>
    </section>

    <p v-if="store.dataMode === 'demo'" class="warn">Demo mode: no Cala key configured, so every company, investor and figure is fictional.</p>
    <p v-if="store.error" class="error-box" role="alert">{{ store.error }}</p>

    <ProgressPanel />

    <nav class="tabs" role="tablist">
      <button v-for="t in tabs" :key="t.id" type="button" role="tab" :aria-selected="store.tab === t.id"
        :class="['tab', { on: store.tab === t.id, wait: !t.ready }]" :disabled="!t.ready" @click="store.tab = t.id">
        {{ t.label }}<small v-if="t.count">{{ t.count }}</small><i v-if="!t.ready && store.running" class="mini-spin" />
      </button>
    </nav>

    <Transition name="fade" mode="out-in">
      <component :is="views[store.tab]" :key="store.tab" />
    </Transition>
  </main>

  <EvidenceDrawer />
</template>
