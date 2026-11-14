<script setup>
import { computed, ref } from "vue";
import { store } from "../store.js";

// Three columns: your startup -> competitors Cala found -> investors with INVESTED_IN edges into them.
// Shortlisted investors that back a competitor turn red; clean shortlisted leads hang off "You" in green.
const W = 760;
const ROW = 30;
const X = { you: 70, comp: 300, inv: 560 };
const MAX_BACKERS = 12;
const hover = ref("");

const key = (name) =>
  String(name || "").toLowerCase().replace(/\b(oy|oyj|ab|ltd|inc|llc|gmbh|as|a\/s)\b\.?/g, "").replace(/[^a-z0-9]+/g, " ").trim();
const clip = (s, n = 26) => (s.length > n ? `${s.slice(0, n - 1)}…` : s);

const shortlist = computed(() => {
  const map = new Map();
  for (const t of store.committee?.investorTargets || []) {
    map.set(key(t.name), t);
    if (t.verification?.entityName) map.set(key(t.verification.entityName), t);
  }
  return map;
});

const layout = computed(() => {
  const comps = store.graph.slice(0, 6);
  const counts = new Map();
  comps.forEach((c) => c.backers.forEach((b) => counts.set(b, (counts.get(b) || 0) + 1)));
  const backers = [...counts.keys()]
    .sort((a, b) => (shortlist.value.has(key(b)) - shortlist.value.has(key(a))) || counts.get(b) - counts.get(a))
    .slice(0, MAX_BACKERS);
  const backerKeys = new Set(backers.map(key));
  const clean = (store.committee?.investorTargets || [])
    .filter((t) => !backerKeys.has(key(t.name)) && !backerKeys.has(key(t.verification?.entityName)))
    .slice(0, 6);

  const right = [...backers.map((b) => ({ name: b, kind: shortlist.value.has(key(b)) ? "conflict" : "backer" })),
    ...clean.map((t) => ({ name: t.name, kind: "lead", gap: true }))];
  let y = 24;
  right.forEach((n, i) => {
    if (n.gap && (i === 0 || !right[i - 1].gap) && backers.length) y += 16;
    n.y = y;
    y += ROW;
  });
  const height = Math.max(y, comps.length * ROW + 40, 140) + (clean.length ? 24 : 0);
  const compStep = comps.length ? (height - 40) / comps.length : 0;
  const compNodes = comps.map((c, i) => ({ ...c, y: 20 + compStep * (i + 0.5) }));
  const you = { y: height / 2 };
  const byName = new Map(right.map((n) => [n.name, n]));
  const edges = [];
  compNodes.forEach((c) => {
    edges.push({ id: `y-${c.id}`, kind: "compete", from: [X.you, you.y], to: [X.comp, c.y], tags: [c.name] });
    c.backers.forEach((b) => {
      const n = byName.get(b);
      if (n) edges.push({ id: `${c.id}-${b}`, kind: n.kind, from: [X.comp, c.y], to: [X.inv, n.y], tags: [c.name, b] });
    });
  });
  right.filter((n) => n.kind === "lead").forEach((n) =>
    edges.push({ id: `lead-${n.name}`, kind: "lead", from: [X.you, you.y], to: [X.inv, n.y], tags: [n.name] }));
  const hidden = counts.size - backers.length;
  return { comps: compNodes, right, you, edges, height, hidden };
});

const curve = ({ kind, from: [x1, y1], to: [x2, y2] }) => {
  if (kind === "lead") {
    // Swing below the competitor column so clean-lead lines never cross its labels.
    const low = layout.value.height - 6;
    return `M${x1 + 8},${y1} C${x1 + 60},${low} ${X.comp},${low} ${x2 - 8},${y2}`;
  }
  const mid = (x1 + x2) / 2;
  return `M${x1 + 8},${y1} C${mid},${y1} ${mid},${y2} ${x2 - 8},${y2}`;
};
const dim = (tags) => hover.value && !tags.includes(hover.value);
</script>

<template>
  <section v-if="store.graph.length" class="card network">
    <header class="card-head">
      <h3>Your market in the Cala graph</h3>
      <span class="legend small">
        <span><span class="lg compete" />competes</span> <span><span class="lg backer" />INVESTED_IN</span>
        <span><span class="lg conflict" />shortlisted, backs a rival</span> <span><span class="lg lead" />clean lead</span>
      </span>
    </header>
    <div class="net-scroll">
      <svg :viewBox="`0 0 ${W} ${layout.height}`" role="img"
        :aria-label="`${store.submitted?.name} competes with ${layout.comps.length} companies; ${layout.right.length} investors shown`">
        <g class="edges">
          <path v-for="e in layout.edges" :key="e.id" :d="curve(e)" :class="['edge', e.kind, { dim: dim(e.tags) }]" />
        </g>
        <g class="node you" :transform="`translate(${X.you},${layout.you.y})`">
          <circle r="26" />
          <text text-anchor="middle" dy="4">{{ clip(store.submitted?.name || "You", 10) }}</text>
        </g>
        <g v-for="c in layout.comps" :key="c.id" :class="['node', 'comp', { dim: dim([c.name]) }]"
          :transform="`translate(${X.comp},${c.y})`" @mouseenter="hover = c.name" @mouseleave="hover = ''">
          <circle r="7" />
          <text x="-12" dy="4" text-anchor="end">{{ clip(c.name, 22) }}</text>
          <text x="12" dy="4" class="count">{{ c.backers.length || "" }}</text>
        </g>
        <g v-for="n in layout.right" :key="n.name" :class="['node', n.kind, { dim: dim([n.name]) }]"
          :transform="`translate(${X.inv},${n.y})`" @mouseenter="hover = n.name" @mouseleave="hover = ''">
          <circle r="6" />
          <text x="12" dy="4">{{ clip(n.name) }}{{ n.kind === "conflict" ? " ⚠" : n.kind === "lead" ? " ✓" : "" }}</text>
        </g>
      </svg>
    </div>
    <p class="muted small">Hover a company or investor to trace its links.
      <template v-if="layout.hidden"> {{ layout.hidden }} more backers not drawn.</template></p>
  </section>
</template>
