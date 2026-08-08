<script setup>
/**
 * "Contact us" form for the kiosk.
 *
 * Three ways to fill it in, because a photobooth has a touchscreen and guests
 * are often holding props:
 *   - tap a field and use the on-screen keyboard
 *   - speak it: Whisper transcribes, then the LLM pulls out name + phone
 *   - a physical keyboard, if the kiosk happens to have one
 *
 * Speech fills the fields rather than submitting, so the guest can correct a
 * misheard digit before it's saved.
 */
import { computed, ref } from 'vue'
import { api } from '../lib/api'
import { useBot } from '../composables/useBot'
import VirtualKeyboard from './VirtualKeyboard.vue'

const props = defineProps({
  language: { type: String, default: 'en' },
})
const emit = defineEmits(['close'])

const bot = useBot()

const form = ref({ name: '', phone: '' })
const activeField = ref('') // '' = keyboard hidden
const listening = ref(false)
const usedVoice = ref(false) // recorded with the submission so Admin can tell them apart
const saving = ref(false)
const status = ref('')
const error = ref('')
const done = ref(false)

const canSubmit = computed(() => form.value.name.trim().length > 0 && !saving.value)
const keyboardLayout = computed(() => (activeField.value === 'phone' ? 'tel' : 'text'))

function openKeyboard(field) {
  activeField.value = field
}

function onKey(char) {
  if (!activeField.value) return
  form.value[activeField.value] += char
}

function onBackspace() {
  if (!activeField.value) return
  const current = form.value[activeField.value]
  form.value[activeField.value] = current.slice(0, -1)
}

/** Record a sentence, transcribe it, and let the AI split it into fields. */
async function speak() {
  if (listening.value) return
  error.value = ''
  status.value = 'Listening… say your name and number'
  listening.value = true
  activeField.value = '' // the keyboard would only get in the way
  try {
    const text = await bot.listenOnce(props.language)
    if (!text) {
      status.value = ''
      error.value = "Didn't catch that — try again or type it in."
      return
    }
    status.value = 'Got it, reading that back…'
    const parsed = await api.parseContact(text)
    if (parsed.name) form.value.name = parsed.name
    if (parsed.phone) form.value.phone = parsed.phone
    if (parsed.name || parsed.phone) usedVoice.value = true
    status.value = parsed.name || parsed.phone
      ? 'Check it looks right, then send.'
      : ''
    if (!parsed.name && !parsed.phone) {
      error.value = `Heard "${text}" but couldn't find a name or number in it.`
    }
  } catch (e) {
    status.value = ''
    error.value = e.message || 'Voice input failed.'
  } finally {
    listening.value = false
  }
}

async function submit() {
  if (!canSubmit.value) return
  saving.value = true
  error.value = ''
  try {
    await api.submitContact({
      name: form.value.name.trim(),
      phone: form.value.phone.trim(),
      source: usedVoice.value ? 'voice' : 'form',
    })
    done.value = true
    setTimeout(() => emit('close'), 1800)
  } catch (e) {
    error.value = e.message || 'Could not send that — please try again.'
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="fixed inset-0 z-50 grid place-items-center p-4" role="dialog" aria-modal="true" aria-labelledby="contact-title">
    <div class="absolute inset-0 bg-ink-950/70 backdrop-blur-sm" @click="emit('close')"></div>

    <div class="modal glass-card relative w-full max-w-xl p-5 sm:p-6 max-h-[92dvh] overflow-y-auto">
      <div class="flex items-center justify-between mb-4">
        <h2 id="contact-title" class="font-display text-2xl font-semibold">Contact us</h2>
        <button class="btn-ghost btn-sm" @click="emit('close')" aria-label="Close">✕</button>
      </div>

      <!-- success -->
      <div v-if="done" class="py-10 text-center">
        <div class="mx-auto mb-4 h-16 w-16 rounded-full bg-brand-500/20 grid place-items-center">
          <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#f97316" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>
        </div>
        <p class="font-display text-xl">Thanks, {{ form.name.trim() }}!</p>
        <p class="hint">We'll be in touch.</p>
      </div>

      <template v-else>
        <p class="hint !mt-0 mb-4">Leave your details and we'll get back to you.</p>

        <div class="grid gap-4">
          <div>
            <label class="label" for="contact-name">Your name</label>
            <input
              id="contact-name"
              v-model="form.name"
              class="field"
              :class="activeField === 'name' ? 'ring-2 ring-electric-400' : ''"
              autocomplete="name"
              placeholder="Tap to type"
              @focus="openKeyboard('name')"
            />
          </div>

          <div>
            <label class="label" for="contact-phone">Phone number</label>
            <input
              id="contact-phone"
              v-model="form.phone"
              class="field"
              :class="activeField === 'phone' ? 'ring-2 ring-electric-400' : ''"
              type="tel"
              inputmode="tel"
              autocomplete="tel"
              placeholder="Tap to type"
              @focus="openKeyboard('phone')"
            />
          </div>
        </div>

        <div class="flex flex-wrap gap-3 mt-4">
          <button
            class="btn-ghost"
            :aria-pressed="!!activeField"
            @click="activeField ? (activeField = '') : openKeyboard('name')"
          >
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="6" width="20" height="12" rx="2"/><path d="M6 10h.01M10 10h.01M14 10h.01M18 10h.01M6 14h12" stroke-linecap="round"/></svg>
            {{ activeField ? 'Hide keyboard' : 'Keyboard' }}
          </button>

          <button class="btn-accent" :disabled="listening" @click="speak">
            <span v-if="listening" class="relative flex h-3 w-3">
              <span class="absolute inline-flex h-full w-full rounded-full bg-white/70 animate-ping"></span>
              <span class="relative inline-flex rounded-full h-3 w-3 bg-white"></span>
            </span>
            <svg v-else width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3Z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2M12 19v4"/></svg>
            {{ listening ? 'Listening…' : 'Speak it' }}
          </button>
        </div>

        <p v-if="status" class="hint mt-3" aria-live="polite">{{ status }}</p>
        <p v-if="error" class="hint text-red-300 mt-3" role="alert">{{ error }}</p>

        <transition name="fade">
          <div v-if="activeField" class="mt-4">
            <VirtualKeyboard
              :layout="keyboardLayout"
              @key="onKey"
              @backspace="onBackspace"
              @close="activeField = ''"
            />
          </div>
        </transition>

        <div class="mt-5 grid grid-cols-2 gap-3">
          <button class="btn-ghost" @click="emit('close')">Cancel</button>
          <button class="btn-primary" :disabled="!canSubmit" @click="submit">
            <span v-if="saving" class="h-4 w-4 rounded-full border-2 border-ink-950 border-t-transparent animate-spin"></span>
            Send
          </button>
        </div>
      </template>
    </div>
  </div>
</template>

<style scoped>
.fade-enter-active { transition: opacity 0.2s ease; }
.fade-leave-active { transition: opacity 0.12s ease; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
</style>
