<script setup>
/**
 * WhatsApp tab - link the booth to a WhatsApp account as a linked device
 * (QR scan, like WhatsApp Web) and tune the anti-ban send limits.
 *
 * Backend: whatsapp.py (neonize). Status is polled while this tab is open
 * so the QR refreshes (WhatsApp rotates it every ~20s) and "connected"
 * appears the moment the phone scans it.
 */
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { api } from '../../lib/api'
import ToggleSwitch from '../../components/ToggleSwitch.vue'

const props = defineProps({ settings: Object })
const emit = defineEmits(['save'])

const wa = ref(null)
const busy = ref('')
const msg = ref({ kind: '', text: '' })
const testPhone = ref('')
let pollTimer = null

const form = reactive({
  whatsapp_share_mode: 'qr',
  whatsapp_code_ttl_s: 300,
  whatsapp_code_max_senders: 10,
  whatsapp_prefill_text: '',
  whatsapp_booth_number: '',
  whatsapp_captions: '',
  whatsapp_default_country_code: '',
  whatsapp_min_interval_s: 8,
  whatsapp_max_per_hour: 40,
  whatsapp_max_per_day: 200,
  whatsapp_max_per_recipient_day: 3,
  whatsapp_typing_indicator: true,
  whatsapp_verify_number: true,
})

watch(
  () => props.settings,
  (s) => {
    if (!s) return
    for (const k of Object.keys(form)) form[k] = s[k] ?? form[k]
  },
  { immediate: true, deep: true },
)

const STATE_LABEL = {
  unavailable: 'Not installed',
  stopped: 'Off',
  starting: 'Starting…',
  pairing: 'Waiting for scan',
  connected: 'Connected',
  error: 'Error',
}
const state = computed(() => wa.value?.state || 'stopped')
const running = computed(() => ['starting', 'pairing', 'connected'].includes(state.value))

async function refresh() {
  try {
    wa.value = await api.waStatus()
  } catch {
    /* keep last known */
  }
  // Fast while pairing (QR rotates), slow otherwise.
  clearTimeout(pollTimer)
  pollTimer = setTimeout(refresh, ['starting', 'pairing'].includes(state.value) ? 2000 : 8000)
}

async function run(kind, fn, okText) {
  busy.value = kind
  msg.value = { kind: '', text: '' }
  try {
    const res = await fn()
    if (res && res.state) wa.value = res
    if (okText) msg.value = { kind: 'ok', text: okText }
  } catch (e) {
    msg.value = { kind: 'error', text: e.message }
  } finally {
    busy.value = ''
    refresh()
  }
}

const connect = () => run('start', api.waStart)
const disconnect = () => run('stop', api.waStop, 'Disconnected. The device stays linked — Connect resumes without a new scan.')
const unlink = () => run('logout', api.waLogout, 'Unlinked. Connect again to scan a new QR code.')
const sendTest = () => run('test', () => api.waTest(testPhone.value), 'Test photo sent — check the phone.')

function saveLimits() {
  emit('save', {
    ...form,
    whatsapp_min_interval_s: Math.max(3, Number(form.whatsapp_min_interval_s) || 8),
    whatsapp_max_per_hour: Math.max(0, Number(form.whatsapp_max_per_hour) || 0),
    whatsapp_max_per_day: Math.max(0, Number(form.whatsapp_max_per_day) || 0),
    whatsapp_max_per_recipient_day: Math.max(0, Number(form.whatsapp_max_per_recipient_day) || 0),
    whatsapp_default_country_code: String(form.whatsapp_default_country_code).replace(/\D/g, ''),
    whatsapp_code_ttl_s: Math.max(60, Number(form.whatsapp_code_ttl_s) || 300),
    whatsapp_code_max_senders: Math.max(1, Number(form.whatsapp_code_max_senders) || 10),
    whatsapp_booth_number: String(form.whatsapp_booth_number).replace(/\D/g, ''),
  })
}

const prefillMissingCode = computed(() => !String(form.whatsapp_prefill_text).includes('{code}'))

onMounted(refresh)
onBeforeUnmount(() => clearTimeout(pollTimer))
</script>

<template>
  <section>
    <header class="mb-6">
      <h1 class="font-display text-3xl font-semibold">WhatsApp</h1>
      <p class="text-slate-400 mt-1">Send guests their photo on WhatsApp from a linked account.</p>
    </header>

    <!-- Connection -->
    <div class="glass-card p-5 sm:p-6 mb-5">
      <div class="flex items-center justify-between gap-3 mb-4">
        <h2 class="font-display text-lg font-semibold">Linked device</h2>
        <span
          class="text-xs rounded-full px-3 py-1 border"
          :class="state === 'connected'
            ? 'border-emerald-400/40 text-emerald-300 bg-emerald-500/10'
            : state === 'error' ? 'border-red-400/40 text-red-300 bg-red-500/10'
            : 'border-white/10 text-slate-300'"
        >{{ STATE_LABEL[state] || state }}</span>
      </div>

      <!-- Not installed -->
      <div v-if="wa && !wa.available">
        <p class="text-slate-200">WhatsApp support isn't installed on this device.</p>
        <p class="hint">
          It needs the <span class="text-slate-200">neonize</span> Python package (64-bit Python only), installed into
          the same Python that runs the backend. Then restart the backend. <code>--reload</code> doesn't pick up new packages.
        </p>
        <ul class="hint space-y-1 mt-2">
          <li>Windows dev: <code class="text-electric-300">backend\.venv\Scripts\python -m pip install neonize</code></li>
          <li>Pi from source: <code class="text-electric-300">.venv/bin/pip install -r requirements-pi.txt</code></li>
          <li>Pi compiled build: <code class="text-electric-300">sudo pip3 install --break-system-packages neonize</code> (install_pi.sh does this)</li>
        </ul>
      </div>

      <template v-else>
        <div class="flex flex-col sm:flex-row gap-6 items-start">
          <!-- QR / status visual -->
          <div class="w-56 h-56 shrink-0 rounded-2xl bg-white grid place-items-center overflow-hidden">
            <img v-if="state === 'pairing' && wa?.qr_svg" :src="wa.qr_svg" alt="WhatsApp pairing QR code" class="w-full h-full" />
            <div v-else-if="state === 'pairing' || state === 'starting'" class="text-center px-4 text-ink-950">
              <div class="mx-auto mb-3 h-8 w-8 rounded-full border-2 border-ink-950 border-t-transparent animate-spin"></div>
              <p class="text-sm">{{ wa?.qr && !wa?.qr_svg ? 'QR ready — install segno to display it' : 'Getting a QR code…' }}</p>
            </div>
            <div v-else-if="state === 'connected'" class="text-center px-4 text-ink-950">
              <svg class="mx-auto mb-2" width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="#059669" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>
              <p class="font-display">Linked</p>
              <p v-if="wa?.me" class="text-sm">+{{ wa.me }}</p>
            </div>
            <p v-else class="text-sm text-ink-950 px-6 text-center">Press Connect to show a QR code.</p>
          </div>

          <div class="flex-1 min-w-0">
            <ol v-if="state === 'pairing'" class="list-decimal ml-5 space-y-1 text-slate-200">
              <li>Open WhatsApp on the booth's phone.</li>
              <li>Settings → <span class="font-semibold">Linked devices</span> → Link a device.</li>
              <li>Scan this code. It refreshes by itself.</li>
            </ol>
            <p v-else-if="state === 'connected'" class="text-slate-200">
              Ready. Enable <span class="font-semibold">Send on WhatsApp</span> in Save &amp; Share to offer it on the kiosk.
            </p>
            <p v-else class="text-slate-300">
              Use a dedicated number for the booth, not a personal one.
              <template v-if="wa?.has_session"> A linked session exists — Connect resumes it without scanning.</template>
            </p>
            <p v-if="wa?.error" class="hint text-red-300 mt-2" role="alert">{{ wa.error }}</p>

            <div class="flex flex-wrap gap-3 mt-5">
              <button v-if="!running" class="btn-accent btn-sm" :disabled="!!busy" @click="connect">
                <span v-if="busy === 'start'" class="h-4 w-4 rounded-full border-2 border-white border-t-transparent animate-spin"></span>
                Connect
              </button>
              <button v-else class="btn-ghost btn-sm" :disabled="!!busy" @click="disconnect">Disconnect</button>
              <button v-if="wa?.has_session || running" class="btn-danger btn-sm" :disabled="!!busy" @click="unlink">
                Unlink device
              </button>
            </div>
          </div>
        </div>

        <!-- Test -->
        <div v-if="state === 'connected'" class="mt-6 pt-5 border-t border-white/10">
          <label class="label" for="watest">Send a test photo</label>
          <div class="flex flex-col sm:flex-row gap-2 max-w-lg">
            <input id="watest" v-model="testPhone" class="field" type="tel" placeholder="+20 10 1234 5678" />
            <button class="btn-ghost btn-sm shrink-0" :disabled="!!busy || !testPhone.trim()" @click="sendTest">
              <span v-if="busy === 'test'" class="h-4 w-4 rounded-full border-2 border-white border-t-transparent animate-spin"></span>
              Send test
            </button>
          </div>
          <p class="hint">Use your own number — someone who has messaged the booth before is safest.</p>
        </div>
      </template>

      <p
        v-if="msg.text"
        class="hint mt-4"
        :class="msg.kind === 'error' ? 'text-red-300' : 'text-emerald-300'"
        :role="msg.kind === 'error' ? 'alert' : 'status'"
      >{{ msg.text }}</p>
    </div>

    <!-- How guests get their photo -->
    <div class="glass-card p-5 sm:p-6 mb-5">
      <h2 class="font-display text-lg font-semibold mb-1">How guests get their photo</h2>
      <p class="hint !mt-0 mb-4">
        With a QR code, the guest messages the booth first and the booth replies with their photo.
        That's the safest way for the number. The booth only ever replies to a valid, unexpired
        photo code, with that photo. Every other message is ignored, including expired and
        unknown codes.
      </p>
      <div class="grid sm:grid-cols-2 gap-4">
        <div class="sm:col-span-2">
          <label class="label" for="wamode">Delivery</label>
          <select id="wamode" v-model="form.whatsapp_share_mode" class="field max-w-md">
            <option value="qr">Scan a QR code (recommended)</option>
            <option value="both">QR code, with "type my number" as a fallback</option>
            <option value="number">Type their number on the kiosk</option>
          </select>
        </div>
        <template v-if="form.whatsapp_share_mode !== 'number'">
          <div class="sm:col-span-2">
            <label class="label" for="waprefill">Message the guest sends</label>
            <input id="waprefill" v-model="form.whatsapp_prefill_text" class="field" aria-describedby="waprefill-hint" />
            <p id="waprefill-hint" class="hint" :class="prefillMissingCode ? 'text-amber-300' : ''">
              <template v-if="prefillMissingCode">No {code} placeholder, so the code will be added at the end.</template>
              <template v-else>{code} is replaced with the photo's one-time code.</template>
            </p>
          </div>
          <div>
            <label class="label" for="wattl">Code valid for (seconds)</label>
            <input id="wattl" v-model.number="form.whatsapp_code_ttl_s" type="number" min="60" class="field max-w-[8rem]" aria-describedby="wattl-hint" />
            <p id="wattl-hint" class="hint">Counted from when the QR code is shown.</p>
          </div>
          <div>
            <label class="label" for="wamaxs">Phones per code</label>
            <input id="wamaxs" v-model.number="form.whatsapp_code_max_senders" type="number" min="1" class="field max-w-[8rem]" aria-describedby="wamaxs-hint" />
            <p id="wamaxs-hint" class="hint">Lets friends in a group photo each get a copy.</p>
          </div>
          <div class="sm:col-span-2">
            <label class="label" for="wabooth">Booth number for the QR link</label>
            <input id="wabooth" v-model="form.whatsapp_booth_number" class="field max-w-xs" inputmode="numeric" :placeholder="wa?.me ? `${wa.me} (linked account)` : 'e.g. 201012345678'" aria-describedby="wabooth-hint" />
            <p id="wabooth-hint" class="hint">Leave blank to use the linked account's number. International format, digits only.</p>
          </div>
        </template>
      </div>
      <div class="pt-4 flex justify-end">
        <button class="btn-accent btn-sm" @click="saveLimits">Save WhatsApp settings</button>
      </div>
    </div>

    <!-- Message + anti-ban limits -->
    <div class="glass-card p-5 sm:p-6 mb-5">
      <h2 class="font-display text-lg font-semibold mb-1">Messages &amp; sending limits</h2>
      <p class="hint !mt-0 mb-4">WhatsApp flags accounts that send fast, identical, unsolicited messages. These limits keep the booth looking like a person.</p>

      <div class="grid sm:grid-cols-2 gap-4">
        <div class="sm:col-span-2">
          <label class="label" for="wacaps">Photo captions (one per line, a random one each time)</label>
          <textarea id="wacaps" v-model="form.whatsapp_captions" rows="4" class="field"></textarea>
        </div>
        <div v-if="form.whatsapp_share_mode !== 'qr'">
          <label class="label" for="wacc">Default country code</label>
          <div class="flex items-center gap-2">
            <span class="text-slate-400">+</span>
            <input id="wacc" v-model="form.whatsapp_default_country_code" class="field max-w-[7rem]" inputmode="numeric" placeholder="20" aria-describedby="wacc-hint" />
          </div>
          <p id="wacc-hint" class="hint">Numbers typed as 010… become +20 10…</p>
        </div>
        <div>
          <label class="label" for="wagap">Seconds between sends</label>
          <input id="wagap" v-model.number="form.whatsapp_min_interval_s" type="number" min="3" class="field max-w-[8rem]" aria-describedby="wagap-hint" />
          <p id="wagap-hint" class="hint">Plus 0–4 s of random jitter. Guests queue behind each other.</p>
        </div>
        <div>
          <label class="label" for="wahour">Max per hour</label>
          <input id="wahour" v-model.number="form.whatsapp_max_per_hour" type="number" min="0" class="field max-w-[8rem]" />
        </div>
        <div>
          <label class="label" for="waday">Max per day</label>
          <input id="waday" v-model.number="form.whatsapp_max_per_day" type="number" min="0" class="field max-w-[8rem]" />
        </div>
        <div>
          <label class="label" for="warcpt">Max per number per day</label>
          <input id="warcpt" v-model.number="form.whatsapp_max_per_recipient_day" type="number" min="0" class="field max-w-[8rem]" aria-describedby="warcpt-hint" />
          <p id="warcpt-hint" class="hint">0 = no limit (same for the two above).</p>
        </div>
      </div>

      <div class="mt-3">
        <ToggleSwitch v-if="form.whatsapp_share_mode !== 'qr'" v-model="form.whatsapp_verify_number" label="Check typed numbers are on WhatsApp first" hint="Messages to non-WhatsApp numbers are a strong spam signal." />
        <ToggleSwitch v-model="form.whatsapp_typing_indicator" label="Show “typing…” before sending" hint="Adds 1–3 s, but looks human." />
      </div>

      <div class="pt-4 flex justify-end">
        <button class="btn-accent btn-sm" @click="saveLimits">Save WhatsApp settings</button>
      </div>
    </div>

    <!-- Guidance -->
    <div class="glass-card p-5 sm:p-6">
      <h2 class="font-display text-lg font-semibold mb-3">Staying unbanned</h2>
      <ul class="space-y-2 text-slate-300 list-disc ml-5">
        <li>Use a dedicated number, with a profile photo and name, that has been active for a while.</li>
        <li>Prefer QR delivery: the guest writes first, so every photo is a reply rather than a cold message.</li>
        <li>The booth never messages anyone on its own and never answers anything except a live photo code.</li>
        <li>Put the number on a sign so guests can save it; replies from guests build trust.</li>
        <li>Keep the limits modest on a new number and raise them gradually.</li>
        <li>If the account gets logged out, unlink here and relink rather than retrying in a loop.</li>
      </ul>
      <p class="hint mt-3">This uses WhatsApp's linked-device protocol (like WhatsApp Web), not the official Business API, so it can't be made ban-proof — only low-risk.</p>
    </div>
  </section>
</template>
