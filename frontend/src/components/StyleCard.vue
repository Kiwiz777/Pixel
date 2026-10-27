<script setup>
/**
 * One AI Enhance style card - a flat row: emoji (or the card's artwork as a
 * thumbnail) on the left, title + description on the right, tinted by the
 * card's accent colour. Shared by the kiosk picker and the Admin preview so
 * both look identical. Short on purpose so a full set fits without scrolling.
 */
import { computed } from 'vue'

const props = defineProps({
  card: { type: Object, required: true }, // { title, description, emoji, color, image }
  compact: { type: Boolean, default: false },
})

const accent = computed(() => (/^#[0-9a-f]{6}$/i.test(props.card.color || '') ? props.card.color : '#F97316'))
const imageUrl = computed(() => (props.card.image ? `/media/styles/${props.card.image}` : ''))
</script>

<template>
  <div
    class="style-card relative flex items-center overflow-hidden rounded-2xl border border-white/10 text-left"
    :class="compact ? 'gap-3 p-3 min-h-[4.5rem]' : 'gap-4 p-4 min-h-[5.5rem]'"
    :style="{ '--accent': accent }"
  >
    <div
      class="tile shrink-0 grid place-items-center overflow-hidden rounded-xl"
      :class="compact ? 'h-12 w-12' : 'h-16 w-16'"
    >
      <img v-if="imageUrl" :src="imageUrl" alt="" class="h-full w-full object-cover" />
      <span
        v-else
        class="leading-none"
        :class="compact ? 'text-2xl' : 'text-3xl'"
        aria-hidden="true"
      >{{ card.emoji || '✨' }}</span>
    </div>
    <div class="min-w-0">
      <h3
        class="font-display font-semibold text-white leading-tight truncate"
        :class="compact ? 'text-base' : 'text-xl'"
      >{{ card.title || 'Untitled style' }}</h3>
      <p
        v-if="card.description"
        class="text-slate-300 mt-0.5 line-clamp-2"
        :class="compact ? 'text-xs' : 'text-sm'"
      >{{ card.description }}</p>
    </div>
  </div>
</template>

<style scoped>
.style-card {
  background:
    linear-gradient(90deg, color-mix(in srgb, var(--accent) 22%, transparent), transparent 70%),
    rgb(15 22 41 / 0.85);
  border-left: 3px solid var(--accent);
}
.tile {
  background: color-mix(in srgb, var(--accent) 28%, #0b1020);
  box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--accent) 45%, transparent);
}
</style>
