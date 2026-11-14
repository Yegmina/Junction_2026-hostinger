import { computed, reactive } from "vue";
import { analyze, examples, health } from "./api.js";

// Fallback examples; the backend list (with cached replays) replaces these on load.
export const EXAMPLES = [
  {
    label: "CSRD reporting SaaS",
    profile: {
      name: "Ledgerly",
      description: "AI assistant that automates EU sustainability (CSRD) reporting for small and mid-sized companies",
      sector: "climate tech software",
      country: "Finland",
      stage: "seed",
      targetAmountEur: 2500000,
      horizonMonths: 12,
    },
  },
  {
    label: "Defence drones",
    profile: {
      name: "AeroRozum",
      description: "Autonomous drones for border surveillance and defence logistics",
      sector: "defence tech",
      country: "Finland",
      stage: "seed",
      targetAmountEur: 3000000,
      horizonMonths: 12,
    },
  },
  {
    label: "SME lending fintech",
    profile: {
      name: "Kassavirta",
      description: "Embedded working-capital loans for Nordic SMEs, underwritten from accounting data",
      sector: "fintech",
      country: "Sweden",
      stage: "series-a",
      targetAmountEur: 8000000,
      horizonMonths: 12,
    },
  },
];

export const KIND_LABELS = {
  competitor: "Competitors",
  funding: "Funding rounds",
  investor: "Investors",
  market: "Company list",
  graph: "Cala graph",
};

export const store = reactive({
  modes: null,
  examples: EXAMPLES,
  replay: null,
  graph: [],
  profile: { ...EXAMPLES[0].profile, name: "", description: "", sector: "" },
  submitted: null,
  running: false,
  error: "",
  question: "",
  dataMode: "",
  steps: [],
  evidence: [],
  evidenceErrors: [],
  plan: null,
  committee: null,
  startedAt: 0,
  finishedAt: 0,
  now: Date.now(),
  tab: "overview",
  openEvidenceId: "",
  editing: true,
});

let controller = null;
let ticker = null;

export const derived = reactive({
  evidenceById: computed(() => Object.fromEntries(store.evidence.map((e) => [e.id, e]))),
  scenarioById: computed(() => Object.fromEntries((store.plan?.scenarios || []).map((s) => [s.id, s]))),
  elapsed: computed(() => ((store.finishedAt || store.now) - store.startedAt) / 1000),
  doneSteps: computed(() => store.steps.filter((s) => s.state === "done" || s.state === "failed").length),
  sourceCount: computed(() => {
    const keys = new Set();
    store.evidence.forEach((e) => e.sources.forEach((s) => keys.add(domainOf(s.url) || s.name)));
    return keys.size;
  }),
  mostLikely: computed(() =>
    store.plan ? [...store.plan.scenarios].sort((a, b) => b.probability - a.probability)[0] : null,
  ),
});

export function domainOf(url) {
  try {
    return url ? new URL(url).hostname.replace(/^www\./, "") : "";
  } catch {
    return "";
  }
}

// Cala text arrives as whitespace-collapsed markdown; restore readable line breaks.
export function cleanText(text) {
  return String(text || "")
    .replace(/\*\*/g, "")
    .replace(/\s*#{1,4}\s+/g, "\n\n")
    .replace(/\s+-\s+(?=\S)/g, "\n• ")
    .replace(/\s*\|\s*---[\s|-]*/g, "\n")
    .trim();
}

export const pct = (v) => `${Math.round((v || 0) * 100)}%`;
export const eur = (v) =>
  v >= 1e6 ? `€${(v / 1e6).toFixed(v % 1e6 ? 1 : 0)}M` : v >= 1e3 ? `€${Math.round(v / 1e3)}k` : `€${v}`;
export const clock = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

export function openEvidence(id) {
  store.openEvidenceId = id;
}

function reset() {
  Object.assign(store, {
    error: "",
    question: "",
    steps: [],
    evidence: [],
    evidenceErrors: [],
    plan: null,
    committee: null,
    replay: null,
    graph: [],
    finishedAt: 0,
    tab: "overview",
    openEvidenceId: "",
  });
}

function onEvent(event) {
  switch (event.type) {
    case "start":
      store.question = event.question;
      store.dataMode = event.dataMode;
      store.replay = event.replay || null;
      break;
    case "graph":
      store.graph = event.competitors || [];
      break;
    case "steps":
      store.steps = event.steps.map((s) => ({ ...s, state: "pending", detail: "", seconds: null, startedAt: null }));
      break;
    case "step": {
      const step = store.steps.find((s) => s.id === event.id);
      if (!step) break;
      if (event.state === "running" && !step.startedAt) step.startedAt = Date.now();
      step.state = event.state;
      if (event.detail) step.detail = event.detail;
      if (event.seconds != null) step.seconds = event.seconds;
      break;
    }
    case "evidence":
      store.evidence = event.evidence;
      store.evidenceErrors = event.errors || [];
      store.dataMode = event.mode;
      break;
    case "plan":
      store.plan = event.plan;
      break;
    case "committee":
      store.committee = event.committee;
      break;
    case "done":
      store.finishedAt = Date.now();
      break;
    case "error":
      store.error = event.message;
      break;
  }
}

export async function runAnalysis() {
  controller?.abort();
  controller = new AbortController();
  reset();
  store.submitted = { ...store.profile };
  store.editing = false;
  store.running = true;
  store.startedAt = store.now = Date.now();
  clearInterval(ticker);
  ticker = setInterval(() => (store.now = Date.now()), 250);
  try {
    await analyze(store.submitted, onEvent, controller.signal);
  } catch (exc) {
    if (exc.name !== "AbortError") store.error = exc.message;
  } finally {
    store.running = false;
    store.finishedAt ||= Date.now();
    store.steps.forEach((s) => s.state === "running" && (s.state = "failed"));
    clearInterval(ticker);
  }
}

export function cancelAnalysis() {
  controller?.abort();
}

export async function loadHealth() {
  try {
    store.modes = await health();
  } catch {
    store.modes = null;
  }
  try {
    const list = (await examples()).examples;
    if (list?.length) store.examples = list;
  } catch {
    /* keep fallback examples */
  }
}
