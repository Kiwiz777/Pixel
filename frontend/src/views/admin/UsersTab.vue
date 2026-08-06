<script setup>
/**
 * Users tab: enrol people the robot can recognise.
 *
 * Face enrolment is CLIENT-SIDE (face-api.js): we compute a 128-d descriptor
 * from a webcam snapshot or an uploaded photo right here in the browser, then
 * send that descriptor to the backend. This works on the laptop and the Pi
 * without server-side dlib.
 */
import { reactive, ref, onMounted, onBeforeUnmount } from 'vue'
import { api } from '../../lib/api'
import { useFaceId } from '../../composables/useFaceId'

defineProps({ languages: Array })

const faceId = useFaceId()
const users = ref([])
const loading = ref(true)
const msg = ref('')
const form = reactive({ name: '', bio: '', language: 'en', is_admin: false })
const submitting = ref(false)

// Enrolment state
const modelsReady = ref(false)
const videoEl = ref(null)
const camActive = ref(false)
const snapshotUrl = ref('') // preview of captured/selected face
const descriptor = ref(null) // Float32Array-as-Array
const faceBlob = ref(null) // thumbnail image to store
const enrollMsg = ref('')
let stream = null

async function load() {
  loading.value = true
  try {
    users.value = (await api.listUsers()).users
  } finally {
    loading.value = false
  }
}

async function ensureModels() {
  if (modelsReady.value) return
  enrollMsg.value = 'Loading face models…'
  await faceId.loadModels()
  modelsReady.value = true
  enrollMsg.value = ''
}

async function startCam() {
  await ensureModels()
  try {
    stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'user' }, audio: false })
    if (videoEl.value) {
      videoEl.value.srcObject = stream
      await videoEl.value.play().catch(() => {})
    }
    camActive.value = true
  } catch {
    enrollMsg.value = 'Could not open the camera.'
  }
}

function stopCam() {
  stream?.getTracks().forEach((t) => t.stop())
  stream = null
  camActive.value = false
}

async function captureFromCam() {
  if (!videoEl.value?.videoWidth) return
  enrollMsg.value = 'Detecting face…'
  const v = videoEl.value
  const canvas = document.createElement('canvas')
  canvas.width = v.videoWidth
  canvas.height = v.videoHeight
  canvas.getContext('2d').drawImage(v, 0, 0)
  const desc = await faceId.describe(v)
  if (!desc) {
    enrollMsg.value = 'No face found — center your face and try again.'
    return
  }
  descriptor.value = desc
  snapshotUrl.value = canvas.toDataURL('image/jpeg', 0.9)
  await new Promise((res) => canvas.toBlob((b) => ((faceBlob.value = b), res()), 'image/jpeg', 0.9))
  enrollMsg.value = 'Face captured ✓'
  stopCam()
}

async function onFile(e) {
  const file = e.target.files?.[0]
  if (!file) return
  await ensureModels()
  enrollMsg.value = 'Detecting face…'
  const img = await createImageBitmap(file)
  const desc = await faceId.describe(img)
  if (!desc) {
    enrollMsg.value = 'No face found in that image.'
    return
  }
  descriptor.value = desc
  faceBlob.value = file
  snapshotUrl.value = URL.createObjectURL(file)
  enrollMsg.value = 'Face captured ✓'
}

async function add() {
  if (!form.name.trim()) return
  submitting.value = true
  msg.value = ''
  try {
    const fd = new FormData()
    fd.append('name', form.name)
    fd.append('bio', form.bio)
    fd.append('language', form.language)
    fd.append('is_admin', form.is_admin ? 'true' : 'false')
    if (faceBlob.value) fd.append('face', faceBlob.value, 'face.jpg')
    if (descriptor.value) fd.append('face_descriptor', JSON.stringify(descriptor.value))
    const res = await api.addUser(fd)
    msg.value = res.face_enrolled
      ? `Added ${form.name} — face enrolled ✓`
      : `Added ${form.name} (no face — add a clear photo to enable recognition).`
    resetForm()
    await load()
  } catch (e) {
    msg.value = e.message
  } finally {
    submitting.value = false
  }
}

function resetForm() {
  form.name = ''
  form.bio = ''
  form.is_admin = false
  descriptor.value = null
  faceBlob.value = null
  snapshotUrl.value = ''
  enrollMsg.value = ''
}

async function remove(u) {
  if (!confirm(`Remove ${u.name}? This cannot be undone.`)) return
  await api.deleteUser(u.id)
  await load()
}

onMounted(load)
onBeforeUnmount(stopCam)
</script>

<template>
  <section>
    <header class="mb-6">
      <h1 class="font-display text-3xl font-semibold">Users</h1>
      <p class="text-slate-400 mt-1">Faces &amp; bios so Pixel can greet returning guests by name.</p>
    </header>

    <!-- Add user -->
    <div class="glass-card p-5 sm:p-6 mb-6">
      <h2 class="font-display text-lg font-semibold mb-4">Add a person</h2>
      <div class="grid sm:grid-cols-2 gap-4">
        <div>
          <label class="label" for="uname">Name</label>
          <input id="uname" v-model="form.name" class="field" placeholder="e.g. Layla" />
        </div>
        <div>
          <label class="label" for="ulang">Preferred language</label>
          <select id="ulang" v-model="form.language" class="field">
            <option v-for="l in languages" :key="l.code" :value="l.code">{{ l.label }}</option>
          </select>
        </div>
        <div class="sm:col-span-2">
          <label class="label" for="ubio">Bio / interests</label>
          <input id="ubio" v-model="form.bio" class="field" placeholder="Loves dad jokes; into football and coffee" />
        </div>
        <label class="sm:col-span-2 flex items-center gap-3 cursor-pointer">
          <input type="checkbox" v-model="form.is_admin" class="h-5 w-5 rounded accent-brand-500" />
          <span class="text-sm text-slate-300">Operator / admin user — Pixel will <b>recognise but not chat them up</b> (saves AI tokens).</span>
        </label>
      </div>

      <!-- Face enrolment -->
      <div class="mt-4 grid sm:grid-cols-[auto,1fr] gap-4 items-start">
        <div class="h-32 w-32 rounded-2xl overflow-hidden bg-ink-900 grid place-items-center shrink-0 border border-white/10">
          <video v-show="camActive" ref="videoEl" class="h-full w-full object-cover" style="transform: scaleX(-1)" autoplay playsinline muted></video>
          <img v-if="!camActive && snapshotUrl" :src="snapshotUrl" alt="Captured face" class="h-full w-full object-cover" />
          <span v-else-if="!camActive" class="hint text-center px-2">No face yet</span>
        </div>
        <div>
          <label class="label">Face (for recognition)</label>
          <div class="flex flex-wrap gap-2">
            <button v-if="!camActive" type="button" class="btn-ghost btn-sm" @click="startCam">Use camera</button>
            <button v-else type="button" class="btn-accent btn-sm" @click="captureFromCam">Capture face</button>
            <button v-if="camActive" type="button" class="btn-ghost btn-sm" @click="stopCam">Cancel</button>
            <label class="btn-ghost btn-sm cursor-pointer">
              <input type="file" accept="image/*" class="hidden" @change="onFile" />
              Upload photo
            </label>
          </div>
          <p class="hint">{{ enrollMsg || 'Capture a clear, front-facing face. Recognition runs in the browser.' }}</p>
        </div>
      </div>

      <div class="flex items-center justify-between mt-4">
        <p class="hint" aria-live="polite">{{ msg }}</p>
        <button class="btn-primary" :disabled="submitting || !form.name" @click="add">
          <span v-if="submitting" class="h-4 w-4 rounded-full border-2 border-ink-950 border-t-transparent animate-spin"></span>
          Add person
        </button>
      </div>
    </div>

    <!-- Users list -->
    <div v-if="loading" class="space-y-3">
      <div v-for="i in 3" :key="i" class="skeleton h-20"></div>
    </div>
    <div v-else-if="!users.length" class="glass-card p-10 text-center">
      <p class="font-display text-lg">No people yet</p>
      <p class="hint">Add someone above to start recognising returning guests.</p>
    </div>
    <ul v-else class="grid sm:grid-cols-2 gap-4">
      <li v-for="u in users" :key="u.id" class="glass-card p-4 flex gap-4 items-center">
        <div class="h-14 w-14 rounded-2xl overflow-hidden bg-ink-800 grid place-items-center shrink-0">
          <img v-if="u.face_image" :src="`/media/faces/${u.face_image}`" :alt="`${u.name} face`" class="h-full w-full object-cover" onerror="this.style.display='none'" />
          <span v-else class="font-display text-xl text-brand-300">{{ u.name.charAt(0) }}</span>
        </div>
        <div class="min-w-0 flex-1">
          <div class="flex items-center gap-2">
            <p class="font-display font-semibold truncate">{{ u.name }}</p>
            <span v-if="u.has_face" class="text-[10px] uppercase tracking-wide bg-emerald-500/15 text-emerald-300 px-2 py-0.5 rounded-full">face</span>
            <span v-if="u.is_admin" class="text-[10px] uppercase tracking-wide bg-brand-500/15 text-brand-300 px-2 py-0.5 rounded-full">admin</span>
          </div>
          <p class="hint !mt-0 truncate">{{ u.bio || '—' }}</p>
          <p class="text-xs text-slate-500">{{ u.language }} · seen {{ u.visit_count }}×</p>
        </div>
        <button class="btn-danger btn-sm shrink-0" @click="remove(u)" :aria-label="`Remove ${u.name}`">Remove</button>
      </li>
    </ul>
  </section>
</template>
