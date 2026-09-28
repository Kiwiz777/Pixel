<script setup>
/**
 * Save & Share tab.
 *
 *  - Soft save: master toggle, auto-save toggle, and the Email / WhatsApp
 *    checkboxes. Each checkbox is disabled until its service is connected
 *    (SMTP verified by a real login / WhatsApp device linked), so the kiosk
 *    can never offer an option that will fail.
 *  - Email service (SMTP): shared with quiz voucher emails.
 *  - Saved photos: browse the dated folders on the device.
 */
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { api } from '../../lib/api'
import ToggleSwitch from '../../components/ToggleSwitch.vue'

const props = defineProps({ settings: Object })
const emit = defineEmits(['save', 'reload'])

const form = reactive({
  soft_save_enabled: false,
  soft_save_auto: false,
  soft_save_email: false,
  soft_save_whatsapp: false,
})
const smtpForm = reactive({
  smtp_host: '', smtp_port: 587, smtp_user: '', smtp_from: '', smtp_tls: true,
  share_email_subject: '', share_email_body: '',
})
const smtpPassword = ref('')
const smtpPasswordSet = ref(false)

const status = ref(null) // /api/share/status
const testing = ref(false)
const emailMsg = ref({ kind: '', text: '' })

watch(
  () => props.settings,
  (s) => {
    if (!s) return
    for (const k of Object.keys(form)) form[k] = !!s[k]
    for (const k of Object.keys(smtpForm)) smtpForm[k] = s[k] ?? smtpForm[k]
    smtpPasswordSet.value = !!s.smtp_password__set
  },
  { immediate: true, deep: true },
)

const emailReady = computed(() => !!status.value?.email?.verified)
const waReady = computed(() => !!status.value?.whatsapp?.connected)
const emailReason = computed(() => {
  if (!status.value) return 'Checking…'
  if (!status.value.email.configured) return 'Set up the email service below first.'
  if (!status.value.email.verified) return 'Run “Test connection” below to enable.'
  return 'Email service connected.'
})
const waReason = computed(() => {
  const w = status.value?.whatsapp
  if (!w) return 'Checking…'
  if (!w.available) return 'WhatsApp support is not installed on this device.'
  if (!w.connected) return 'Link a WhatsApp account in the WhatsApp tab first.'
  return `Connected${w.me ? ` as +${w.me}` : ''}.`
})

// What the guest will actually see - spelled out so the combinations are obvious.
const kioskPreview = computed(() => {
  if (!form.soft_save_enabled) return 'Nothing — photos are not saved.'
  const opts = []
  if (form.soft_save_email && emailReady.value) opts.push('Email it')
  if (form.soft_save_whatsapp && waReady.value) opts.push('WhatsApp it')
  if (form.soft_save_auto) {
    return opts.length
      ? `Photos save automatically. Guests see: ${opts.join(' · ')}.`
      : 'Photos save automatically. No button is shown.'
  }
  return opts.length
    ? `A Save button with an arrow for: ${opts.join(' · ')}.`
    : 'A Save button.'
})

async function loadStatus() {
  try {
    status.value = await api.shareStatus()
  } catch {
    /* leave checkboxes disabled */
  }
}

function toggle(key, value) {
  form[key] = value
  emit('save', { [key]: value })
}

function saveSmtp() {
  const patch = { ...smtpForm, smtp_port: Number(smtpForm.smtp_port) || 587 }
  if (smtpPassword.value) patch.smtp_password = smtpPassword.value // blank = keep existing
  emit('save', patch)
  smtpPassword.value = ''
  smtpPasswordSet.value = smtpPasswordSet.value || !!patch.smtp_password
  // Any SMTP change clears the verified flag server-side; reflect it.
  setTimeout(loadStatus, 400)
}

async function testEmail() {
  testing.value = true
  emailMsg.value = { kind: '', text: '' }
  try {
    await api.emailTest()
    emailMsg.value = { kind: 'ok', text: 'Connected and logged in. Email is now available on the kiosk.' }
  } catch (e) {
    emailMsg.value = { kind: 'error', text: e.message }
  } finally {
    testing.value = false
    loadStatus()
  }
}

// ---- saved photos --------------------------------------------------------
const gallery = ref({ folder: '', days: [], day: null, photos: [] })
async function loadPhotos(day) {
  try {
    gallery.value = await api.savedPhotos(day)
  } catch {
    /* empty gallery */
  }
}

onMounted(() => {
  loadStatus()
  loadPhotos()
})
</script>

<template>
  <section>
    <header class="mb-6">
      <h1 class="font-display text-3xl font-semibold">Save &amp; Share</h1>
      <p class="text-slate-400 mt-1">Keep guests' photos on this device and send them by email or WhatsApp.</p>
    </header>

    <!-- Soft save -->
    <div class="glass-card p-5 sm:p-6 mb-5">
      <h2 class="font-display text-lg font-semibold mb-2">Soft save</h2>
      <ToggleSwitch
        :model-value="form.soft_save_enabled"
        label="Save photos to this device"
        :hint="`Saved as <date>/<date>_<time>.jpg in ${status?.photos_dir || 'the photos folder'}.`"
        @update:model-value="toggle('soft_save_enabled', $event)"
      />
      <div :class="form.soft_save_enabled ? '' : 'opacity-40 pointer-events-none'" :aria-disabled="!form.soft_save_enabled">
        <ToggleSwitch
          :model-value="form.soft_save_auto"
          label="Auto save"
          hint="Save every photo as soon as it's taken and hide the Save button. Enabled send options still show."
          @update:model-value="toggle('soft_save_auto', $event)"
        />

        <p class="label mt-4">Also offer guests</p>
        <div class="grid sm:grid-cols-2 gap-3">
          <label
            v-for="opt in [
              { key: 'soft_save_email', title: 'Send by email', ready: emailReady, reason: emailReason },
              { key: 'soft_save_whatsapp', title: 'Send on WhatsApp', ready: waReady, reason: waReason },
            ]"
            :key="opt.key"
            class="flex items-start gap-3 rounded-2xl border px-4 py-3 transition-colors"
            :class="opt.ready ? 'border-white/10 hover:bg-white/5 cursor-pointer' : 'border-white/5 cursor-not-allowed'"
          >
            <input
              type="checkbox"
              class="mt-1 h-5 w-5 accent-brand-500"
              :checked="form[opt.key]"
              :disabled="!opt.ready"
              @change="toggle(opt.key, $event.target.checked)"
            />
            <span>
              <span class="font-display" :class="opt.ready ? 'text-slate-100' : 'text-slate-500'">{{ opt.title }}</span>
              <span class="hint block" :class="opt.ready ? 'text-emerald-300/80' : ''">{{ opt.reason }}</span>
              <span v-if="form[opt.key] && !opt.ready" class="hint block text-amber-300">
                Checked, but hidden on the kiosk until the service is connected.
              </span>
            </span>
          </label>
        </div>
      </div>

      <div class="mt-4 rounded-2xl bg-ink-900/60 border border-white/10 px-4 py-3">
        <p class="hint !mt-0 uppercase tracking-wide">Guests will see</p>
        <p class="text-slate-100 mt-0.5">{{ kioskPreview }}</p>
      </div>
    </div>

    <!-- Email service -->
    <div class="glass-card p-5 sm:p-6 mb-5">
      <div class="flex items-center justify-between mb-3 gap-3">
        <h2 class="font-display text-lg font-semibold">Email service (SMTP)</h2>
        <span
          class="text-xs rounded-full px-3 py-1 border"
          :class="emailReady ? 'border-emerald-400/40 text-emerald-300 bg-emerald-500/10' : 'border-white/10 text-slate-400'"
        >{{ emailReady ? 'connected' : status?.email?.configured ? 'not verified' : 'not set' }}</span>
      </div>
      <p class="hint !mt-0 mb-4">Used for photo emails and quiz voucher emails. After saving, run Test connection — the kiosk only offers email once a login succeeds.</p>
      <div class="grid sm:grid-cols-2 gap-4">
        <div>
          <label class="label" for="smtphost">SMTP host</label>
          <input id="smtphost" v-model="smtpForm.smtp_host" class="field" placeholder="smtp.gmail.com" />
        </div>
        <div>
          <label class="label" for="smtpport">Port</label>
          <input id="smtpport" v-model.number="smtpForm.smtp_port" type="number" class="field max-w-[8rem]" aria-describedby="smtpport-hint" />
          <p id="smtpport-hint" class="hint">587 = STARTTLS · 465 = SSL</p>
        </div>
        <div>
          <label class="label" for="smtpuser">Username</label>
          <input id="smtpuser" v-model="smtpForm.smtp_user" class="field" autocomplete="off" />
        </div>
        <div>
          <label class="label" for="smtppass">Password</label>
          <input id="smtppass" v-model="smtpPassword" type="password" class="field" autocomplete="new-password"
                 :placeholder="smtpPasswordSet ? '•••••••• (leave blank to keep)' : 'App password'" />
        </div>
        <div>
          <label class="label" for="smtpfrom">From address</label>
          <input id="smtpfrom" v-model="smtpForm.smtp_from" class="field" placeholder="Pixel <booth@example.com>" />
        </div>
        <div class="flex items-end">
          <ToggleSwitch v-model="smtpForm.smtp_tls" label="Use STARTTLS" hint="Recommended for port 587." />
        </div>
        <div class="sm:col-span-2">
          <label class="label" for="mailsubj">Photo email subject</label>
          <input id="mailsubj" v-model="smtpForm.share_email_subject" class="field" />
        </div>
        <div class="sm:col-span-2">
          <label class="label" for="mailbody">Photo email message</label>
          <textarea id="mailbody" v-model="smtpForm.share_email_body" rows="4" class="field"></textarea>
          <p class="hint">The photo is attached.</p>
        </div>
      </div>
      <p
        v-if="emailMsg.text"
        class="hint mt-3"
        :class="emailMsg.kind === 'error' ? 'text-red-300' : 'text-emerald-300'"
        :role="emailMsg.kind === 'error' ? 'alert' : 'status'"
      >{{ emailMsg.text }}</p>
      <div class="pt-4 flex flex-wrap justify-end gap-3">
        <button class="btn-ghost btn-sm" :disabled="testing || !smtpForm.smtp_host" @click="testEmail">
          <span v-if="testing" class="h-4 w-4 rounded-full border-2 border-white border-t-transparent animate-spin"></span>
          Test connection
        </button>
        <button class="btn-accent btn-sm" @click="saveSmtp">Save email settings</button>
      </div>
    </div>

    <!-- Saved photos -->
    <div class="glass-card p-5 sm:p-6">
      <div class="flex flex-wrap items-center justify-between gap-3 mb-3">
        <h2 class="font-display text-lg font-semibold">Saved photos</h2>
        <div class="flex items-center gap-2">
          <select
            v-if="gallery.days.length"
            class="field !py-1.5 max-w-[11rem]"
            aria-label="Day"
            :value="gallery.day"
            @change="loadPhotos($event.target.value)"
          >
            <option v-for="d in gallery.days" :key="d" :value="d">{{ d }}</option>
          </select>
          <button class="btn-ghost btn-sm" @click="loadPhotos(gallery.day)">↻ Refresh</button>
        </div>
      </div>
      <p class="hint !mt-0 mb-4">Folder on the device: <span class="text-slate-200 break-all">{{ gallery.folder }}</span></p>
      <p v-if="!gallery.photos.length" class="hint">No saved photos yet.</p>
      <ul v-else class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
        <li v-for="p in gallery.photos" :key="p.file">
          <a
            :href="api.savedPhotoUrl(p.file)"
            :download="p.name"
            class="block rounded-2xl overflow-hidden border border-white/10 hover:border-electric-400/60 transition-colors"
          >
            <img :src="api.savedPhotoUrl(p.file)" :alt="p.name" loading="lazy" class="aspect-[4/3] w-full object-cover bg-ink-900" />
            <span class="block px-2.5 py-1.5 text-xs text-slate-400 truncate">{{ p.name }}</span>
          </a>
        </li>
      </ul>
    </div>
  </section>
</template>
