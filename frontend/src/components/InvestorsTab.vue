<script setup>
import { ref } from "vue";
import { pct, store } from "../store.js";
import CiteChips from "./CiteChips.vue";
import CompetitorBackers from "./CompetitorBackers.vue";
import InvestorCard from "./InvestorCard.vue";
import Skeleton from "./Skeleton.vue";

const openMember = ref("");
const stanceLabel = { back: "Would back", conditional: "Conditional", pass: "Would pass" };
const initials = (p) => p.split(" ").slice(0, 2).map((w) => w[0]).join("");
</script>

<template>
  <div class="investors">
    <section class="card">
      <h3>Investment committee</h3>
      <p class="muted small">Three AI partners argue your case using only Cala evidence.</p>
      <div v-if="store.committee" class="members">
        <article v-for="m in store.committee.members" :key="m.persona" :class="['member', m.stance]">
          <header>
            <span class="avatar">{{ initials(m.persona) }}</span>
            <div><b>{{ m.persona }}</b><span :class="['stance-tag', m.stance]">{{ stanceLabel[m.stance] }}</span></div>
          </header>
          <p class="headline">“{{ m.headline || m.argument }}”</p>
          <button type="button" class="link" @click="openMember = openMember === m.persona ? '' : m.persona">
            {{ openMember === m.persona ? "Hide argument" : "Read argument" }}</button>
          <Transition name="fold">
            <div v-if="openMember === m.persona" class="argument"><p>{{ m.argument }}</p><CiteChips :ids="m.evidence" /></div>
          </Transition>
        </article>
      </div>
      <Skeleton v-else :lines="3" />
      <p v-if="store.committee" class="consensus"><b>Consensus:</b> {{ store.committee.consensus }}</p>
    </section>

    <section class="card">
      <h3>Lead investors to approach</h3>
      <p class="muted small">Only investors named in Cala evidence. Each is checked in the Cala graph for its portfolio, recent deals and conflicts with your competitors.</p>
      <TransitionGroup v-if="store.committee" tag="ol" name="list" class="leads">
        <li v-for="(t, i) in store.committee.investorTargets" :key="t.name">
          <InvestorCard :target="t" :rank="i + 1" />
        </li>
      </TransitionGroup>
      <Skeleton v-else :lines="3" />
      <p v-if="store.committee && !store.committee.investorTargets.length" class="muted">No investor in the evidence matched well enough.</p>
    </section>

    <CompetitorBackers />
  </div>
</template>
