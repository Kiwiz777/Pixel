<script setup>
/**
 * BotFace - EMO-inspired companion face.
 *
 * Deliberately NOT a boxy robot: no border, no antenna, no ears. Just a soft,
 * borderless dark "screen" with two expressive glowing cyan eyes (à la EMO the
 * desktop companion). Personality is carried almost entirely by the eyes.
 *
 * Still a placeholder you can upgrade: swap the <svg> internals for Lottie /
 * Canvas later without touching the public API.
 *
 * Public API:
 *   state: 'idle' | 'listening' | 'thinking' | 'speaking'
 *   mood:  'happy' | 'neutral' | 'curious'
 *   size:  px (number)
 */
import { computed } from 'vue'

const props = defineProps({
  state: { type: String, default: 'idle' },
  mood: { type: String, default: 'happy' },
  size: { type: Number, default: 200 },
})

// Happy mood + idle/speaking => smiling arc eyes; otherwise rounded eyes.
const happyEyes = computed(
  () => props.mood === 'happy' && (props.state === 'idle' || props.state === 'speaking'),
)
const label = computed(
  () => ({ idle: '', listening: 'Listening…', thinking: 'Thinking…', speaking: '' }[props.state] || ''),
)

// Eye geometry derived from state (keeps the template clean).
const eyeW = computed(() => (props.state === 'thinking' ? 16 : 20))
const eyeH = computed(() =>
  props.state === 'listening' ? 46 : props.state === 'thinking' ? 16 : 36,
)
const thinkY = computed(() =>
  props.state === 'thinking' ? 66 : props.state === 'listening' ? 56 : 60,
)
</script>

<template>
  <div class="botface select-none" :style="{ width: size + 'px' }" role="img" :aria-label="`Companion face, ${state}`">
    <!-- soft glow halo -->
    <span class="halo" :data-state="state"></span>

    <!-- listening ripples -->
    <template v-if="state === 'listening'">
      <span class="ripple animate-pulse-ring"></span>
      <span class="ripple animate-pulse-ring" style="animation-delay: 0.7s"></span>
    </template>

    <svg
      :class="['screen', { 'animate-bob-soft': state !== 'thinking' }]"
      :width="size" :height="size * 0.82" viewBox="0 0 200 164" fill="none"
    >
      <defs>
        <radialGradient id="bf-screen" cx="50%" cy="38%" r="75%">
          <stop offset="0" stop-color="#0e1830" />
          <stop offset="1" stop-color="#05070f" />
        </radialGradient>
        <linearGradient id="bf-eye" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stop-color="#7df0ff" />
          <stop offset="1" stop-color="#22d3ee" />
        </linearGradient>
        <filter id="bf-eyeglow" x="-60%" y="-60%" width="220%" height="220%">
          <feGaussianBlur stdDeviation="3" result="b" />
          <feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge>
        </filter>
      </defs>

      <!-- borderless dark screen (no stroke = no robot box) -->
      <rect x="6" y="6" width="188" height="152" rx="44" fill="url(#bf-screen)" />
      <!-- faint top sheen so it reads as a glassy display, not a flat box -->
      <rect x="20" y="16" width="160" height="40" rx="20" fill="#ffffff" opacity="0.04" />

      <!-- EYES -->
      <g filter="url(#bf-eyeglow)" :class="['eyes', state]">
        <!-- Happy arc eyes (smiling) -->
        <template v-if="happyEyes">
          <path d="M52 96 Q70 70 88 96" stroke="url(#bf-eye)" stroke-width="13" stroke-linecap="round" fill="none" />
          <path d="M112 96 Q130 70 148 96" stroke="url(#bf-eye)" stroke-width="13" stroke-linecap="round" fill="none" />
        </template>

        <!-- Rounded rectangle eyes (listening / thinking / neutral) -->
        <template v-else>
          <rect class="eye animate-blink" :x="58" :y="thinkY" :width="eyeW" :height="eyeH" :rx="eyeW / 2" fill="url(#bf-eye)" />
          <rect class="eye animate-blink" :x="122" :y="thinkY" :width="eyeW" :height="eyeH" :rx="eyeW / 2" fill="url(#bf-eye)" />
          <circle :cx="64" :cy="thinkY + 8" r="3.5" fill="#ffffff" opacity="0.85" />
          <circle :cx="128" :cy="thinkY + 8" r="3.5" fill="#ffffff" opacity="0.85" />
        </template>
      </g>

      <!-- speaking: soft equaliser mouth -->
      <g v-if="state === 'speaking'" fill="#22d3ee" opacity="0.95">
        <rect class="bar b1" x="84" y="120" width="7" height="14" rx="3.5" />
        <rect class="bar b2" x="96.5" y="116" width="7" height="22" rx="3.5" />
        <rect class="bar b3" x="109" y="120" width="7" height="14" rx="3.5" />
      </g>

      <!-- thinking: floating dots -->
      <g v-if="state === 'thinking'" class="think" fill="#7df0ff">
        <circle class="d1" cx="150" cy="40" r="3.5" />
        <circle class="d2" cx="163" cy="32" r="4.5" />
        <circle class="d3" cx="178" cy="26" r="5.5" />
      </g>
    </svg>

    <p v-if="label" class="state-label font-display">{{ label }}</p>
  </div>
</template>

<style scoped>
.botface {
  position: relative;
  display: grid;
  place-items: center;
}
.screen {
  position: relative;
  z-index: 2;
  filter: drop-shadow(0 16px 40px rgba(2, 8, 23, 0.6));
}
.halo {
  position: absolute;
  inset: 6%;
  z-index: 0;
  border-radius: 9999px;
  background: radial-gradient(circle, rgba(34, 211, 238, 0.35), transparent 65%);
  filter: blur(18px);
  transition: opacity 0.4s ease;
  opacity: 0.55;
}
.halo[data-state='listening'] { opacity: 0.9; }
.halo[data-state='thinking'] { opacity: 0.4; }

.ripple {
  position: absolute;
  z-index: 1;
  width: 66%;
  height: 66%;
  border-radius: 9999px;
  border: 2px solid rgba(34, 211, 238, 0.6);
}

.state-label {
  margin-top: 0.35rem;
  font-size: 0.9rem;
  color: #a5f3fc;
}

.eye { transform-origin: center; transform-box: fill-box; }
.eyes.thinking { animation: glance 2.4s ease-in-out infinite; }
@keyframes glance {
  0%, 100% { transform: translateX(0); }
  35% { transform: translateX(7px); }
  70% { transform: translateX(-6px); }
}

.bar { transform-origin: center; transform-box: fill-box; }
.b1 { animation: eq 0.5s ease-in-out infinite; }
.b2 { animation: eq 0.5s ease-in-out infinite 0.12s; }
.b3 { animation: eq 0.5s ease-in-out infinite 0.24s; }
@keyframes eq {
  0%, 100% { transform: scaleY(0.5); }
  50% { transform: scaleY(1.25); }
}

.think circle { opacity: 0; }
.think .d1 { animation: rise 1.6s infinite 0s; }
.think .d2 { animation: rise 1.6s infinite 0.22s; }
.think .d3 { animation: rise 1.6s infinite 0.44s; }
@keyframes rise {
  0% { opacity: 0; transform: translateY(4px); }
  45% { opacity: 1; transform: translateY(0); }
  100% { opacity: 0; transform: translateY(-5px); }
}

@media (prefers-reduced-motion: reduce) {
  .eyes, .bar, .think circle, .halo { animation: none !important; }
}
</style>
