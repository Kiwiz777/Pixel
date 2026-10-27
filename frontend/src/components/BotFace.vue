<script setup>
/**
 * BotFace - the kiosk's animated character.
 *
 * A thin shell around one of the avatars in ./avatars (robot, cartoon kid,
 * receptionist, fox - chosen in Admin -> Avatar & Welcome). The shell owns the
 * effects every character shares: glow halo, listening ripples, thinking dots,
 * the state label, and the welcome hop. The avatar itself only draws the
 * character and its expressions. Avatars marked `motion: 'subtle'` (the
 * realistic receptionist) get none of the cartoon effects - just the halo,
 * the label and a gentle nod on welcome.
 *
 * Public API:
 *   avatar: avatar id (see avatars/index.js); unknown ids fall back to robot
 *   state:  'idle' | 'listening' | 'thinking' | 'speaking'
 *   mood:   'happy' | 'neutral' | 'curious'
 *   size:   px (number)
 *   waving: true while welcoming a guest - hops and waves, layered on `state`
 *   video:  real-person avatar clips + shape (ignored by the drawn avatars)
 */
import { computed } from 'vue'
import { avatarById } from './avatars'

const props = defineProps({
  avatar: { type: String, default: 'robot' },
  state: { type: String, default: 'idle' },
  mood: { type: String, default: 'happy' },
  size: { type: Number, default: 200 },
  waving: { type: Boolean, default: false },
  // Real-person avatar only: { clips: {idle, talking, ...} urls, shape }.
  video: { type: Object, default: () => ({}) },
})

const def = computed(() => avatarById(props.avatar))
const subtle = computed(() => def.value.motion === 'subtle')
const label = computed(
  () => ({ listening: 'Listening…', thinking: 'Thinking…' }[props.state] || ''),
)
</script>

<template>
  <div
    class="botface select-none"
    :class="{ 'is-waving': waving, subtle }"
    :style="{ width: size + 'px', '--glow': def.glow }"
    role="img"
    :aria-label="`${def.label} avatar, ${waving ? 'waving hello' : state}`"
  >
    <span class="halo" :data-state="waving ? 'waving' : state"></span>

    <template v-if="state === 'listening' && !subtle">
      <span class="ripple animate-pulse-ring"></span>
      <span class="ripple animate-pulse-ring" style="animation-delay: 0.7s"></span>
    </template>

    <div :class="['figure', { 'animate-bob-soft': state !== 'thinking' && !waving && !subtle }]">
      <component
        :is="def.comp" :state="state" :mood="mood" :size="size" :waving="waving"
        v-bind="def.video ? { video } : {}"
      />
    </div>

    <div v-if="state === 'thinking' && !subtle" class="think" aria-hidden="true">
      <span></span><span></span><span></span>
    </div>

    <p v-if="label" class="state-label font-display">{{ label }}</p>
  </div>
</template>

<style scoped>
.botface {
  position: relative;
  display: grid;
  place-items: center;
}
.figure {
  position: relative;
  z-index: 2;
  filter: drop-shadow(0 16px 40px rgba(2, 8, 23, 0.6));
}
.halo {
  position: absolute;
  inset: 6%;
  z-index: 0;
  border-radius: 9999px;
  background: radial-gradient(circle, rgba(var(--glow), 0.35), transparent 65%);
  filter: blur(18px);
  transition: opacity 0.4s ease, transform 0.4s ease;
  opacity: 0.55;
}
.halo[data-state='listening'] { opacity: 0.9; }
.halo[data-state='thinking'] { opacity: 0.4; }
.halo[data-state='waving'] { opacity: 1; transform: scale(1.15); }

.ripple {
  position: absolute;
  z-index: 1;
  width: 66%;
  height: 66%;
  border-radius: 9999px;
  border: 2px solid rgba(var(--glow), 0.6);
}

/* Welcome: a couple of happy hops, then settle. */
.is-waving .figure {
  animation: hop 0.7s cubic-bezier(0.34, 1.56, 0.64, 1) 3;
}
@keyframes hop {
  0%, 100% { transform: translateY(0) rotate(0); }
  40% { transform: translateY(-14px) rotate(-3deg); }
  70% { transform: translateY(-4px) rotate(2deg); }
}

/* Realistic avatars: a calm nod instead of hopping, quieter glow. */
.subtle .halo { opacity: 0.35; }
.subtle .halo[data-state='listening'] { opacity: 0.6; }
.subtle.is-waving .figure {
  animation: nod 1.4s cubic-bezier(0.25, 1, 0.5, 1) 1;
}
@keyframes nod {
  0%, 100% { transform: translateY(0); }
  35% { transform: translateY(-4px); }
  65% { transform: translateY(1px); }
}

.think {
  position: absolute;
  z-index: 3;
  top: 0;
  right: 2%;
  display: flex;
  align-items: flex-end;
  gap: 4px;
}
.think span {
  display: block;
  border-radius: 9999px;
  background: rgb(var(--glow));
  opacity: 0;
  animation: rise 1.6s infinite;
}
.think span:nth-child(1) { width: 7px; height: 7px; }
.think span:nth-child(2) { width: 9px; height: 9px; animation-delay: 0.22s; }
.think span:nth-child(3) { width: 11px; height: 11px; animation-delay: 0.44s; }
@keyframes rise {
  0% { opacity: 0; transform: translateY(4px); }
  45% { opacity: 1; transform: translateY(0); }
  100% { opacity: 0; transform: translateY(-5px); }
}

.state-label {
  margin-top: 0.35rem;
  font-size: 0.9rem;
  color: #e0f2fe;
}

@media (prefers-reduced-motion: reduce) {
  .figure, .think span, .halo { animation: none !important; }
  .think span { opacity: 1; }
}
</style>
