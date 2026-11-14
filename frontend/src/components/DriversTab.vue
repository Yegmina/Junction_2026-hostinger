<script setup>
import { computed, ref } from "vue";
import { pct, store } from "../store.js";
import CiteChips from "./CiteChips.vue";

const open = ref("");
const hover = ref("");
const drivers = computed(() =>
  [...(store.plan?.drivers || [])].sort((a, b) => b.impact * b.uncertainty - a.impact * a.uncertainty),
);
const W = 320, H = 220, P = 28;
const x = (v) => P + v * (W - 2 * P);
const y = (v) => H - P - v * (H - 2 * P);
// Spread dots that would overlap so every number stays readable.
const points = computed(() => {
  const placed = [];
  for (const d of drivers.value) {
    let px = x(d.impact), py = y(d.uncertainty);
    for (let tries = 0; tries < 12 && placed.some((p) => Math.hypot(p.px - px, p.py - py) < 22); tries++) {
      const angle = tries * 2.4;
      px = x(d.impact) + Math.cos(angle) * 14 * (1 + tries / 4);
      py = y(d.uncertainty) + Math.sin(angle) * 14 * (1 + tries / 4);
    }
    placed.push({ d, px: Math.min(W - 12, Math.max(P, px)), py: Math.min(H - P, Math.max(12, py)) });
  }
  return placed;
});
</script>

<template>
  <div v-if="store.plan" class="drivers-tab">
    <section class="card map-card">
      <h3>Driver map</h3>
      <p class="muted small">Top-right drivers matter most and are least predictable. They form the scenario axes.</p>
      <svg :viewBox="`0 0 ${W} ${H}`" class="driver-map" role="img" aria-label="Drivers by impact and uncertainty">
        <rect :x="x(0.5)" :y="y(1)" :width="x(1) - x(0.5)" :height="y(0.5) - y(1)" class="hot" />
        <line :x1="P" :y1="H - P" :x2="W - P" :y2="H - P" class="axis" />
        <line :x1="P" :y1="P" :x2="P" :y2="H - P" class="axis" />
        <text :x="W / 2" :y="H - 6" class="axis-label">Impact →</text>
        <text :x="10" :y="H / 2" class="axis-label" :transform="`rotate(-90 10 ${H / 2})`">Uncertainty →</text>
        <g v-for="({ d, px, py }, i) in points" :key="d.id" :class="['dot', d.direction, { on: hover === d.id || open === d.id }]"
          @mouseenter="hover = d.id" @mouseleave="hover = ''" @click="open = open === d.id ? '' : d.id">
          <title>{{ d.name }}</title>
          <circle :cx="px" :cy="py" r="11" />
          <text :x="px" :y="py + 4">{{ i + 1 }}</text>
        </g>
      </svg>
      <p class="legend small"><span class="lg tailwind" />tailwind <span class="lg headwind" />headwind <span class="lg mixed" />mixed</p>
    </section>

    <section class="card">
      <h3>What decides your round</h3>
      <ul class="driver-list">
        <li v-for="(d, i) in drivers" :key="d.id" :class="{ on: hover === d.id, open: open === d.id }"
          @mouseenter="hover = d.id" @mouseleave="hover = ''">
          <button type="button" class="driver-row" :aria-expanded="open === d.id" @click="open = open === d.id ? '' : d.id">
            <span :class="['num', d.direction]">{{ i + 1 }}</span>
            <span class="dname">{{ d.name }}</span>
            <span :class="['pestel', d.pestel]">{{ d.pestel }}</span>
            <span :class="['dir', d.direction]">{{ d.direction }}</span>
          </button>
          <Transition name="fold">
            <div v-if="open === d.id" class="driver-more">
              <p>{{ d.description }}</p>
              <p class="muted small">Impact {{ pct(d.impact) }} · Uncertainty {{ pct(d.uncertainty) }}</p>
              <CiteChips :ids="d.evidence" />
            </div>
          </Transition>
        </li>
      </ul>
    </section>
  </div>
</template>
