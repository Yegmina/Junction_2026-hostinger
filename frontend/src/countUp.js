import { onBeforeUnmount, ref, watch } from "vue";

// Animates a number towards the latest value of `source()`.
export function useCountUp(source, duration = 900) {
  const value = ref(0);
  let frame = 0;
  const reduce = typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
  watch(
    source,
    (target) => {
      cancelAnimationFrame(frame);
      const from = value.value;
      const to = Number(target) || 0;
      if (reduce) {
        value.value = to;
        return;
      }
      const start = performance.now();
      const step = (t) => {
        const k = Math.min(1, (t - start) / duration);
        value.value = from + (to - from) * (1 - Math.pow(1 - k, 3));
        if (k < 1) frame = requestAnimationFrame(step);
      };
      frame = requestAnimationFrame(step);
    },
    { immediate: true },
  );
  onBeforeUnmount(() => cancelAnimationFrame(frame));
  return value;
}
