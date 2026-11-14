<script setup>
import { computed, ref } from "vue";
import { eur, runAnalysis, saveAccessCode, store } from "../store.js";

const code = ref(store.accessCode);
function submit() {
  if (store.needCode && code.value.trim()) saveAccessCode(code.value);
  runAnalysis();
}

const stages = [
  ["pre-seed", "Pre-seed"],
  ["seed", "Seed"],
  ["series-a", "Series A"],
  ["series-b", "Series B"],
  ["growth", "Growth"],
];
const typical = { "pre-seed": [100e3, 1.5e6], seed: [500e3, 5e6], "series-a": [3e6, 20e6], "series-b": [10e6, 60e6], growth: [20e6, 500e6] };
const amountHint = computed(() => {
  const [lo, hi] = typical[store.profile.stage];
  const v = store.profile.targetAmountEur || 0;
  if (v && v < lo) return { warn: true, text: `${eur(v)} is small for ${store.profile.stage}; typical is ${eur(lo)}–${eur(hi)}.` };
  if (v > hi) return { warn: true, text: `${eur(v)} is large for ${store.profile.stage}; typical is ${eur(lo)}–${eur(hi)}.` };
  return { warn: false, text: v ? `${eur(v)} · typical ${store.profile.stage} is ${eur(lo)}–${eur(hi)}` : "" };
});

function useExample(example) {
  Object.assign(store.profile, example.profile);
}
const isExample = computed(() =>
  store.examples.some((e) => e.cached && Object.entries(e.profile).every(([k, v]) => store.profile[k] === v)),
);
</script>

<template>
  <form class="card form" @submit.prevent="submit">
    <div class="examples">
      <span class="muted small">Try an example:</span>
      <button v-for="ex in store.examples" :key="ex.label" type="button" class="chip" @click="useExample(ex)">{{ ex.label }}</button>
    </div>
    <label>Startup name<input v-model.trim="store.profile.name" required maxlength="120" placeholder="e.g. Ledgerly" /></label>
    <label>What you build
      <textarea v-model.trim="store.profile.description" required minlength="10" maxlength="1500" rows="3"
        placeholder="Product, customer and problem in one or two sentences" />
    </label>
    <div class="row">
      <label>Sector<input v-model.trim="store.profile.sector" required maxlength="80" placeholder="e.g. fintech" /></label>
      <label>Country or region<input v-model.trim="store.profile.country" required maxlength="60" /></label>
    </div>
    <fieldset class="stages">
      <legend>Stage</legend>
      <label v-for="[value, text] in stages" :key="value" :class="['seg', { on: store.profile.stage === value }]">
        <input v-model="store.profile.stage" type="radio" name="stage" :value="value" />{{ text }}
      </label>
    </fieldset>
    <div class="row">
      <label>Target round (EUR)
        <input v-model.number="store.profile.targetAmountEur" type="number" min="10000" step="10000" required />
      </label>
      <label>Close within (months)
        <input v-model.number="store.profile.horizonMonths" type="number" min="3" max="36" required />
      </label>
    </div>
    <p v-if="amountHint.text" :class="['hint', { warnText: amountHint.warn }]">{{ amountHint.text }}</p>
    <div v-if="store.needCode && !isExample" class="code-box">
      <label for="access-code"><b>Access code</b> <span class="muted small">Live runs on this server are invite-only. Examples stay open to everyone.</span></label>
      <input id="access-code" v-model="code" type="password" autocomplete="off" placeholder="Enter the code from the team" />
    </div>
    <p v-if="store.error && store.editing" class="error-box small" role="alert">{{ store.error }}</p>
    <button type="submit" class="primary big-btn" :disabled="store.running">Forecast my round</button>
    <p class="muted small center">{{ isExample ? "Example: replays a recorded live run in a few seconds." : "Live run takes about a minute. Every claim links to its Cala source." }}</p>
  </form>
</template>
