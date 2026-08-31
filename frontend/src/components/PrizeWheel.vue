<script setup>
/**
 * PrizeWheel - a themed, animated SVG prize wheel (Liquid-Glass / brand palette
 * by default, fully re-themeable via the `theme` prop — see Admin > Quiz >
 * Wheel style, backed by the `wheel_style` setting).
 *
 * Timeline once `winner` is a valid index:
 *   1. holds still for `prerollMs` (default 2s), glowing, to build anticipation
 *   2. spins slowly and decelerates onto the winning slice (`spinMs`)
 *   3. holds `holdMs` with the winning slice lit, then emits `done`
 *
 * The parent hides the wheel on `done` so only the reward remains.
 * Labels only — callers pass display text (never voucher codes).
 */
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue'

const props = defineProps({
  segments: { type: Array, default: () => [] }, // [{ label, color? }] — color overrides the default gradient
  winner: { type: Number, default: -1 },        // index to land on (-1 = idle)
  size: { type: Number, default: 340 },
  prerollMs: { type: Number, default: 2000 },
  spinMs: { type: Number, default: 5600 },
  holdMs: { type: Number, default: 1300 },
  // Wheel "chrome" theme — see DEFAULT_SETTINGS.wheel_style in backend/database.py.
  theme: { type: Object, default: () => ({}) },
})
const emit = defineEmits(['done'])

// On-brand gradient pairs (orange ↔ electric-blue family) — the fallback
// palette for segments that don't have an admin-set color of their own.
const GRADIENTS = [
  ['#FB923C', '#F97316'], // orange
  ['#38BDF8', '#2563EB'], // blue
  ['#FDBA74', '#EA580C'], // amber-orange
  ['#818CF8', '#4F46E5'], // indigo
  ['#F59E0B', '#F97316'], // gold
  ['#22D3EE', '#0EA5E9'], // cyan
]

// --- theme (with sane fallbacks matching the pre-customization defaults) --
const isSolid = computed(() => props.theme?.segment_style === 'solid')
const pointerColor = computed(() => props.theme?.pointer_color || '#F97316')
const hubColor = computed(() => props.theme?.hub_color || '#1e293b')
const hubAccentColor = computed(() => props.theme?.hub_accent_color || '#F97316')
const glowColor1 = computed(() => props.theme?.glow_color_1 || '#F97316')
const glowColor2 = computed(() => props.theme?.glow_color_2 || '#38BDF8')
const borderColor = computed(() => props.theme?.border_color || '#F8FAFC')
const labelColor = computed(() => props.theme?.label_color || '#F8FAFC')
const labelFontFamily = computed(() =>
  props.theme?.label_font === 'display' ? 'Fredoka, system-ui, sans-serif' : 'Nunito, system-ui, sans-serif',
)
const frameImageUrl = computed(() => props.theme?.frame_image || '')
const backgroundImageUrl = computed(() => props.theme?.background_image || '')

const rotation = ref(0)
const spinning = ref(false)
const landed = ref(false)
let doneEmitted = false
const timers = []

const n = computed(() => Math.max(props.segments.length, 1))
const seg = computed(() => 360 / n.value)
const r = computed(() => props.size / 2)
const hub = computed(() => Math.max(26, props.size * 0.11))

// With only a few large slices, upright centred labels read best; with many
// slices we rotate them radially so they fit. Font + radius scale to the count.
const fewSlices = computed(() => n.value <= 4)
const labelRadius = computed(() => (n.value === 1 ? 0 : r.value * (fewSlices.value ? 0.54 : 0.6)))
const fontSize = computed(() =>
  n.value <= 2 ? 15 : n.value <= 4 ? 14 : n.value <= 7 ? 12.5 : n.value <= 10 ? 11 : 10,
)
// Characters per line before wrapping — keeps labels inside their wedge.
const maxLine = computed(() => (fewSlices.value ? 13 : n.value <= 8 ? 10 : 8))

function polar(angleDeg, radius) {
  const a = ((angleDeg - 90) * Math.PI) / 180
  return [r.value + radius * Math.cos(a), r.value + radius * Math.sin(a)]
}
function slicePath(i) {
  const rr = r.value - 6
  // A single option fills the whole disc (two half-arcs) — no zero-width wedge.
  if (n.value === 1) {
    return `M ${r.value} ${r.value - rr} A ${rr} ${rr} 0 1 1 ${r.value} ${r.value + rr} `
      + `A ${rr} ${rr} 0 1 1 ${r.value} ${r.value - rr} Z`
  }
  const a0 = i * seg.value
  const a1 = (i + 1) * seg.value
  const [x0, y0] = polar(a0, rr)
  const [x1, y1] = polar(a1, rr)
  const large = seg.value > 180 ? 1 : 0
  return `M ${r.value} ${r.value} L ${x0} ${y0} A ${rr} ${rr} 0 ${large} 1 ${x1} ${y1} Z`
}
function labelTransform(i) {
  if (n.value === 1) return `translate(${r.value} ${r.value - r.value * 0.42})`
  const mid = i * seg.value + seg.value / 2
  const [x, y] = polar(mid, labelRadius.value)
  if (fewSlices.value) return `translate(${x} ${y})` // upright, centred in the wedge
  let rot = mid
  if (mid > 90 && mid < 270) rot += 180
  return `translate(${x} ${y}) rotate(${rot})`
}
function grad(i) {
  return `grad${i % GRADIENTS.length}`
}
// Admin-set solid color (per segment) wins over the default gradient palette.
function sliceFill(i) {
  return props.segments[i]?.color || `url(#${grad(i)})`
}
// Tinted-glass fill by default: see-through, brightening the winner on
// landing. "Solid" theme keeps slices opaque throughout instead.
function sliceOpacity(i) {
  if (!landed.value) return isSolid.value ? 0.94 : 0.24
  if (i === props.winner) return 1
  return isSolid.value ? 0.45 : 0.1
}
// Wrap a label into at most two lines that fit within the wedge.
function labelLines(label) {
  const words = String(label ?? '').trim().split(/\s+/).filter(Boolean)
  if (!words.length) return ['']
  const lim = maxLine.value
  const lines = ['']
  for (const w of words) {
    const word = w.length > lim ? w.slice(0, lim - 1) + '…' : w
    const li = lines.length - 1
    if (!lines[li]) lines[li] = word
    else if ((lines[li] + ' ' + word).length <= lim) lines[li] += ' ' + word
    else if (lines.length < 2) lines.push(word)
    else { lines[li] += '…'; break }
  }
  return lines
}

const transitionStyle = computed(() =>
  spinning.value
    ? `transform ${props.spinMs}ms cubic-bezier(0.08, 0.62, 0.1, 1)`
    : 'none',
)

function clearTimers() {
  while (timers.length) clearTimeout(timers.pop())
}

function startSequence(index) {
  if (index == null || index < 0 || index >= n.value) return
  clearTimers()
  doneEmitted = false
  landed.value = false
  rotation.value = 0
  spinning.value = false

  // Bring the winning slice centre under the top pointer, after several turns.
  const mid = index * seg.value + seg.value / 2
  const turns = 6
  const target = turns * 360 + (360 - mid)

  // 1) hold still (glow) → 2) start the slow decelerating spin.
  timers.push(setTimeout(() => {
    spinning.value = true
    requestAnimationFrame(() => requestAnimationFrame(() => (rotation.value = target)))
  }, props.prerollMs))
}

function onTransitionEnd() {
  if (!spinning.value || doneEmitted) return
  spinning.value = false
  landed.value = true
  // 3) hold on the winner, then let the parent reveal the reward.
  timers.push(setTimeout(() => {
    doneEmitted = true
    emit('done')
  }, props.holdMs))
}

watch(() => props.winner, (i) => { if (i >= 0) startSequence(i) })
onMounted(() => { if (props.winner >= 0) startSequence(props.winner) })
onBeforeUnmount(clearTimers)
</script>

<template>
  <div
    class="relative inline-grid place-items-center"
    :style="{ width: `${size}px`, height: `${size + 30}px`, '--glow1': glowColor1, '--glow2': glowColor2 }"
  >
    <!-- custom background art (replaces the procedural glow + frosted disc) -->
    <img
      v-if="backgroundImageUrl"
      :src="backgroundImageUrl" alt=""
      class="absolute rounded-full pointer-events-none object-cover"
      :style="{ width: `${size * 1.15}px`, height: `${size * 1.15}px`, top: `${30 - size * 0.075}px` }"
    />
    <template v-else>
      <!-- ambient glow -->
      <div class="absolute rounded-full pointer-events-none"
           :style="{ width: `${size * 0.92}px`, height: `${size * 0.92}px`, top: '30px',
                     background: `radial-gradient(circle, ${glowColor1}38, ${glowColor2}20 55%, transparent 72%)`,
                     filter: 'blur(16px)' }"></div>

      <!-- frosted glass disc: blurs whatever is behind the wheel -->
      <div class="absolute rounded-full pointer-events-none"
           :style="{ width: `${size}px`, height: `${size}px`, top: '30px',
                     backdropFilter: 'blur(6px)', WebkitBackdropFilter: 'blur(6px)',
                     background: 'rgba(255,255,255,0.04)',
                     boxShadow: 'inset 0 1px 12px rgba(255,255,255,0.08)' }"></div>
    </template>

    <!-- pointer -->
    <div class="wheel-pointer absolute z-20" :style="{ borderTopColor: pointerColor }" aria-hidden="true"></div>

    <svg
      :width="size" :height="size" :viewBox="`0 0 ${size} ${size}`"
      class="mt-[30px] rounded-full"
      :class="{ 'wheel-glow': !spinning && !landed }"
      :style="{ transform: `rotate(${rotation}deg)`, transition: transitionStyle }"
      @transitionend="onTransitionEnd"
    >
      <defs>
        <linearGradient v-for="(g, i) in GRADIENTS" :key="i" :id="`grad${i}`" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" :stop-color="g[0]" />
          <stop offset="100%" :stop-color="g[1]" />
        </linearGradient>
        <radialGradient id="hubGrad" cx="50%" cy="42%" r="60%">
          <stop offset="0%" :stop-color="hubColor" />
          <stop offset="100%" stop-color="#070b16" />
        </radialGradient>
        <linearGradient id="sheen" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="#ffffff" stop-opacity="0.22" />
          <stop offset="45%" stop-color="#ffffff" stop-opacity="0.05" />
          <stop offset="100%" stop-color="#ffffff" stop-opacity="0" />
        </linearGradient>
      </defs>

      <!-- slices (translucent "glass" by default, opaque with the solid theme) -->
      <g v-for="(seg2, i) in segments" :key="i">
        <path
          :d="slicePath(i)" :fill="sliceFill(i)"
          :fill-opacity="sliceOpacity(i)"
          :stroke="borderColor" stroke-opacity="0.25" stroke-width="1.5"
          :style="landed && i === winner ? 'filter: drop-shadow(0 0 12px rgba(255,255,255,0.6));' : ''"
        />
        <text
          :transform="labelTransform(i)"
          :fill="labelColor" :font-size="fontSize" font-weight="800"
          :font-family="labelFontFamily" text-anchor="middle" dominant-baseline="middle"
          style="paint-order: stroke; stroke: #0b1120; stroke-width: 3.5px; stroke-opacity: 0.55;"
          :opacity="landed && i !== winner ? 0.4 : 1"
        >
          <tspan
            v-for="(ln, li) in labelLines(seg2.label)" :key="li"
            x="0" :dy="li === 0 ? `${-(labelLines(seg2.label).length - 1) * 0.55}em` : '1.1em'"
          >{{ ln }}</tspan>
        </text>
      </g>

      <!-- glassy top sheen + rim -->
      <circle :cx="r" :cy="r" :r="r - 6" fill="url(#sheen)" pointer-events="none" />
      <circle :cx="r" :cy="r" :r="r - 3" fill="none" :stroke="borderColor" stroke-opacity="0.28" stroke-width="2" />
      <circle :cx="r" :cy="r" :r="r - 2" fill="none" stroke="#000000" stroke-opacity="0.35" stroke-width="3" />

      <!-- hub -->
      <circle :cx="r" :cy="r" :r="hub + 4" :fill="borderColor" fill-opacity="0.85" />
      <circle :cx="r" :cy="r" :r="hub" fill="url(#hubGrad)" :stroke="hubAccentColor" stroke-width="2.5" />
      <text :x="r" :y="r + 1" :fill="labelColor" font-size="20" text-anchor="middle" dominant-baseline="middle">★</text>
    </svg>

    <!-- custom frame/bezel art, drawn on top (typically a ring PNG with a transparent center) -->
    <img
      v-if="frameImageUrl"
      :src="frameImageUrl" alt=""
      class="absolute pointer-events-none z-10 object-contain"
      :style="{ width: `${size}px`, height: `${size}px`, top: '30px' }"
    />
  </div>
</template>

<style scoped>
.wheel-pointer {
  top: 8px;
  width: 0;
  height: 0;
  border-left: 15px solid transparent;
  border-right: 15px solid transparent;
  border-top-width: 26px;
  border-top-style: solid;
  filter: drop-shadow(0 3px 4px rgba(0, 0, 0, 0.55));
}
.wheel-glow {
  animation: wheelPulse 1.6s ease-in-out infinite;
}
@keyframes wheelPulse {
  0%, 100% { filter: drop-shadow(0 0 6px var(--glow1, #f97316)); }
  50% { filter: drop-shadow(0 0 20px var(--glow2, #38bdf8)); }
}
@media (prefers-reduced-motion: reduce) {
  .wheel-glow { animation: none; }
}
</style>
