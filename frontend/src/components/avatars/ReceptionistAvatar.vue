<script setup>
/**
 * Receptionist - a realistic front-desk host. Shaded skin, natural
 * proportions, slim headset, tailored blazer.
 *
 * Motion is deliberately human, not cartoon: a slow head sway and breathing
 * at rest, quick natural blinks, small lip movement while speaking, a head
 * tilt while listening, a glance up while thinking, and a smooth hand raise
 * to wave. BotFace marks this avatar `motion: 'subtle'`, so the shell also
 * skips its hop / thinking dots / ripples for her.
 */
import { computed } from 'vue'

const props = defineProps({
  state: { type: String, default: 'idle' },
  mood: { type: String, default: 'happy' },
  size: { type: Number, default: 200 },
  waving: { type: Boolean, default: false },
})

// Iris offset: thinking glances up and aside.
const look = computed(() => (props.state === 'thinking' ? { x: -1.6, y: -1.6 } : { x: 0, y: 0 }))
const browLift = computed(() => (props.state === 'listening' || props.waving ? -1.6 : 0))
// Listening = slight attentive tilt; thinking = tilt the other way.
const tilt = computed(() => (props.state === 'listening' ? 3 : props.state === 'thinking' ? -2.5 : 0))
const smile = computed(() => props.waving || props.mood === 'happy')
</script>

<template>
  <svg :width="size" :height="size" viewBox="0 0 200 200" fill="none" overflow="visible">
    <defs>
      <radialGradient id="rc-skin" cx="48%" cy="40%" r="62%">
        <stop offset="0" stop-color="#F3CDB0" />
        <stop offset="0.7" stop-color="#E2AE8B" />
        <stop offset="1" stop-color="#C98F6C" />
      </radialGradient>
      <linearGradient id="rc-neck" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" stop-color="#B97F5E" />
        <stop offset="0.45" stop-color="#D9A280" />
      </linearGradient>
      <linearGradient id="rc-hair" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" stop-color="#3B2519" />
        <stop offset="1" stop-color="#1A0F0A" />
      </linearGradient>
      <linearGradient id="rc-blazer" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" stop-color="#26324D" />
        <stop offset="1" stop-color="#0F1626" />
      </linearGradient>
      <linearGradient id="rc-lip" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" stop-color="#B9566A" />
        <stop offset="1" stop-color="#93364A" />
      </linearGradient>
      <radialGradient id="rc-iris" cx="50%" cy="40%" r="60%">
        <stop offset="0" stop-color="#7A5539" />
        <stop offset="1" stop-color="#2C1A0F" />
      </radialGradient>
      <filter id="rc-soft" x="-50%" y="-50%" width="200%" height="200%">
        <feGaussianBlur stdDeviation="2.2" />
      </filter>
    </defs>

    <!-- body: breathes -->
    <g class="breathe">
      <path d="M32 206 Q34 164 70 153 L100 162 L130 153 Q166 164 168 206 Z" fill="url(#rc-blazer)" />
      <path d="M86 154 L100 184 L114 154 Q100 160 86 154 Z" fill="#F4F1EC" />
      <!-- lapels -->
      <path d="M70 153 L100 186 L84 158 Z" fill="#1A2338" />
      <path d="M130 153 L100 186 L116 158 Z" fill="#1A2338" />
      <path d="M70 153 L84 158" stroke="#3B4A6B" stroke-width="1" />
      <path d="M130 153 L116 158" stroke="#3B4A6B" stroke-width="1" />
      <!-- name badge -->
      <rect x="130" y="172" width="22" height="7" rx="1.5" fill="#E8EDF5" />
      <rect x="132" y="174.5" width="10" height="2" rx="1" fill="#F97316" />
    </g>

    <!-- waving arm -->
    <g v-if="waving" class="wave-arm">
      <path d="M150 182 Q163 156 169 132" stroke="url(#rc-blazer)" stroke-width="17" stroke-linecap="round" />
      <path d="M168 135 L170.5 127" stroke="#F4F1EC" stroke-width="15" stroke-linecap="round" />
      <path
        d="M163 124 Q162 110 166 101 Q168 97 170.5 100.5 L171.5 109 L172.5 96 Q174.5 92 177 96 L177 109 L179 99 Q181 95.5 183 99.5 L182 112 L185 107 Q188.5 105 188.5 109 Q184.5 122 176 128 Q167 131 163 124 Z"
        fill="url(#rc-skin)" stroke="#C98F6C" stroke-width="0.8"
      />
    </g>

    <!-- head: slow natural sway, tilts on listen/think -->
    <g class="sway">
      <g class="tilt" :style="{ transform: `rotate(${tilt}deg)` }">
        <!-- hair, back volume -->
        <path d="M62 84 Q56 32 100 30 Q146 32 140 86 Q142 120 150 146 Q144 154 128 152 Q100 158 72 152 Q56 154 50 146 Q58 120 62 84 Z" fill="url(#rc-hair)" />

        <!-- neck + jaw shadow -->
        <path d="M87 118 L87 148 Q100 155 113 148 L113 118 Z" fill="url(#rc-neck)" />

        <!-- ears -->
        <ellipse cx="66.5" cy="90" rx="4.5" ry="8" fill="#D9A07C" />
        <ellipse cx="133.5" cy="90" rx="4.5" ry="8" fill="#D9A07C" />

        <!-- face -->
        <path d="M66 80 Q66 40 100 40 Q134 40 134 80 Q134 110 117 125 Q108 133 100 133 Q92 133 83 125 Q66 110 66 80 Z" fill="url(#rc-skin)" />
        <!-- soft contour + cheek warmth -->
        <ellipse cx="76" cy="104" rx="7" ry="5" fill="#E58F86" opacity="0.28" filter="url(#rc-soft)" />
        <ellipse cx="124" cy="104" rx="7" ry="5" fill="#E58F86" opacity="0.28" filter="url(#rc-soft)" />

        <!-- fringe, side-swept with strands -->
        <path d="M65 84 Q63 44 103 39 Q134 41 137 76 Q128 57 108 55 Q90 56 80 66 Q71 74 65 84 Z" fill="url(#rc-hair)" />
        <g stroke="#5A3A27" stroke-width="0.9" stroke-linecap="round" opacity="0.7">
          <path d="M78 58 Q92 49 112 48" />
          <path d="M72 66 Q86 54 104 52" />
          <path d="M116 47 Q128 52 134 64" />
        </g>

        <!-- brows -->
        <g class="ease" :style="{ transform: `translateY(${browLift}px)` }" fill="#3B2519">
          <path d="M78 76.5 Q86 72 95 75 L95 76.4 Q86 74.2 78.5 78 Z" />
          <path d="M122 76.5 Q114 72 105 75 L105 76.4 Q114 74.2 121.5 78 Z" />
        </g>

        <!-- eyes -->
        <g class="blink">
          <path d="M79 86 Q87 80.5 95 86 Q87 89.5 79 86 Z" fill="#F8F3EE" />
          <path d="M105 86 Q113 80.5 121 86 Q113 89.5 105 86 Z" fill="#F8F3EE" />
          <g class="ease" :style="{ transform: `translate(${look.x}px, ${look.y}px)` }">
            <circle cx="87" cy="85.4" r="3" fill="url(#rc-iris)" />
            <circle cx="113" cy="85.4" r="3" fill="url(#rc-iris)" />
            <circle cx="87" cy="85.4" r="1.3" fill="#120A06" />
            <circle cx="113" cy="85.4" r="1.3" fill="#120A06" />
            <circle cx="88" cy="84.4" r="0.75" fill="#fff" />
            <circle cx="114" cy="84.4" r="0.75" fill="#fff" />
          </g>
          <!-- upper lids / lashes -->
          <path d="M78.5 86 Q87 79.6 95.5 85.6" stroke="#22140C" stroke-width="1.6" stroke-linecap="round" />
          <path d="M104.5 85.6 Q113 79.6 121.5 86" stroke="#22140C" stroke-width="1.6" stroke-linecap="round" />
          <path d="M80 87.5 Q87 89.8 94 87.6" stroke="#B4806A" stroke-width="0.6" opacity="0.7" />
          <path d="M106 87.6 Q113 89.8 120 87.5" stroke="#B4806A" stroke-width="0.6" opacity="0.7" />
        </g>

        <!-- nose -->
        <path d="M99.5 88 Q98.5 98 96 103 Q99.5 106 104 103.5" stroke="#B57A59" stroke-width="1.4" stroke-linecap="round" opacity="0.65" />

        <!-- lips -->
        <g v-if="state === 'speaking'">
          <path d="M90.5 113 Q95 110.5 100 112 Q105 110.5 109.5 113 Q100 114.2 90.5 113 Z" fill="url(#rc-lip)" />
          <ellipse class="talk-gap" cx="100" cy="115.2" rx="6.4" ry="2.4" fill="#3E1219" />
          <path class="talk-lip" d="M90.5 115 Q100 122 109.5 115 Q100 117.4 90.5 115 Z" fill="url(#rc-lip)" />
        </g>
        <g v-else>
          <path :d="smile ? 'M89.5 113 Q95 110.2 100 111.8 Q105 110.2 110.5 113 Q100 114.6 89.5 113 Z' : 'M90.5 113 Q95 110.6 100 112 Q105 110.6 109.5 113 Q100 114 90.5 113 Z'" fill="url(#rc-lip)" />
          <path v-if="waving" d="M92 114 Q100 116.8 108 114" stroke="#F8F3EE" stroke-width="1.6" stroke-linecap="round" />
          <path :d="smile ? 'M89.5 113 Q100 121 110.5 113 Q100 116 89.5 113 Z' : 'M90.5 113 Q100 119 109.5 113 Q100 115 90.5 113 Z'" fill="url(#rc-lip)" />
        </g>

        <!-- headset: slim band, single earpiece, thin boom -->
        <path d="M64 88 Q60 32 100 32 Q140 32 136 88" stroke="#2A3242" stroke-width="2.4" stroke-linecap="round" />
        <rect x="131" y="83" width="8" height="14" rx="4" fill="#2A3242" />
        <path d="M136 95 Q134 114 116 117" stroke="#2A3242" stroke-width="1.6" stroke-linecap="round" />
        <ellipse cx="114.6" cy="117.2" rx="2.6" ry="1.9" fill="#3A4458" />
        <circle cx="134.5" cy="86" r="0.9" fill="#38BDF8" class="led" />
      </g>
    </g>
  </svg>
</template>

<style scoped>
.ease { transition: transform 0.6s cubic-bezier(0.25, 1, 0.5, 1); }

.sway {
  transform-origin: 100px 150px;
  transform-box: view-box;
  animation: sway 7s ease-in-out infinite;
}
@keyframes sway {
  0%, 100% { transform: rotate(-1deg) translateY(0); }
  50% { transform: rotate(1deg) translateY(-0.6px); }
}
.tilt {
  transform-origin: 100px 150px;
  transform-box: view-box;
  transition: transform 0.8s cubic-bezier(0.25, 1, 0.5, 1);
}

.breathe {
  transform-origin: 100px 206px;
  transform-box: view-box;
  animation: breathe 4.2s ease-in-out infinite;
}
@keyframes breathe {
  0%, 100% { transform: scaleY(1); }
  50% { transform: scaleY(1.012); }
}

/* A blink is ~120ms, every few seconds - not a slow cartoon squash. */
.blink {
  transform-origin: 100px 85px;
  transform-box: view-box;
  animation: blink 5.6s infinite;
}
@keyframes blink {
  0%, 95%, 100% { transform: scaleY(1); }
  96.5% { transform: scaleY(0.08); }
}

/* Speech: small, irregular lip movement. */
.talk-lip, .talk-gap { transform-box: fill-box; transform-origin: top center; }
.talk-lip { animation: lip 0.9s ease-in-out infinite; }
.talk-gap { animation: gap 0.9s ease-in-out infinite; }
@keyframes lip {
  0%, 100% { transform: translateY(0); }
  20% { transform: translateY(1.6px); }
  45% { transform: translateY(0.5px); }
  70% { transform: translateY(2.2px); }
}
@keyframes gap {
  0%, 100% { transform: scaleY(0.35); }
  20% { transform: scaleY(1); }
  45% { transform: scaleY(0.55); }
  70% { transform: scaleY(1.15); }
}

.led { animation: led 2.4s ease-in-out infinite; }
@keyframes led { 50% { opacity: 0.25; } }

/* Raise the hand smoothly, then a calm wave. */
.wave-arm {
  transform-origin: 150px 182px;
  transform-box: view-box;
  animation: raise 0.55s cubic-bezier(0.25, 1, 0.5, 1), wave 1.1s ease-in-out 0.55s infinite alternate;
}
@keyframes raise {
  from { transform: rotate(48deg); opacity: 0; }
  to { transform: rotate(-5deg); opacity: 1; }
}
@keyframes wave {
  from { transform: rotate(-5deg); }
  to { transform: rotate(7deg); }
}
</style>
