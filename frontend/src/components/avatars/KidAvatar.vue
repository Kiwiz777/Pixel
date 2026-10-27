<script setup>
/**
 * Cartoon kid - round friendly face, big shiny eyes, orange brand tee.
 * Listening raises the eyebrows, thinking glances up, speaking opens the
 * mouth, waving swings the right arm up.
 */
import { computed } from 'vue'

const props = defineProps({
  state: { type: String, default: 'idle' },
  mood: { type: String, default: 'happy' },
  size: { type: Number, default: 200 },
  waving: { type: Boolean, default: false },
})

const happyEyes = computed(() => props.waving)
const eyeRy = computed(() => (props.state === 'listening' ? 12 : 10))
// Thinking looks up and to the side.
const look = computed(() => (props.state === 'thinking' ? { x: 4, y: -5 } : { x: 0, y: 0 }))
const browY = computed(() => (props.state === 'listening' ? -6 : props.state === 'thinking' ? -3 : 0))
</script>

<template>
  <svg :width="size" :height="size" viewBox="0 0 200 200" fill="none" overflow="visible">
    <!-- body / tee -->
    <path d="M36 204 Q38 160 100 154 Q162 160 164 204 Z" fill="#F97316" />
    <path d="M84 156 Q100 170 116 156" stroke="#C2410C" stroke-width="5" stroke-linecap="round" />

    <!-- waving arm (behind head, in front of body) -->
    <g v-if="waving" class="wave-arm">
      <path d="M150 178 Q166 150 176 124" stroke="#F97316" stroke-width="20" stroke-linecap="round" />
      <path d="M170 140 L180 116" stroke="#FBD3AE" stroke-width="14" stroke-linecap="round" />
      <circle cx="182" cy="108" r="12" fill="#FBD3AE" />
    </g>

    <rect x="88" y="132" width="24" height="26" rx="8" fill="#F1BB91" />

    <!-- ears + head -->
    <circle cx="48" cy="100" r="12" fill="#F1BB91" />
    <circle cx="152" cy="100" r="12" fill="#F1BB91" />
    <ellipse cx="100" cy="95" rx="52" ry="54" fill="#FBD3AE" />

    <!-- hair -->
    <path d="M47 94 Q42 38 100 36 Q158 38 153 94 Q146 66 122 60 Q124 74 108 76 Q104 60 84 62 Q66 70 47 94 Z" fill="#3B2414" />
    <path d="M94 40 Q100 18 118 26 Q106 30 104 42 Z" fill="#3B2414" />

    <!-- brows -->
    <g :transform="`translate(0 ${browY})`" class="ease" stroke="#3B2414" stroke-width="4" stroke-linecap="round">
      <path d="M70 82 Q80 77 90 82" />
      <path d="M110 82 Q120 77 130 82" />
    </g>

    <!-- eyes -->
    <g v-if="happyEyes" stroke="#1F2937" stroke-width="5" stroke-linecap="round">
      <path d="M71 102 Q80 92 89 102" />
      <path d="M111 102 Q120 92 129 102" />
    </g>
    <g v-else :transform="`translate(${look.x} ${look.y})`" class="ease">
      <g class="blink animate-blink">
        <ellipse cx="80" cy="100" rx="8" :ry="eyeRy" fill="#1F2937" />
        <ellipse cx="120" cy="100" rx="8" :ry="eyeRy" fill="#1F2937" />
        <circle cx="83" cy="96" r="3" fill="#fff" />
        <circle cx="123" cy="96" r="3" fill="#fff" />
      </g>
    </g>

    <!-- cheeks -->
    <ellipse cx="66" cy="120" rx="9" ry="5.5" fill="#FB7185" opacity="0.45" />
    <ellipse cx="134" cy="120" rx="9" ry="5.5" fill="#FB7185" opacity="0.45" />

    <!-- mouth -->
    <g v-if="state === 'speaking'" class="talk">
      <ellipse cx="100" cy="129" rx="10" ry="8" fill="#7C2D12" />
      <ellipse cx="100" cy="133" rx="6" ry="3" fill="#FB7185" />
    </g>
    <path v-else-if="state === 'thinking'" d="M93 130 Q100 127 107 130" stroke="#7C2D12" stroke-width="4" stroke-linecap="round" />
    <path v-else-if="waving" d="M84 122 Q100 142 116 122 Z" fill="#7C2D12" />
    <path v-else d="M86 124 Q100 136 114 124" stroke="#7C2D12" stroke-width="4" stroke-linecap="round" />
  </svg>
</template>

<style scoped>
.ease { transition: transform 0.35s cubic-bezier(0.16, 1, 0.3, 1); }
.blink, .talk { transform-origin: center; transform-box: fill-box; }
.talk { animation: talk 0.32s ease-in-out infinite alternate; }
@keyframes talk {
  from { transform: scaleY(0.45); }
  to { transform: scaleY(1); }
}
.wave-arm {
  transform-origin: 150px 178px;
  transform-box: view-box;
  animation: wave 0.5s ease-in-out infinite alternate;
}
@keyframes wave {
  from { transform: rotate(-12deg); }
  to { transform: rotate(14deg); }
}
</style>
