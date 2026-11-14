import { eur, pct, reportUrl, store } from "./store.js";

const STAGE = { "pre-seed": "pre-seed", seed: "seed", "series-a": "Series A", "series-b": "Series B", growth: "growth" };

export async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    // Clipboard API needs a secure context; fall back to a hidden textarea.
    const area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    const ok = document.execCommand("copy");
    area.remove();
    return ok;
  }
}

function sourceLine(id) {
  const fact = store.evidence.find((e) => e.id === id);
  const src = fact?.sources.find((s) => s.url) || fact?.sources[0];
  return src ? `${src.name}${src.url ? ` <${src.url}>` : ""}` : "";
}

// Markdown shortlist a founder can paste into Notion, a doc or an email to co-founders.
export function investorListMarkdown() {
  const p = store.submitted;
  const lines = [`# Lead investors for ${p.name}`, "",
    `${eur(p.targetAmountEur)} ${STAGE[p.stage] || p.stage} · ${p.sector} · ${p.country}` +
      (store.plan ? ` · ${pct(store.plan.event.probability)} chance to close in ${p.horizonMonths} months` : ""), ""];
  (store.committee?.investorTargets || []).forEach((t, i) => {
    const v = t.verification;
    lines.push(`${i + 1}. **${t.name}** (${pct(t.fitScore)} fit)${v?.verified ? " ✓ verified in Cala graph" : ""}`);
    lines.push(`   - Why: ${t.why}`);
    if (v?.ticket && v.ticket.match !== "unknown") lines.push(`   - Rounds: ${v.ticket.text}`);
    if (v?.introPaths?.length)
      lines.push(`   - Warm intro: ${v.introPaths.map((x) => `${x.person} (${x.role}, ${x.company})`).join("; ")}`);
    const hard = (v?.conflicts || []).filter((c) => c.basis === "graph");
    if (hard.length) lines.push(`   - ⚠ Backs competitor: ${hard.map((c) => c.company).join(", ")}`);
    const src = t.evidence.map(sourceLine).filter(Boolean);
    if (src.length) lines.push(`   - Sources: ${[...new Set(src)].slice(0, 3).join("; ")}`);
  });
  if (store.runId) lines.push("", `Full report: ${reportUrl(store.runId)}`);
  return lines.join("\n");
}

// Deterministic draft: built only from the profile and Cala facts on the card, nothing invented.
export function introEmail(target) {
  const p = store.submitted;
  const v = target.verification || {};
  const firm = v.entityName || target.name;
  const path = v.introPaths?.[0];
  const ask = `${eur(p.targetAmountEur)} ${STAGE[p.stage] || p.stage} round`;
  const pitch = p.description.replace(/\.$/, "");
  const portfolio = (v.portfolio || []).filter((c) => c !== path?.company).slice(0, 2);
  if (path) {
    const first = path.person.split(" ")[0];
    return {
      to: `${path.person} (${path.role}, ${path.company})`,
      subject: `Intro to ${firm}? ${p.name} is raising a ${ask}`,
      body: [
        `Hi ${first},`,
        "",
        `I'm building ${p.name} in ${p.country}: ${pitch}.`,
        `We're raising a ${ask} and ${firm} looks like a strong fit: ${target.why.replace(/\.$/, "")}.`,
        `Since ${firm} backed ${path.company}, would you be open to a short intro to the partner you worked with?`,
        "",
        "Happy to send a forwardable blurb and our deck.",
        "",
        "Thanks,",
        "[Your name]",
      ].join("\n"),
    };
  }
  return {
    to: `${firm} (partner covering ${p.sector})`,
    subject: `${p.name}: ${ask} in ${p.sector}`,
    body: [
      "Hi [Partner name],",
      "",
      `I'm the founder of ${p.name} in ${p.country}: ${pitch}.`,
      `We're raising a ${ask}. ${target.why.replace(/\.$/, "")}.`,
      portfolio.length ? `Given your work with ${portfolio.join(" and ")}, I think we'd be a natural addition to the portfolio.` : "",
      "",
      "Could we find 20 minutes in the next two weeks? Deck attached.",
      "",
      "Best,",
      "[Your name]",
    ].filter((l, i, a) => l !== "" || a[i - 1] !== "").join("\n"),
  };
}
