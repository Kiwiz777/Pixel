<script setup>
/**
 * Kiosk tab: customise the public screen's background — solid colour, a single
 * image, a looping video, or an image slideshow. Media is uploaded here and
 * the kiosk reads the active config from /api/settings/public.
 */
import { reactive, ref, watch, onMounted, computed } from 'vue'
import { api } from '../../lib/api'

const props = defineProps({ settings: Object })
const emit = defineEmits(['save'])

const MODES = [
  { id: 'none', label: 'Default (aurora)' },
  { id: 'color', label: 'Solid colour' },
  { id: 'image', label: 'Single image' },
  { id: 'video', label: 'Video' },
  { id: 'slideshow', label: 'Slideshow' },
]

const form = reactive({
  kiosk_bg_mode: 'none',
  kiosk_bg_color: '#070b16',
  kiosk_bg_slideshow_ms: 6000,
  kiosk_bg_dim: 35,
})
const media = ref([])
const uploading = ref(false)
const msg = ref('')

watch(
  () => props.settings,
  (s) => {
    if (!s) return
    Object.keys(form).forEach((k) => (form[k] = s[k] ?? form[k]))
  },
  { immediate: true, deep: true },
)

const images = computed(() => media.value.filter((m) => m.type === 'image'))

async function loadMedia() {
  try {
    media.value = (await api.listBackgrounds()).media
  } catch (e) {
    msg.value = e.message
  }
}

async function upload(e) {
  const file = e.target.files?.[0]
  if (!file) return
  uploading.value = true
  msg.value = ''
  try {
    await api.uploadBackground(file)
    await loadMedia()
  } catch (err) {
    msg.value = err.message || 'Upload failed.'
  } finally {
    uploading.value = false
    e.target.value = ''
  }
}

async function remove(m) {
  await api.deleteBackground(m.file)
  await loadMedia()
}

function save() {
  emit('save', {
    kiosk_bg_mode: form.kiosk_bg_mode,
    kiosk_bg_color: form.kiosk_bg_color,
    kiosk_bg_slideshow_ms: Number(form.kiosk_bg_slideshow_ms),
    kiosk_bg_dim: Number(form.kiosk_bg_dim),
  })
}

onMounted(loadMedia)
</script>

<template>
  <section>
    <header class="mb-6">
      <h1 class="font-display text-3xl font-semibold">Kiosk</h1>
      <p class="text-slate-400 mt-1">Set the background guests see behind the photobooth.</p>
    </header>

    <!-- Mode + options -->
    <div class="glass-card p-5 sm:p-6 mb-5">
      <label class="label" for="bgmode">Background mode</label>
      <select id="bgmode" v-model="form.kiosk_bg_mode" class="field max-w-xs">
        <option v-for="m in MODES" :key="m.id" :value="m.id">{{ m.label }}</option>
      </select>

      <div class="grid sm:grid-cols-2 gap-5 mt-5">
        <div v-if="form.kiosk_bg_mode === 'color'">
          <label class="label" for="bgcolor">Colour</label>
          <div class="flex items-center gap-3">
            <input id="bgcolor" v-model="form.kiosk_bg_color" type="color" class="h-11 w-16 rounded-lg bg-transparent border border-white/10 cursor-pointer" />
            <input v-model="form.kiosk_bg_color" class="field max-w-[10rem]" />
          </div>
        </div>

        <div v-if="form.kiosk_bg_mode === 'slideshow'">
          <label class="label" for="bgint">Slide duration (ms)</label>
          <input id="bgint" v-model.number="form.kiosk_bg_slideshow_ms" type="number" min="2000" step="500" class="field max-w-[10rem]" />
        </div>

        <div v-if="['image', 'video', 'slideshow'].includes(form.kiosk_bg_mode)">
          <label class="label" for="bgdim">Darken for legibility ({{ form.kiosk_bg_dim }}%)</label>
          <input id="bgdim" v-model.number="form.kiosk_bg_dim" type="range" min="0" max="80" class="w-full max-w-xs accent-brand-500" />
        </div>
      </div>

      <div class="flex justify-end mt-5">
        <button class="btn-primary" @click="save">Save background</button>
      </div>
    </div>

    <!-- Media library -->
    <div class="glass-card p-5 sm:p-6">
      <div class="flex items-center justify-between mb-4">
        <div>
          <h2 class="font-display text-lg font-semibold">Media library</h2>
          <p class="hint !mt-0">Images for single/slideshow, or a video for video mode.</p>
        </div>
        <label class="btn-ghost btn-sm cursor-pointer">
          <input type="file" accept="image/*,video/*" class="hidden" @change="upload" />
          <span v-if="uploading" class="h-4 w-4 rounded-full border-2 border-white border-t-transparent animate-spin"></span>
          Upload media
        </label>
      </div>

      <p v-if="!media.length" class="hint">No media yet. Upload images or a video to use above.</p>
      <ul v-else class="grid grid-cols-2 sm:grid-cols-3 gap-3">
        <li v-for="m in media" :key="m.file" class="relative group rounded-2xl overflow-hidden bg-ink-900 aspect-video">
          <img v-if="m.type === 'image'" :src="m.url" alt="" class="h-full w-full object-cover" />
          <video v-else :src="m.url" class="h-full w-full object-cover" muted></video>
          <span class="absolute top-2 left-2 text-[10px] uppercase tracking-wide bg-ink-950/70 px-2 py-0.5 rounded-full">{{ m.type }}</span>
          <button
            class="absolute top-2 right-2 btn-danger btn-sm opacity-0 group-hover:opacity-100 focus:opacity-100 transition"
            @click="remove(m)" :aria-label="`Delete ${m.file}`"
          >Delete</button>
        </li>
      </ul>
      <p v-if="msg" class="hint mt-3" aria-live="polite">{{ msg }}</p>
    </div>
  </section>
</template>
