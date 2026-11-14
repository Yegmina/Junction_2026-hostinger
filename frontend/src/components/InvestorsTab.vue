<script setup>
import { ref } from "vue";
import { pct, store } from "../store.js";
import CiteChips from "./CiteChips.vue";
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
      <p class="muted small">Only investors that appear in Cala evidence are shown, ranked by fit.</p>
      <TransitionGroup v-if="store.committee" tag="ol" name="list" class="leads">
        <li v-for="(t, i) in store.committee.investorTargets" :key="t.name" class="lead">
          <span class="rank">#{{ i + 1 }}</span>
          <div class="lead-body">
            <div class="lead-top"><b>{{ t.name }}</b><span class="fit">{{ pct(t.fitScore) }} fit</span></div>
            <div class="fitbar"><span :style="{ width: pct(t.fitScore) }" /></div>
            <p>{{ t.why }}</p>
            <CiteChips :ids="t.evidence" />
          </div>
        </li>
      </TransitionGroup>
      <Skeleton v-else :lines="3" />
      <p v-if="store.committee && !store.committee.investorTargets.length" class="muted">No investor in the evidence matched well enough.</p>
    </section>
  </div>
</template>
