<script setup>
import { reactive, watch } from 'vue'
import ToggleSwitch from '../../components/ToggleSwitch.vue'

const props = defineProps({ settings: Object, languages: Array })
const emit = defineEmits(['save'])

const form = reactive({
  face_recognition_enabled: true,
  auto_interact_mode: true,
  interact_button_visible: true,
  multilingual_autodetect: true,
  default_language: 'en',
  system_persona: '',
  dev_mode: false,
  bot_face_visible: true,
  // Camera behaviour (global kiosk settings)
  kiosk_camera_autostart: true,
  camera_off_after_session: false,
  camera_idle_off_seconds: 0,
})

watch(
  () => props.settings,
  (s) => s && Object.keys(form).forEach((k) => (form[k] = s[k] ?? form[k])),
  { immediate: true, deep: true },
)

function save() {
  emit('save', {
    ...form,
    camera_idle_off_seconds: Number(form.camera_idle_off_seconds) || 0,
  })
}
</script>

<template>
  <section>
    <header class="mb-6">
      <h1 class="font-display text-3xl font-semibold">General</h1>
      <p class="text-slate-400 mt-1">Control how Pixel greets and talks to guests.</p>
    </header>

    <div class="glass-card p-5 sm:p-6 divide-y divide-white/10">
      <ToggleSwitch
        v-model="form.face_recognition_enabled"
        label="Face Recognition"
        hint="Master switch for all camera face detection (kiosk dwell-watch + on-device recognition). Turn off to disable face features entirely — the kiosk still works via the buttons."
      />
      <ToggleSwitch
        v-model="form.auto_interact_mode"
        label="Auto-Interact Mode"
        hint="When a face is detected, Pixel greets the guest automatically. Requires Face Recognition to be on."
      />
      <ToggleSwitch
        v-model="form.interact_button_visible"
        label="Show 'Talk to Me' button"
        hint="Display the voice button on the kiosk so guests can start a chat."
      />
      <ToggleSwitch
        v-model="form.bot_face_visible"
        label="Show robot face animation"
        hint="Display the floating EMO-style robot face on the kiosk camera view."
      />
      <ToggleSwitch
        v-model="form.multilingual_autodetect"
        label="Multilingual Auto-Detect"
        hint="Detect the guest's spoken language and reply in it automatically."
      />

      <div class="py-4">
        <label class="label" for="lang">Default Language</label>
        <select id="lang" v-model="form.default_language" class="field max-w-xs" :disabled="form.multilingual_autodetect">
          <option v-for="l in languages" :key="l.code" :value="l.code">{{ l.label }} · {{ l.native }}</option>
        </select>
        <p class="hint">Used when auto-detect is off, or as a fallback.</p>
      </div>

      <ToggleSwitch
        v-model="form.dev_mode"
        label="Developer mode (recognition overlay)"
        hint="Show live face-detection boxes, recognised names and match distance on the kiosk camera."
      />

      <div class="py-4">
        <label class="label" for="persona">Bot Persona / System Prompt</label>
        <textarea id="persona" v-model="form.system_persona" rows="3" class="field" placeholder="You are Pixel, a cheerful multilingual photobooth robot…"></textarea>
        <p class="hint">Sets Pixel's personality and tone across every provider.</p>
      </div>
    </div>

    <div class="glass-card p-5 sm:p-6 mt-5 divide-y divide-white/10">
      <div class="pb-4">
        <h2 class="font-display text-lg font-semibold">Camera</h2>
        <p class="hint !mt-0.5">How the kiosk webcam powers on and off.</p>
      </div>
      <ToggleSwitch
        v-model="form.kiosk_camera_autostart"
        label="Start kiosk with the camera on"
        hint="When off, the kiosk opens on the buttons and starts the camera only when a guest taps Capture Photo (or wins a photo reward)."
      />
      <ToggleSwitch
        v-model="form.camera_off_after_session"
        label="Turn camera off after each photo session"
        hint="Powers the webcam back down once a capture/print session ends. Pair with the option above for a fully on-demand camera."
      />
      <div class="py-4">
        <label class="label" for="idleoff">Turn camera off after inactivity</label>
        <div class="flex items-center gap-2">
          <input id="idleoff" v-model.number="form.camera_idle_off_seconds" type="number" min="0" max="3600" class="field max-w-[8rem]" />
          <span class="hint !mt-0">seconds · 0 = never</span>
        </div>
        <p class="hint">The camera stops after this long with no taps or conversation. Any tap wakes it (or a guest presses Capture).</p>
      </div>
    </div>

    <div class="mt-5 flex justify-end">
      <button class="btn-primary" @click="save">Save changes</button>
    </div>
  </section>
</template>
