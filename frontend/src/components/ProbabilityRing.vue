<script setup>
import { computed } from "vue";
import { useCountUp } from "../countUp.js";

const props = defineProps({ value: { type: Number, default: 0 }, low: Number, high: Number, size: { type: Number, default: 180 } });
const shown = useCountUp(() => props.value);
const r = 70;
const c = 2 * Math.PI * r;
const arc = (v) => `${Math.max(0, Math.min(1, v)) * c} ${c}`;
const tone = computed(() => (props.value >= 0.5 ? "good" : props.value >= 0.25 ? "mid" : "low"));
</script>

<template>
  <svg :width="size" :height="size" viewBox="0 0 180 180" :class="['ring', tone]" role="img"
    :aria-label="`Probability ${Math.round(value * 100)} percent`">
    <circle cx="90" cy="90" :r="r" class="track" />
    <circle v-if="high != null" cx="90" cy="90" :r="r" class="band" :stroke-dasharray="arc(high)" transform="rotate(-90 90 90)" />
    <circle cx="90" cy="90" :r="r" class="value" :stroke-dasharray="arc(shown)" transform="rotate(-90 90 90)" />
    <text x="90" y="92" class="num">{{ Math.round(shown * 100) }}%</text>
    <text x="90" y="118" class="cap">chance</text>
  </svg>
</template>
