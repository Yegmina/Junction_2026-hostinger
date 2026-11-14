<script setup>
import { computed, ref } from "vue";
import { domainOf, investorKey, pct, store } from "../store.js";
import { copyText, introEmail } from "../share.js";
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
const ticket = computed(() => (v.value?.ticket && v.value.ticket.match !== "unknown" ? v.value.ticket : null));
const ticketIcon = { yes: "✓", partial: "≈", no: "✕", unknown: "?" };
const web = computed(() => props.target.web);
const news = computed(() => (web.value?.news || []).slice(0, 1));
const audit = computed(() => props.target.audit);
const auditLabel = { supported: "✓ Supported", weak: "≈ Weak evidence", contradicted: "✕ Contradicted" };
const logoOk = ref(true);
const seen = computed(() => store.history?.investors?.[investorKey(props.target.name)] || null);
const seenAudit = computed(() => {
  const s = seen.value;
  if (!s) return "";
  return [["supported", s.supported], ["weak", s.weak], ["contradicted", s.contradicted]]
    .filter(([, n]) => n).map(([label, n]) => `${n} ${label}`).join(", ");
});
const intros = computed(() => (v.value?.introPaths || []).slice(0, props.compact ? 1 : 3));

const showEmail = ref(false);
const copied = ref(false);
const email = computed(() => introEmail(props.target));
async function copyEmail() {
  copied.value = await copyText(`Subject: ${email.value.subject}\n\n${email.value.body}`);
  setTimeout(() => (copied.value = false), 1800);
}
</script>

<template>
  <article :class="['inv', { compact, conflict: hardConflicts.length }]">
    <span v-if="rank" class="rank">#{{ rank }}</span>
    <div class="inv-body">
      <div class="inv-top">
        <span class="inv-name">
          <img v-if="web?.logo && logoOk" :src="web.logo" alt="" class="inv-logo" referrerpolicy="no-referrer" @error="logoOk = false" />
          <b>{{ target.name }}</b>
          <a v-if="web?.website" :href="web.website" target="_blank" rel="noopener" class="small site-link">{{ domainOf(web.website) }} ↗</a>
        </span>
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
      <p v-if="ticket" :class="['ticket', ticket.match]" :title="`${ticket.rounds} rounds in the Cala graph`">
        <span class="ticon">{{ ticketIcon[ticket.match] }}</span>{{ ticket.text }}
      </p>
      <p v-if="audit" :class="['audit', audit.verdict]">
        <span class="audit-tag">Nemotron audit: {{ auditLabel[audit.verdict] }}</span>
        {{ audit.reason }} <CiteChips v-if="!compact" :ids="audit.evidence" />
      </p>
      <p class="why">{{ target.why }}</p>
      <p v-if="seen && !compact" class="seen small">
        <span class="muted">Seen before</span> Shortlisted in {{ seen.reports }} other founder{{ seen.reports === 1 ? "'s report" : "s' reports" }}
        <template v-if="seen.sectors.length"> ({{ seen.sectors.join(", ") }})</template><template v-if="seenAudit">; Nemotron rated it {{ seenAudit }}</template>.
        <span class="muted">Last {{ seen.lastSeen }}.</span>
      </p>
      <p v-if="!compact && web?.focus" class="webline">
        <span class="muted small">Their stated focus</span> “{{ web.focus }}”
        <CiteChips :ids="[web.focusEvidenceId].filter(Boolean)" />
      </p>
      <p v-for="n in news" :key="n.url" class="webline">
        <span class="muted small">Latest on the web</span>
        <a :href="n.url" target="_blank" rel="noopener">{{ n.title }}</a>
        <small class="muted"> · {{ domainOf(n.url) }}</small>
        <template v-if="!compact"><br />“{{ n.snippet }}” <CiteChips :ids="[n.evidenceId].filter(Boolean)" /></template>
      </p>
      <div v-if="intros.length" class="intros">
        <span class="muted small">Warm intro via</span>
        <span v-for="x in intros" :key="x.person" class="intro">
          <b>{{ x.person }}</b>, {{ x.role }} of {{ x.company }}
        </span>
        <small class="muted">(portfolio company, Cala graph)</small>
      </div>
      <p v-if="portfolio.length" class="portfolio">
        <span class="muted small">Portfolio:</span>
        <span v-for="p in portfolio" :key="p" class="pchip">{{ p }}</span>
        <span v-if="more" class="muted small">{{ more }}</span>
      </p>
      <CiteChips :ids="compact ? target.evidence.slice(0, 3) : target.evidence" />
      <template v-if="!compact && v">
        <button type="button" class="link email-toggle" @click="showEmail = !showEmail">
          {{ showEmail ? "Hide draft" : intros.length ? "✉ Draft intro request" : "✉ Draft cold email" }}</button>
        <Transition name="fold">
          <div v-if="showEmail" class="email">
            <p class="small"><span class="muted">To:</span> {{ email.to }}<br /><span class="muted">Subject:</span> {{ email.subject }}</p>
            <pre>{{ email.body }}</pre>
            <button type="button" class="ghost small-btn" @click="copyEmail">{{ copied ? "Copied ✓" : "Copy email" }}</button>
          </div>
        </Transition>
      </template>
    </div>
  </article>
</template>
