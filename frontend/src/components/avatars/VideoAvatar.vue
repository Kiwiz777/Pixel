<script setup>
/**
 * Real-person avatar from video clips (Admin -> Avatar & Welcome -> Real
 * person). The clips are filmed or AI-generated; the voice is still TTS.
 *
 * One <video> per clip, stacked; only the active one plays (the Pi decodes one
 * stream, not five) and they crossfade on change. State -> clip:
 *   waving -> wave (once, then back), speaking -> talking,
 *   listening -> listening, thinking -> thinking, else idle.
 * A missing clip falls back to idle. Videos are muted - the voice is TTS.
 */
import { computed, nextTick, onMounted, ref, watch } from 'vue'

const props = defineProps({
  state: { type: String, default: 'idle' },
  mood: { type: String, default: 'happy' },
  size: { type: Number, default: 200 },
  waving: { type: Boolean, default: false },
  // { clips: { idle, talking, listening, thinking, wave } (urls), shape }
  video: { type: Object, default: () => ({}) },
})

const clips = computed(() => {
  const c = props.video?.clips || {}
  return Object.fromEntries(Object.entries(c).filter(([, url]) => !!url))
})
const shape = computed(() => props.video?.shape || 'rounded')
const aspect = ref(3 / 4) // from the idle clip once it loads
const waveDone = ref(false)
const els = {}

watch(() => props.waving, (w) => { if (w) waveDone.value = false })

const active = computed(() => {
  const c = clips.value
  if (props.waving && c.wave && !waveDone.value) return 'wave'
  if (props.state === 'speaking' && c.talking) return 'talking'
  if (props.state === 'listening' && c.listening) return 'listening'
  if (props.state === 'thinking' && c.thinking) return 'thinking'
  return c.idle ? 'idle' : Object.keys(c)[0] || null
})

function playOnly(key, restart) {
  const v = els[key]
  if (!v) return
  if (restart) v.currentTime = 0
  v.play().catch(() => {})
  // Pause the rest once the crossfade is over.
  setTimeout(() => {
    for (const [k, el] of Object.entries(els)) if (k !== active.value && el) el.pause()
  }, 350)
}

watch(active, async (key) => {
  await nextTick()
  playOnly(key, key === 'wave' || key === 'talking')
})
onMounted(() => nextTick(() => active.value && playOnly(active.value, false)))

function onMeta(key, e) {
  const v = e.target
  if (key === 'idle' && v.videoWidth && v.videoHeight) aspect.value = v.videoWidth / v.videoHeight
}
</script>

<template>
  <div
    class="va relative overflow-hidden"
    :class="`va-${shape}`"
    :style="{ width: size + 'px', aspectRatio: shape === 'circle' ? '1' : String(aspect) }"
  >
    <video
      v-for="(url, key) in clips"
      :key="url"
      :ref="(el) => (els[key] = el)"
      :src="url"
      class="absolute inset-0 h-full w-full transition-opacity duration-300"
      :class="[active === key ? 'opacity-100' : 'opacity-0', shape === 'cutout' ? 'object-contain' : 'object-cover']"
      muted
      playsinline
      preload="auto"
      :loop="key !== 'wave'"
      @loadedmetadata="onMeta(key, $event)"
      @ended="key === 'wave' && (waveDone = true)"
    ></video>

    <!-- No clips yet: a neutral silhouette so the slot is visible in Admin -->
    <div v-if="!active" class="absolute inset-0 grid place-items-center bg-ink-900/80 text-slate-400">
      <svg viewBox="0 0 64 64" class="w-1/2" fill="none" stroke="currentColor" stroke-width="2.5" aria-hidden="true">
        <circle cx="32" cy="22" r="11" />
        <path d="M12 58c2-12 10-18 20-18s18 6 20 18" stroke-linecap="round" />
      </svg>
    </div>
  </div>
</template>

<style scoped>
.va-rounded {
  border-radius: 1.5rem;
  border: 1px solid rgb(255 255 255 / 0.14);
  background: #0b1020;
  box-shadow: 0 20px 50px -20px rgb(2 6 23 / 0.8);
}
.va-circle {
  border-radius: 9999px;
  border: 2px solid rgb(125 211 252 / 0.45);
  background: #0b1020;
}
.va-cutout { overflow: visible; }
</style>
