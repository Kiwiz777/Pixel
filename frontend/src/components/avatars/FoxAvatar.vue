<script setup>
/**
 * Fox - a brand-orange mascot. Ears perk up while listening, paw waves on
 * welcome. Works well for family / kids events.
 */
import { computed } from 'vue'

const props = defineProps({
  state: { type: String, default: 'idle' },
  mood: { type: String, default: 'happy' },
  size: { type: Number, default: 200 },
  waving: { type: Boolean, default: false },
})

const look = computed(() => (props.state === 'thinking' ? { x: 4, y: -4 } : { x: 0, y: 0 }))
const eyeRy = computed(() => (props.state === 'listening' ? 11 : 9))
</script>

<template>
  <svg :width="size" :height="size" viewBox="0 0 200 200" fill="none" overflow="visible">
    <!-- body -->
    <path d="M46 204 Q50 160 100 154 Q150 160 154 204 Z" fill="#EA580C" />
    <path d="M78 204 Q82 168 100 164 Q118 168 122 204 Z" fill="#FFF7ED" />

    <!-- waving paw -->
    <g v-if="waving" class="wave-arm">
      <path d="M146 178 Q164 150 174 122" stroke="#EA580C" stroke-width="18" stroke-linecap="round" />
      <circle cx="178" cy="112" r="12" fill="#1F2937" />
    </g>

    <!-- ears -->
    <g :class="['ears', { perk: state === 'listening' }]">
      <path class="ear-l" d="M54 76 L58 18 L98 50 Z" fill="#F97316" />
      <path class="ear-l" d="M62 66 L64 34 L86 52 Z" fill="#1F2937" />
      <path class="ear-r" d="M146 76 L142 18 L102 50 Z" fill="#F97316" />
      <path class="ear-r" d="M138 66 L136 34 L114 52 Z" fill="#1F2937" />
    </g>

    <!-- head + white muzzle -->
    <ellipse cx="100" cy="96" rx="58" ry="52" fill="#F97316" />
    <path d="M44 100 Q70 110 100 146 Q130 110 156 100 Q146 142 100 150 Q54 142 44 100 Z" fill="#FFF7ED" />

    <!-- eyes -->
    <g v-if="waving" stroke="#1F2937" stroke-width="5" stroke-linecap="round">
      <path d="M69 98 Q78 88 87 98" />
      <path d="M113 98 Q122 88 131 98" />
    </g>
    <g v-else :transform="`translate(${look.x} ${look.y})`" class="ease">
      <g class="blink animate-blink">
        <ellipse cx="78" cy="96" rx="7" :ry="eyeRy" fill="#1F2937" />
        <ellipse cx="122" cy="96" rx="7" :ry="eyeRy" fill="#1F2937" />
        <circle cx="80.5" cy="92" r="2.6" fill="#fff" />
        <circle cx="124.5" cy="92" r="2.6" fill="#fff" />
      </g>
    </g>

    <!-- nose + mouth -->
    <ellipse cx="100" cy="122" rx="7.5" ry="5.5" fill="#1F2937" />
    <ellipse v-if="state === 'speaking'" class="talk" cx="100" cy="136" rx="7" ry="6" fill="#7C2D12" />
    <path v-else d="M90 132 Q95 138 100 132 Q105 138 110 132" stroke="#1F2937" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" />
  </svg>
</template>

<style scoped>
.ease { transition: transform 0.35s cubic-bezier(0.16, 1, 0.3, 1); }
.blink, .talk { transform-origin: center; transform-box: fill-box; }
.talk { animation: talk 0.3s ease-in-out infinite alternate; }
@keyframes talk {
  from { transform: scaleY(0.35); }
  to { transform: scaleY(1); }
}
.ear-l, .ear-r { transition: transform 0.3s cubic-bezier(0.16, 1, 0.3, 1); transform-box: view-box; }
.ear-l { transform-origin: 76px 60px; }
.ear-r { transform-origin: 124px 60px; }
.perk .ear-l { transform: rotate(-9deg) translateY(-4px); }
.perk .ear-r { transform: rotate(9deg) translateY(-4px); }
.wave-arm {
  transform-origin: 146px 178px;
  transform-box: view-box;
  animation: wave 0.5s ease-in-out infinite alternate;
}
@keyframes wave {
  from { transform: rotate(-12deg); }
  to { transform: rotate(14deg); }
}
</style>
