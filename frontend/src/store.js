import { computed, reactive } from "vue";
import { analyze, examples, getRun, health } from "./api.js";

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
  web: "Live web",
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
  runId: "",
  usage: null,
  savedAt: "",
  needCode: false,
  accessCode: readCode(),
});

const CODE_KEY = "unicorn-oracle-access-code";

function readCode() {
  try {
    return localStorage.getItem(CODE_KEY) || "";
  } catch {
    return "";
  }
}

export function saveAccessCode(code) {
  store.accessCode = code.trim();
  store.needCode = false;
  try {
    localStorage.setItem(CODE_KEY, store.accessCode);
  } catch {
    /* private mode: the code lives for this tab only */
  }
}

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
    runId: "",
    usage: null,
    savedAt: "",
  });
}

export const reportUrl = (runId) => `${location.origin}/r/${runId}`;

function setPath(path) {
  if (location.pathname !== path) history.pushState(null, "", path);
}

function onEvent(event) {
  switch (event.type) {
    case "start":
      store.runId = event.runId || "";
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
    case "usage":
      store.usage = event.usage;
      break;
    case "done":
      store.finishedAt = Date.now();
      store.runId = event.runId || store.runId;
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
  setPath("/");
  try {
    await analyze(store.submitted, onEvent, controller.signal, store.accessCode);
    // A finished report gets its own address, so the URL bar is the share link.
    if (store.finishedAt && store.runId && !store.error) setPath(`/r/${store.runId}`);
  } catch (exc) {
    if (exc.name === "AbortError") return;
    if (exc.detail === "access_code_required") {
      store.needCode = true;
      store.editing = true;
      store.error = store.accessCode ? "That access code was not accepted." : "";
    } else {
      store.error = exc.message;
    }
  } finally {
    store.running = false;
    store.finishedAt ||= Date.now();
    store.steps.forEach((s) => s.state === "running" && (s.state = "failed"));
    clearInterval(ticker);
  }
}

// Open a saved report (/r/<runId>) by applying its recorded events at once.
export async function loadReport(runId) {
  reset();
  store.editing = false;
  store.running = true;
  try {
    const run = await getRun(runId);
    store.submitted = run.profile;
    store.profile = { ...run.profile };
    run.events.forEach(onEvent);
    store.savedAt = run.savedAt || "";
    const seconds = run.events.find((e) => e.type === "done")?.seconds
      ?? run.events.find((e) => e.type === "start")?.replay?.originalSeconds;
    store.startedAt = Date.now() - (seconds || 0) * 1000;
    store.finishedAt = store.now = Date.now();
    store.runId = runId;
  } catch (exc) {
    store.submitted = null;
    store.editing = true;
    store.error = exc.message;
  } finally {
    store.running = false;
  }
}

export function newForecast() {
  store.editing = true;
  setPath("/");
}

export function cancelAnalysis() {
  controller?.abort();
}

export async function loadHealth() {
  try {
    store.modes = await health();
    if (store.modes.accessCodeRequired && !store.accessCode) store.needCode = true;
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
