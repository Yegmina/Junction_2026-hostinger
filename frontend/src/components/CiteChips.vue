<script setup>
import { derived, openEvidence } from "../store.js";

defineProps({ ids: { type: Array, default: () => [] } });
</script>

<template>
  <span v-if="ids.length" class="cites">
    <button
      v-for="id in ids"
      :key="id"
      type="button"
      class="cite"
      :title="derived.evidenceById[id]?.title || id"
      @click.stop="openEvidence(id)"
    >
      {{ id }}
    </button>
  </span>
</template>
