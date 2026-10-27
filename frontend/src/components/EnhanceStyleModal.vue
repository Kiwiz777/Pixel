<script setup>
/**
 * AI Enhance style picker (Admin -> Photobooth -> "Style cards").
 *
 * Big tappable cards instead of a prompt box: the guest picks a look and we
 * emit its `index`. The prompt behind each card never reaches the browser -
 * /api/photobooth/enhance resolves it from the index.
 */
import { computed, onMounted, onBeforeUnmount } from 'vue'
import StyleCard from './StyleCard.vue'

const props = defineProps({
  cards: { type: Array, required: true }, // public cards: { index, title, description, emoji, color, image }
})
const emit = defineEmits(['pick', 'close'])

// Flat rows: two columns up to 6 cards, three (and compact) beyond that, so
// even 12 cards fit on screen without scrolling.
const compact = computed(() => props.cards.length > 6)
const gridClass = computed(() => (compact.value ? 'sm:grid-cols-2 lg:grid-cols-3' : 'sm:grid-cols-2'))

function onKey(e) {
  if (e.key === 'Escape') emit('close')
}
onMounted(() => window.addEventListener('keydown', onKey))
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))
</script>

<template>
  <div class="fixed inset-0 z-[55] grid place-items-center p-4" role="dialog" aria-modal="true" aria-labelledby="style-title">
    <div class="absolute inset-0 bg-ink-950/80 backdrop-blur-md" @click="emit('close')"></div>

    <div class="picker relative w-full max-h-[94dvh] overflow-y-auto p-2"
      :class="compact ? 'max-w-5xl' : 'max-w-3xl'">
      <div class="text-center mb-5">
        <h2 id="style-title" class="font-display text-3xl font-semibold">Pick your style</h2>
        <p class="text-slate-300 mt-1">Tap a card and we'll transform your photo.</p>
      </div>

      <div class="grid grid-cols-1 gap-3" :class="gridClass">
        <button
          v-for="(card, i) in cards"
          :key="card.index"
          type="button"
          class="tile rounded-2xl focus:outline-none focus-visible:ring-4 focus-visible:ring-electric-400"
          :style="{ animationDelay: `${i * 60}ms` }"
          @click="emit('pick', card)"
        >
          <StyleCard :card="card" :compact="compact" />
        </button>
      </div>

      <div class="flex justify-center mt-5">
        <button class="btn-ghost text-lg px-7" @click="emit('close')">Not now</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.picker { animation: pop 0.28s cubic-bezier(0.16, 1, 0.3, 1); }
.tile {
  animation: rise 0.42s cubic-bezier(0.16, 1, 0.3, 1) both;
  transition: transform 0.18s cubic-bezier(0.16, 1, 0.3, 1);
}
.tile:hover { transform: translateY(-3px); }
.tile:active { transform: scale(0.97); }
@keyframes pop {
  from { opacity: 0; transform: scale(0.96); }
  to { opacity: 1; transform: scale(1); }
}
@keyframes rise {
  from { opacity: 0; transform: translateY(14px); }
  to { opacity: 1; transform: translateY(0); }
}
@media (prefers-reduced-motion: reduce) {
  .picker, .tile { animation: none; }
  .tile:hover { transform: none; }
}
</style>
