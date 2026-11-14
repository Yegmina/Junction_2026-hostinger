<script setup>
import { computed } from "vue";
import { pct } from "../store.js";
import CiteChips from "./CiteChips.vue";

const props = defineProps({ target: { type: Object, required: true }, rank: Number, compact: Boolean });
const v = computed(() => props.target.verification);
const portfolio = computed(() => (v.value?.portfolio || []).slice(0, props.compact ? 3 : 8));
const more = computed(() => {
  const count = v.value?.portfolioCount || 0;
  if (v.value?.portfolioCapped) return `${count}+ companies in total`;
  const rest = count - portfolio.value.length;
  return rest > 0 ? `+${rest} more` : "";
});
const hardConflicts = computed(() => (v.value?.conflicts || []).filter((c) => c.basis === "graph"));
const softConflicts = computed(() => (v.value?.conflicts || []).filter((c) => c.basis !== "graph"));
const activity = computed(() => {
  if (!v.value?.verified) return "";
  const parts = [];
  if (v.value.recentDeals) parts.push(`${v.value.recentDeals} deals in the last 2 years`);
  if (v.value.latestDeal) parts.push(`latest ${v.value.latestDeal}`);
  return parts.join(" · ");
});
</script>

<template>
  <article :class="['inv', { compact, conflict: hardConflicts.length }]">
    <span v-if="rank" class="rank">#{{ rank }}</span>
    <div class="inv-body">
      <div class="inv-top">
        <b>{{ target.name }}</b>
        <span class="fit">{{ pct(target.fitScore) }} fit</span>
      </div>
      <div class="fitbar"><span :style="{ width: pct(target.fitScore) }" /></div>
      <p class="badges">
        <span v-if="!v" class="vbadge pending">Checking Cala graph…</span>
        <span v-else-if="v.verified" class="vbadge ok" :title="v.entityName">✓ Verified in Cala graph</span>
        <span v-else class="vbadge none">Not found in Cala graph</span>
        <span v-if="activity" class="activity">{{ activity }}</span>
      </p>
      <p v-for="c in hardConflicts" :key="c.company" class="conflict-line">
        ⚠ Backs your competitor <b>{{ c.company }}</b> <small>(INVESTED_IN in Cala graph)</small>
      </p>
      <p v-if="softConflicts.length" class="soft-conflict">
        Possible link to {{ softConflicts.map((c) => c.company).join(", ") }}: named together in
        <CiteChips :ids="[...new Set(softConflicts.map((c) => c.evidence).filter(Boolean))]" />. Check before pitching.
      </p>
      <p class="why">{{ target.why }}</p>
      <p v-if="portfolio.length" class="portfolio">
        <span class="muted small">Portfolio:</span>
        <span v-for="p in portfolio" :key="p" class="pchip">{{ p }}</span>
        <span v-if="more" class="muted small">{{ more }}</span>
      </p>
      <CiteChips :ids="compact ? target.evidence.slice(0, 3) : target.evidence" />
    </div>
  </article>
</template>
