<script setup>
/**
 * On-screen keyboard for the kiosk.
 *
 * A photobooth has a touchscreen and no physical keyboard, so any text input
 * needs one of these. Emits key events rather than touching the input directly,
 * so the parent stays in control of which field is being edited.
 *
 * `layout` picks the key set: 'text' for names, 'tel' for phone numbers.
 */
import { computed, ref } from 'vue'

const props = defineProps({
  layout: { type: String, default: 'text' }, // text|tel|email
})
const emit = defineEmits(['key', 'backspace', 'close'])

const shift = ref(true) // names start capitalised

const LETTER_ROWS = [
  ['q', 'w', 'e', 'r', 't', 'y', 'u', 'i', 'o', 'p'],
  ['a', 's', 'd', 'f', 'g', 'h', 'j', 'k', 'l'],
  ['z', 'x', 'c', 'v', 'b', 'n', 'm'],
]
const TEL_ROWS = [
  ['1', '2', '3'],
  ['4', '5', '6'],
  ['7', '8', '9'],
  ['+', '0', '-'],
]

const isTel = computed(() => props.layout === 'tel')
const isEmail = computed(() => props.layout === 'email')
const rows = computed(() => {
  if (isTel.value) return TEL_ROWS
  // Addresses are lowercase and need digits reachable, so no shift games here.
  const letters = LETTER_ROWS.map((row) =>
    row.map((k) => (shift.value && !isEmail.value ? k.toUpperCase() : k)),
  )
  return isEmail.value ? [['1','2','3','4','5','6','7','8','9','0'], ...letters] : letters
})

function press(key) {
  emit('key', key)
  if (shift.value && !isTel.value) shift.value = false // one-shot capital
}
</script>

<template>
  <div class="glass-card p-3 select-none" role="group" aria-label="On-screen keyboard">
    <div
      v-for="(row, i) in rows"
      :key="i"
      class="flex justify-center gap-1.5 mb-1.5"
    >
      <button
        v-for="k in row"
        :key="k"
        type="button"
        class="vk-key"
        :class="isTel ? 'w-16 sm:w-20' : 'flex-1 min-w-0 max-w-[3.25rem]'"
        @click="press(k)"
      >{{ k }}</button>
    </div>

    <div class="flex justify-center gap-1.5">
      <button
        v-if="!isTel && !isEmail"
        type="button"
        class="vk-key px-4"
        :class="shift ? 'vk-key--active' : ''"
        :aria-pressed="shift"
        aria-label="Shift"
        @click="shift = !shift"
      >⇧</button>
      <!-- Addresses are typed far more often than they are spelled out, so the
           three fiddliest characters get dedicated keys. -->
      <template v-if="isEmail">
        <button type="button" class="vk-key px-3" @click="press('@')">@</button>
        <button type="button" class="vk-key px-3" @click="press('.')">.</button>
        <button type="button" class="vk-key px-3" @click="press('_')">_</button>
        <button type="button" class="vk-key px-3" @click="press('.com')">.com</button>
      </template>
      <button
        v-if="!isTel && !isEmail"
        type="button"
        class="vk-key flex-1"
        aria-label="Space"
        @click="press(' ')"
      >space</button>
      <button
        type="button"
        class="vk-key px-4"
        :class="isTel ? 'flex-1' : ''"
        aria-label="Backspace"
        @click="emit('backspace')"
      >⌫</button>
      <button
        type="button"
        class="vk-key vk-key--done px-5"
        @click="emit('close')"
      >Done</button>
    </div>
  </div>
</template>

<style scoped>
.vk-key {
  padding: 0.7rem 0.4rem;
  border-radius: 0.75rem;
  background: rgba(255, 255, 255, 0.08);
  color: #f1f5f9;
  font-weight: 600;
  font-size: 1.05rem;
  line-height: 1;
  border: 1px solid rgba(255, 255, 255, 0.12);
  transition: background-color 0.12s ease, transform 0.12s ease;
}
.vk-key:active {
  background: rgba(255, 255, 255, 0.2);
  transform: scale(0.95);
}
.vk-key--active {
  background: rgba(37, 99, 235, 0.55);
  border-color: rgba(37, 99, 235, 0.8);
}
.vk-key--done {
  background: rgba(249, 115, 22, 0.85);
  border-color: rgba(249, 115, 22, 0.9);
  color: #fff;
}

@media (prefers-reduced-motion: reduce) {
  .vk-key { transition: none; }
  .vk-key:active { transform: none; }
}
</style>
