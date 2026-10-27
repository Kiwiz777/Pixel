<script setup>
/**
 * Robot - the original EMO-inspired companion. Borderless dark "screen" with
 * two glowing cyan eyes; personality lives almost entirely in the eyes.
 * Waving pops a little glowing mitt out from the side of the screen.
 */
import { computed } from 'vue'

const props = defineProps({
  state: { type: String, default: 'idle' },
  mood: { type: String, default: 'happy' },
  size: { type: Number, default: 200 },
  waving: { type: Boolean, default: false },
})

// Happy mood + idle/speaking (or any wave) => smiling arc eyes.
const happyEyes = computed(
  () => props.waving || (props.mood === 'happy' && (props.state === 'idle' || props.state === 'speaking')),
)
const eyeW = computed(() => (props.state === 'thinking' ? 16 : 20))
const eyeH = computed(() =>
  props.state === 'listening' ? 46 : props.state === 'thinking' ? 16 : 36,
)
const eyeY = computed(() =>
  props.state === 'thinking' ? 66 : props.state === 'listening' ? 56 : 60,
)
</script>

<template>
  <svg :width="size" :height="size * 0.82" viewBox="0 0 200 164" fill="none" overflow="visible">
    <defs>
      <radialGradient id="rb-screen" cx="50%" cy="38%" r="75%">
        <stop offset="0" stop-color="#0e1830" />
        <stop offset="1" stop-color="#05070f" />
      </radialGradient>
      <linearGradient id="rb-eye" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" stop-color="#7df0ff" />
        <stop offset="1" stop-color="#22d3ee" />
      </linearGradient>
      <filter id="rb-glow" x="-60%" y="-60%" width="220%" height="220%">
        <feGaussianBlur stdDeviation="3" result="b" />
        <feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge>
      </filter>
    </defs>

    <!-- waving mitt, tucked behind the screen edge -->
    <g v-if="waving" class="wave-arm" filter="url(#rb-glow)">
      <rect x="168" y="70" width="40" height="16" rx="8" fill="#0e1830" stroke="#22d3ee" stroke-width="2.5" />
      <circle cx="214" cy="62" r="16" fill="#0e1830" stroke="#7df0ff" stroke-width="3.5" />
    </g>

    <rect x="6" y="6" width="188" height="152" rx="44" fill="url(#rb-screen)" />
    <rect x="20" y="16" width="160" height="40" rx="20" fill="#ffffff" opacity="0.04" />

    <g filter="url(#rb-glow)" :class="['eyes', state]">
      <template v-if="happyEyes">
        <path d="M52 96 Q70 70 88 96" stroke="url(#rb-eye)" stroke-width="13" stroke-linecap="round" />
        <path d="M112 96 Q130 70 148 96" stroke="url(#rb-eye)" stroke-width="13" stroke-linecap="round" />
      </template>
      <template v-else>
        <rect class="blink animate-blink" x="58" :y="eyeY" :width="eyeW" :height="eyeH" :rx="eyeW / 2" fill="url(#rb-eye)" />
        <rect class="blink animate-blink" x="122" :y="eyeY" :width="eyeW" :height="eyeH" :rx="eyeW / 2" fill="url(#rb-eye)" />
        <circle cx="64" :cy="eyeY + 8" r="3.5" fill="#ffffff" opacity="0.85" />
        <circle cx="128" :cy="eyeY + 8" r="3.5" fill="#ffffff" opacity="0.85" />
      </template>
    </g>

    <g v-if="state === 'speaking'" fill="#22d3ee" opacity="0.95">
      <rect class="talk" x="84" y="120" width="7" height="14" rx="3.5" />
      <rect class="talk" style="animation-delay: 0.12s" x="96.5" y="116" width="7" height="22" rx="3.5" />
      <rect class="talk" style="animation-delay: 0.24s" x="109" y="120" width="7" height="14" rx="3.5" />
    </g>
    <path v-else-if="waving" d="M86 124 Q100 136 114 124" stroke="#22d3ee" stroke-width="5" stroke-linecap="round" filter="url(#rb-glow)" />
  </svg>
</template>

<style scoped>
.blink, .talk { transform-origin: center; transform-box: fill-box; }
.talk { animation: eq 0.5s ease-in-out infinite; }
@keyframes eq {
  0%, 100% { transform: scaleY(0.5); }
  50% { transform: scaleY(1.25); }
}
.eyes.thinking { animation: glance 2.4s ease-in-out infinite; }
@keyframes glance {
  0%, 100% { transform: translateX(0); }
  35% { transform: translateX(7px); }
  70% { transform: translateX(-6px); }
}
.wave-arm {
  transform-origin: 176px 81px;
  transform-box: view-box;
  animation: wave 0.55s ease-in-out infinite alternate;
}
@keyframes wave {
  from { transform: rotate(-28deg); }
  to { transform: rotate(18deg); }
}
</style>
