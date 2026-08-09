<script setup>
/**
 * App-wide on-screen keyboard: Arabic + English, draggable, resizable, closable.
 *
 * Mounted once in App.vue so it works on every page. It types into whatever
 * text field last had focus (tracked in useGlobalKeyboard), so no page needs to
 * be aware of it.
 *
 * Pointer events (not mouse) throughout, because the kiosk is a touchscreen.
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import {
  open, lang, target,
  closeKeyboard, typeChar, backspace, submitTarget, rememberTarget,
} from '../composables/useGlobalKeyboard'

const EN_ROWS = [
  ['1', '2', '3', '4', '5', '6', '7', '8', '9', '0'],
  ['q', 'w', 'e', 'r', 't', 'y', 'u', 'i', 'o', 'p'],
  ['a', 's', 'd', 'f', 'g', 'h', 'j', 'k', 'l'],
  ['z', 'x', 'c', 'v', 'b', 'n', 'm'],
]
const AR_ROWS = [
  ['١', '٢', '٣', '٤', '٥', '٦', '٧', '٨', '٩', '٠'],
  ['ض', 'ص', 'ث', 'ق', 'ف', 'غ', 'ع', 'ه', 'خ', 'ح', 'ج'],
  ['ش', 'س', 'ي', 'ب', 'ل', 'ا', 'ت', 'ن', 'م', 'ك', 'ط'],
  ['ئ', 'ء', 'ؤ', 'ر', 'ﻻ', 'ى', 'ة', 'و', 'ز', 'ظ', 'د'],
]

const shift = ref(false)
const pos = ref({ x: 0, y: 0 })
const size = ref({ w: 720, h: 300 })
const placed = ref(false)

const isArabic = computed(() => lang.value === 'ar')
const rows = computed(() =>
  isArabic.value
    ? AR_ROWS
    : EN_ROWS.map((r, i) => (i === 0 ? r : r.map((k) => (shift.value ? k.toUpperCase() : k)))),
)

// Keys shrink with the panel so a resized keyboard stays usable.
const keyFont = computed(() => Math.max(12, Math.min(26, Math.round(size.value.w / 34))) + 'px')

function clampIntoView() {
  const maxX = window.innerWidth - size.value.w
  const maxY = window.innerHeight - size.value.h
  pos.value.x = Math.max(0, Math.min(pos.value.x, Math.max(0, maxX)))
  pos.value.y = Math.max(0, Math.min(pos.value.y, Math.max(0, maxY)))
}

function place() {
  size.value.w = Math.min(720, window.innerWidth - 24)
  pos.value = {
    x: Math.max(12, (window.innerWidth - size.value.w) / 2),
    y: Math.max(12, window.innerHeight - size.value.h - 24),
  }
  placed.value = true
}

// --- drag / resize (shared pointer plumbing) -------------------------------
let mode = null // 'move' | 'resize'
let startPointer = { x: 0, y: 0 }
let startBox = { x: 0, y: 0, w: 0, h: 0 }

function onPointerDown(e, which) {
  mode = which
  startPointer = { x: e.clientX, y: e.clientY }
  startBox = { ...pos.value, w: size.value.w, h: size.value.h }
  window.addEventListener('pointermove', onPointerMove)
  window.addEventListener('pointerup', onPointerUp)
  e.preventDefault()
}

function onPointerMove(e) {
  const dx = e.clientX - startPointer.x
  const dy = e.clientY - startPointer.y
  if (mode === 'move') {
    pos.value = { x: startBox.x + dx, y: startBox.y + dy }
  } else if (mode === 'resize') {
    size.value = {
      w: Math.max(320, Math.min(window.innerWidth - 16, startBox.w + dx)),
      h: Math.max(200, Math.min(window.innerHeight - 16, startBox.h + dy)),
    }
  }
  clampIntoView()
}

function onPointerUp() {
  mode = null
  window.removeEventListener('pointermove', onPointerMove)
  window.removeEventListener('pointerup', onPointerUp)
}

function press(key) {
  typeChar(key)
  if (shift.value && !isArabic.value) shift.value = false // one-shot capital
}

// Track focus globally so the keyboard always knows where to type.
function onFocusIn(e) {
  rememberTarget(e.target)
}

onMounted(() => {
  place()
  document.addEventListener('focusin', onFocusIn)
  window.addEventListener('resize', clampIntoView)
})
onBeforeUnmount(() => {
  document.removeEventListener('focusin', onFocusIn)
  window.removeEventListener('resize', clampIntoView)
  onPointerUp()
})
</script>

<template>
  <div
    v-if="open && placed"
    class="fixed z-[60] select-none"
    :style="{ left: pos.x + 'px', top: pos.y + 'px', width: size.w + 'px', height: size.h + 'px' }"
    role="dialog"
    aria-label="On-screen keyboard"
  >
    <div class="glass-card h-full flex flex-col p-2 shadow-glass border border-white/10">
      <!-- title bar: drag handle + language + close -->
      <div
        class="flex items-center gap-2 px-2 py-1.5 cursor-move touch-none rounded-lg hover:bg-white/5"
        @pointerdown="onPointerDown($event, 'move')"
      >
        <span class="text-slate-500 tracking-widest text-xs">⠿</span>
        <span class="font-display text-xs font-semibold">Keyboard</span>

        <div class="ml-auto flex items-center gap-1" @pointerdown.stop>
          <button
            class="kb-chip" :class="lang === 'en' ? 'kb-chip--on' : ''"
            :aria-pressed="lang === 'en'" @click="lang = 'en'"
          >EN</button>
          <button
            class="kb-chip" :class="lang === 'ar' ? 'kb-chip--on' : ''"
            :aria-pressed="lang === 'ar'" @click="lang = 'ar'"
          >ع</button>
          <button class="kb-chip" aria-label="Close keyboard" @click="closeKeyboard">✕</button>
        </div>
      </div>

      <p v-if="!target" class="text-[11px] text-amber-300/90 px-2 pb-1">
        Tap a text field first, then type.
      </p>

      <!-- keys -->
      <div class="flex-1 min-h-0 flex flex-col justify-center gap-1.5 px-1" :dir="isArabic ? 'rtl' : 'ltr'">
        <div v-for="(row, i) in rows" :key="i" class="flex justify-center gap-1.5">
          <button
            v-for="k in row"
            :key="k"
            type="button"
            class="kb-key flex-1 min-w-0"
            :style="{ fontSize: keyFont }"
            @click="press(k)"
          >{{ k }}</button>
        </div>

        <div class="flex justify-center gap-1.5">
          <button
            v-if="!isArabic"
            type="button" class="kb-key px-3" :class="shift ? 'kb-key--on' : ''"
            :aria-pressed="shift" aria-label="Shift" @click="shift = !shift"
          >⇧</button>
          <button type="button" class="kb-key px-3" @click="press('@')">@</button>
          <button type="button" class="kb-key px-3" @click="press('.')">.</button>
          <button type="button" class="kb-key flex-[3]" aria-label="Space" @click="press(' ')">space</button>
          <button type="button" class="kb-key px-3" aria-label="Backspace" @click="backspace">⌫</button>
          <button type="button" class="kb-key kb-key--go px-4" @click="submitTarget">↵</button>
        </div>
      </div>

      <!-- resize grip -->
      <div
        class="absolute bottom-0 right-0 h-6 w-6 cursor-nwse-resize touch-none grid place-items-center text-slate-500"
        aria-hidden="true"
        @pointerdown="onPointerDown($event, 'resize')"
      >◢</div>
    </div>
  </div>
</template>

<style scoped>
.kb-key {
  padding: 0.55rem 0.3rem;
  border-radius: 0.6rem;
  background: rgba(255, 255, 255, 0.08);
  border: 1px solid rgba(255, 255, 255, 0.12);
  color: #f1f5f9;
  font-weight: 600;
  line-height: 1;
  transition: background-color 0.12s ease, transform 0.12s ease;
}
.kb-key:active { background: rgba(255, 255, 255, 0.22); transform: scale(0.95); }
.kb-key--on { background: rgba(37, 99, 235, 0.55); border-color: rgba(37, 99, 235, 0.85); }
.kb-key--go { background: rgba(249, 115, 22, 0.85); border-color: rgba(249, 115, 22, 0.9); color: #fff; }

.kb-chip {
  padding: 0.2rem 0.55rem;
  border-radius: 0.5rem;
  font-size: 0.72rem;
  font-weight: 700;
  color: #cbd5e1;
  background: rgba(255, 255, 255, 0.07);
}
.kb-chip--on { background: rgba(37, 99, 235, 0.6); color: #fff; }

@media (prefers-reduced-motion: reduce) {
  .kb-key { transition: none; }
  .kb-key:active { transform: none; }
}
</style>
