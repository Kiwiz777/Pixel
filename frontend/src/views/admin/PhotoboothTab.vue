<script setup>
/**
 * Photobooth tab: AI-Enhance prompt, frame overlay (PNG) upload, and
 * CUPS printer settings (default printer, copies, media, colour, test print).
 */
import { computed, reactive, ref, watch, onMounted } from 'vue'
import { api } from '../../lib/api'

const props = defineProps({ settings: Object })
const emit = defineEmits(['save', 'reload'])

const form = reactive({
  ai_enhance_prompt: '',
  capture_countdown_seconds: 5,
  frame_overlay_display: 'both',
  print_copies: 1,
  print_media: '4x6.Borderless',
  print_color_mode: 'color',
  print_size_cm: '10x15',
  print_orientation: 'auto',
  print_dpi: 300,
  print_fit: 'cover',
})
const framePreview = ref('')
const printers = ref([])
const backend = ref('')
const defaultPrinter = ref('')
const msg = ref('')
const uploading = ref(false)

// Media names are printer-specific strings, so they come from the printer via
// /api/printer/media rather than being typed by hand.
const mediaOptions = ref([])
const mediaSource = ref('')
const customMedia = ref(false)

const PAPER_SIZES = ['10x15', '13x18', '15x21', '20x30']

// Pixel dimensions the photo will be cropped to - mirrors print_target_px()
// on the backend so the operator sees the real output before printing.
const targetPx = computed(() => {
  const parts = String(form.print_size_cm).split('x').map((n) => parseFloat(n))
  const [a, b] = parts.length === 2 && parts.every((n) => n > 0) ? parts : [10, 15]
  const [short, long] = [Math.min(a, b), Math.max(a, b)]
  const [wCm, hCm] = form.print_orientation === 'landscape' ? [long, short] : [short, long]
  const dpi = Number(form.print_dpi) || 300
  return `${Math.round((wCm / 2.54) * dpi)} × ${Math.round((hCm / 2.54) * dpi)} px`
})

watch(
  () => props.settings,
  (s) => {
    if (!s) return
    form.ai_enhance_prompt = s.ai_enhance_prompt ?? ''
    form.capture_countdown_seconds = s.capture_countdown_seconds ?? 5
    form.frame_overlay_display = s.frame_overlay_display ?? 'both'
    form.print_copies = s.print_copies ?? 1
    form.print_media = s.print_media ?? '4x6.Borderless'
    form.print_color_mode = s.print_color_mode ?? 'color'
    form.print_size_cm = s.print_size_cm ?? '10x15'
    form.print_orientation = s.print_orientation ?? 'auto'
    form.print_dpi = s.print_dpi ?? 300
    form.print_fit = s.print_fit ?? 'cover'
    framePreview.value = s.frame_overlay_path ? `/media/frames/${s.frame_overlay_path}?t=${Date.now()}` : ''
  },
  { immediate: true, deep: true },
)

async function loadPrinters() {
  try {
    const res = await api.printers()
    printers.value = res.printers
    backend.value = res.backend
    defaultPrinter.value = res.config.default_printer
    await loadMedia()
  } catch (e) {
    msg.value = e.message
  }
}

async function loadMedia() {
  try {
    const res = await api.printerMedia(defaultPrinter.value)
    mediaOptions.value = res.media || []
    mediaSource.value = res.source
    // Keep a hand-entered name usable if the printer doesn't advertise it.
    customMedia.value = !!form.print_media && !mediaOptions.value.includes(form.print_media)
  } catch (e) {
    msg.value = e.message
  }
}

async function uploadFrame(e) {
  const file = e.target.files?.[0]
  if (!file) return
  uploading.value = true
  msg.value = ''
  try {
    const res = await api.uploadFrame(file)
    framePreview.value = res.frame_url + `?t=${Date.now()}`
    emit('reload')
  } catch (err) {
    msg.value = err.message || 'Upload failed (PNG with transparency recommended).'
  } finally {
    uploading.value = false
  }
}

async function setDefault() {
  await api.setDefaultPrinter(defaultPrinter.value)
  msg.value = `Default printer set to ${defaultPrinter.value}.`
}

async function testPrint() {
  msg.value = 'Sending test page…'
  try {
    const res = await api.testPrint()
    msg.value = `Test sent · job ${res.job_id} (${res.backend}).`
  } catch (e) {
    msg.value = e.message
  }
}

function savePrompt() {
  emit('save', { ai_enhance_prompt: form.ai_enhance_prompt })
}

function saveCapture() {
  emit('save', {
    capture_countdown_seconds: Math.max(0, Math.min(30, Number(form.capture_countdown_seconds) || 0)),
    frame_overlay_display: form.frame_overlay_display,
  })
  msg.value = 'Capture settings saved.'
}

async function savePrintConfig() {
  try {
    await api.updatePrintConfig({
      copies: Number(form.print_copies),
      media: form.print_media,
      color_mode: form.print_color_mode,
      size_cm: form.print_size_cm,
      orientation: form.print_orientation,
      dpi: Number(form.print_dpi),
      fit: form.print_fit,
    })
    emit('reload')
    msg.value = 'Print settings saved.'
  } catch (e) {
    msg.value = e.message
  }
}

onMounted(loadPrinters)
</script>

<template>
  <section>
    <header class="mb-6">
      <h1 class="font-display text-3xl font-semibold">Photobooth</h1>
      <p class="text-slate-400 mt-1">AI enhancement, photo frame and printer setup.</p>
    </header>

    <!-- AI enhance prompt -->
    <div class="glass-card p-5 sm:p-6 mb-5">
      <h2 class="font-display text-lg font-semibold mb-3">AI Enhance Prompt</h2>
      <textarea v-model="form.ai_enhance_prompt" rows="3" class="field" placeholder="Describe how photos should be transformed…"></textarea>
      <p class="hint">Sent with every photo to the active image provider.</p>
      <div class="flex justify-end mt-3"><button class="btn-accent btn-sm" @click="savePrompt">Save prompt</button></div>
    </div>

    <!-- Frame overlay -->
    <div class="glass-card p-5 sm:p-6 mb-5">
      <h2 class="font-display text-lg font-semibold mb-3">Photo Frame (PNG overlay)</h2>
      <div class="flex flex-col sm:flex-row gap-5 items-start">
        <div class="w-40 h-40 rounded-2xl border border-dashed border-white/20 grid place-items-center bg-ink-900 overflow-hidden shrink-0"
             style="background-image: linear-gradient(45deg,#1a2335 25%,transparent 25%),linear-gradient(-45deg,#1a2335 25%,transparent 25%),linear-gradient(45deg,transparent 75%,#1a2335 75%),linear-gradient(-45deg,transparent 75%,#1a2335 75%); background-size:16px 16px; background-position:0 0,0 8px,8px -8px,-8px 0;">
          <img v-if="framePreview" :src="framePreview" alt="Current frame overlay" class="max-h-full max-w-full object-contain" />
          <span v-else class="hint text-center px-2">No frame set</span>
        </div>
        <div class="flex-1">
          <label class="btn-ghost cursor-pointer inline-flex">
            <input type="file" accept="image/png" class="hidden" @change="uploadFrame" />
            <span v-if="uploading" class="h-4 w-4 rounded-full border-2 border-white border-t-transparent animate-spin"></span>
            Upload PNG frame
          </label>
          <p class="hint">Use a transparent PNG sized to your photo's aspect ratio. The clear centre shows the photo; printed and on-screen previews use it automatically.</p>

          <div class="mt-4">
            <label class="label" for="frame-display">Show frame preview on</label>
            <select
              id="frame-display"
              v-model="form.frame_overlay_display"
              class="field max-w-xs"
              aria-describedby="frame-display-hint"
            >
              <option value="both">Live camera + photo review</option>
              <option value="capture">Live camera only</option>
              <option value="modal">Photo review only</option>
              <option value="none">Don't preview</option>
            </select>
            <p id="frame-display-hint" class="hint mt-1">
              Preview only — this doesn't change what gets printed.
            </p>
          </div>
        </div>
      </div>
    </div>

    <!-- Capture behaviour -->
    <div class="glass-card p-5 sm:p-6 mb-5">
      <h2 class="font-display text-lg font-semibold mb-3">Capture</h2>
      <div class="grid sm:grid-cols-2 gap-4">
        <div>
          <label class="label" for="countdown">Countdown before the shot</label>
          <div class="flex items-center gap-2">
            <input
              id="countdown"
              v-model.number="form.capture_countdown_seconds"
              type="number" min="0" max="30"
              class="field max-w-[8rem]"
              aria-describedby="countdown-hint"
            />
            <span class="hint !mt-0">seconds</span>
          </div>
          <p id="countdown-hint" class="hint mt-1">0 shoots immediately.</p>
        </div>
      </div>
      <p class="hint mt-3">
        With the camera off, the first tap of <span class="text-slate-200">Capture Photo</span>
        opens the viewfinder so guests can see their framing; the next tap starts the countdown.
      </p>
      <div class="flex justify-end mt-3">
        <button class="btn-accent btn-sm" @click="saveCapture">Save capture settings</button>
      </div>
    </div>

    <!-- Printer -->
    <div class="glass-card p-5 sm:p-6">
      <div class="flex items-center justify-between mb-3">
        <h2 class="font-display text-lg font-semibold">Printer (CUPS)</h2>
        <span class="text-xs glass rounded-full px-3 py-1">backend: {{ backend || '…' }}</span>
      </div>

      <div class="grid sm:grid-cols-2 gap-4">
        <div>
          <label class="label" for="printer">Default printer</label>
          <div class="flex gap-2">
            <select id="printer" v-model="defaultPrinter" class="field">
              <option value="">— none —</option>
              <option v-for="p in printers" :key="p.name" :value="p.name">
                {{ p.description || p.name }} ({{ p.state }})
              </option>
            </select>
            <button class="btn-ghost btn-sm shrink-0" @click="setDefault">Set</button>
          </div>
          <button class="hint hover:text-slate-200 mt-1" @click="loadPrinters">↻ Refresh list</button>
        </div>

        <div>
          <label class="label" for="copies">Copies</label>
          <input id="copies" v-model.number="form.print_copies" type="number" min="1" max="10" class="field max-w-[8rem]" />
        </div>

        <div>
          <label class="label" for="media">Media (CUPS)</label>
          <select
            v-if="!customMedia"
            id="media"
            v-model="form.print_media"
            class="field"
            aria-describedby="media-hint"
          >
            <option v-for="m in mediaOptions" :key="m" :value="m">{{ m }}</option>
          </select>
          <input
            v-else
            id="media"
            v-model="form.print_media"
            class="field"
            placeholder="4x6.Borderless"
            aria-describedby="media-hint"
          />
          <p id="media-hint" class="hint mt-1">
            <template v-if="customMedia">Typed manually.</template>
            <template v-else-if="mediaSource === 'fallback'">
              Printer reported none — showing common sizes.
            </template>
            <template v-else>Reported by the printer ({{ mediaSource }}).</template>
            <button class="underline hover:text-slate-200 ml-1" @click="customMedia = !customMedia">
              {{ customMedia ? 'Pick from list' : 'Enter manually' }}
            </button>
          </p>
        </div>

        <div>
          <label class="label" for="color">Colour mode</label>
          <select id="color" v-model="form.print_color_mode" class="field">
            <option value="color">Colour</option>
            <option value="monochrome">Black &amp; white</option>
          </select>
        </div>
      </div>

      <!-- Print geometry: the photo is cropped to this shape BEFORE it reaches
           CUPS, which is what stops CUPS auto-rotating it onto the paper. -->
      <h3 class="font-display text-sm font-semibold mt-6 mb-3 text-slate-300">Photo size &amp; orientation</h3>
      <div class="grid sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <div>
          <label class="label" for="paper">Paper (cm)</label>
          <select id="paper" v-model="form.print_size_cm" class="field">
            <option v-for="s in PAPER_SIZES" :key="s" :value="s">{{ s }} cm</option>
          </select>
        </div>

        <div>
          <label class="label" for="orientation">Orientation</label>
          <select id="orientation" v-model="form.print_orientation" class="field">
            <option value="auto">Auto — never crop</option>
            <option value="portrait">Portrait</option>
            <option value="landscape">Landscape</option>
          </select>
        </div>

        <div>
          <label class="label" for="dpi">Resolution</label>
          <select id="dpi" v-model.number="form.print_dpi" class="field">
            <option :value="300">300 DPI (photo)</option>
            <option :value="600">600 DPI (fine)</option>
          </select>
        </div>

        <div>
          <label class="label" for="fit">Fit</label>
          <select id="fit" v-model="form.print_fit" class="field" aria-describedby="fit-hint">
            <option value="cover">Crop to fill</option>
            <option value="contain">Fit with white border</option>
          </select>
        </div>
      </div>

      <p id="fit-hint" class="hint mt-3">
        <template v-if="form.print_orientation === 'auto'">
          The photo is sent exactly as shot and the printer scales it to the sheet,
          turning it sideways if that fills more paper. Nothing is ever cropped, so
          Fit and Resolution below don't apply. Frame overlays keep the camera's shape.
        </template>
        <template v-else>
          Output: <span class="text-slate-200">{{ targetPx }}</span>.
          <template v-if="form.print_fit === 'cover'">
            Crop to fill trims the sides of a wide photo — the kiosk preview is
            reshaped to match, so guests frame themselves for it.
          </template>
          <template v-else>Whole frame kept; unused paper prints white.</template>
          Frame overlays should match this shape.
        </template>
      </p>

      <div class="flex flex-wrap gap-3 mt-5">
        <button class="btn-primary" @click="savePrintConfig">Save print settings</button>
        <button class="btn-ghost" @click="testPrint">Test print</button>
      </div>
    </div>

    <p v-if="msg" class="hint mt-4" aria-live="polite">{{ msg }}</p>
  </section>
</template>
