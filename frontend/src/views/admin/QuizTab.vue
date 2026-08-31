<script setup>
/**
 * QuizTab - manage MCQ quizzes: questions, answers, pass score, reward config,
 * CSV import/export of the question bank, and which quiz is active on the kiosk.
 */
import { ref, reactive, computed, watch, onMounted } from 'vue'
import { api } from '../../lib/api'
import ToggleSwitch from '../../components/ToggleSwitch.vue'
import RewardFields from './RewardFields.vue'
import WheelStyleFields from './WheelStyleFields.vue'

const props = defineProps({ settings: Object })
const emit = defineEmits(['save'])

// Quiz-level kiosk setting (persisted via the shared settings store).
const kioskForm = reactive({ quiz_enabled: true })
// SMTP (for voucher email delivery). Password is a secret: sent only if typed.
const smtpForm = reactive({
  smtp_host: '', smtp_port: 587, smtp_user: '', smtp_from: '', smtp_tls: true,
})
const smtpPassword = ref('')
const smtpPasswordSet = ref(false)

// Global prize-wheel look — mirrors DEFAULT_SETTINGS.wheel_style in backend/database.py
// so the editor always has every field even against an older/partial saved value.
const DEFAULT_WHEEL_STYLE = {
  preset: 'brand', segment_style: 'glass',
  pointer_color: '#F97316', hub_color: '#1e293b', hub_accent_color: '#F97316',
  glow_color_1: '#F97316', glow_color_2: '#38BDF8', border_color: '#F8FAFC',
  label_font: 'body', label_color: '#F8FAFC',
  size_px: 340, preroll_ms: 2000, spin_ms: 5600, hold_ms: 1300,
  frame_image: '', background_image: '',
}
const wheelStyleForm = ref({ ...DEFAULT_WHEEL_STYLE })

watch(
  () => props.settings,
  (s) => {
    if (!s) return
    kioskForm.quiz_enabled = s.quiz_enabled ?? true
    smtpForm.smtp_host = s.smtp_host ?? ''
    smtpForm.smtp_port = s.smtp_port ?? 587
    smtpForm.smtp_user = s.smtp_user ?? ''
    smtpForm.smtp_from = s.smtp_from ?? ''
    smtpForm.smtp_tls = s.smtp_tls ?? true
    smtpPasswordSet.value = !!s.smtp_password__set
    wheelStyleForm.value = { ...DEFAULT_WHEEL_STYLE, ...(s.wheel_style || {}) }
  },
  { immediate: true, deep: true },
)
function saveKioskSettings() {
  emit('save', { ...kioskForm })
}
function saveSmtp() {
  const patch = { ...smtpForm, smtp_port: Number(smtpForm.smtp_port) || 587 }
  if (smtpPassword.value) patch.smtp_password = smtpPassword.value // blank = keep existing
  emit('save', patch)
  smtpPassword.value = ''
  smtpPasswordSet.value = smtpPasswordSet.value || !!patch.smtp_password
}
function saveWheelStyle() {
  emit('save', { wheel_style: wheelStyleForm.value })
}

const quizzes = ref([])
const activeId = ref(null)
const draft = ref(null) // reactive editable copy of the selected quiz
const selectedId = ref(null)
const loading = ref(false)
const saving = ref(false)
const importing = ref(false)
const msg = ref('')

const uid = (p) =>
  p + (crypto?.randomUUID?.().slice(0, 8) || Math.random().toString(36).slice(2, 10))

const totalAnswers = computed(() =>
  draft.value ? draft.value.questions.reduce((n, q) => n + q.answers.length, 0) : 0,
)

async function load() {
  loading.value = true
  try {
    const res = await api.listQuizzes()
    quizzes.value = res.quizzes
    activeId.value = res.active_quiz_id
    if (selectedId.value && !quizzes.value.find((q) => q.id === selectedId.value)) {
      draft.value = null
      selectedId.value = null
    }
  } catch (e) {
    msg.value = e.message
  } finally {
    loading.value = false
  }
}

function selectQuiz(q) {
  selectedId.value = q.id
  // Deep clone into an editable draft; normalise reward to an object.
  draft.value = reactive({
    id: q.id,
    title: q.title || '',
    description: q.description || '',
    pass_score: q.pass_score ?? 70,
    questions: (q.questions || []).map((qq) => ({
      id: qq.id || uid('q'),
      text: qq.text || '',
      type: qq.type === 'multi' ? 'multi' : 'single',
      answers: (qq.answers || []).map((a) => ({
        id: a.id || uid('a'),
        text: a.text || '',
        correct: !!a.correct,
      })),
    })),
    reward: q.reward && Object.keys(q.reward).length ? { ...q.reward } : { type: 'prints', photos_count: 1, prints_count: 1 },
  })
  msg.value = ''
}

async function newQuiz() {
  saving.value = true
  msg.value = ''
  try {
    const res = await api.createQuiz({ title: 'New quiz', pass_score: 70 })
    await load()
    selectQuiz(res.quiz)
  } catch (e) {
    msg.value = e.message
  } finally {
    saving.value = false
  }
}

async function saveQuiz() {
  if (!draft.value) return
  saving.value = true
  msg.value = ''
  try {
    const res = await api.updateQuiz(draft.value.id, {
      title: draft.value.title,
      description: draft.value.description,
      pass_score: Number(draft.value.pass_score),
      questions: draft.value.questions,
      reward: draft.value.reward,
    })
    msg.value = 'Quiz saved.'
    await load()
    if (res.quiz) selectQuiz(res.quiz)
  } catch (e) {
    msg.value = e.message
  } finally {
    saving.value = false
  }
}

async function removeQuiz(q) {
  if (!confirm(`Delete quiz “${q.title}”? This cannot be undone.`)) return
  try {
    await api.deleteQuiz(q.id)
    if (selectedId.value === q.id) {
      draft.value = null
      selectedId.value = null
    }
    await load()
  } catch (e) {
    msg.value = e.message
  }
}

async function activate(q) {
  try {
    await api.activateQuiz(q.id)
    await load()
    msg.value = `“${q.title}” is now live on the kiosk.`
  } catch (e) {
    msg.value = e.message
  }
}

async function resetUsage() {
  if (!draft.value) return
  if (!confirm('Reset used/remaining counts for this reward back to zero?')) return
  try {
    const res = await api.resetRewardUsage(draft.value.id)
    msg.value = 'Reward usage reset.'
    if (res.quiz) selectQuiz(res.quiz)
  } catch (e) {
    msg.value = e.message
  }
}

// ---- question editing ----------------------------------------------------
function addQuestion() {
  draft.value.questions.push({
    id: uid('q'),
    text: '',
    type: 'single',
    answers: [
      { id: uid('a'), text: '', correct: true },
      { id: uid('a'), text: '', correct: false },
    ],
  })
}
function removeQuestion(i) {
  draft.value.questions.splice(i, 1)
}
function addAnswer(q) {
  q.answers.push({ id: uid('a'), text: '', correct: false })
}
function removeAnswer(q, i) {
  q.answers.splice(i, 1)
}
function setCorrect(q, answer) {
  if (q.type === 'single') {
    q.answers.forEach((a) => (a.correct = a.id === answer.id))
  } else {
    answer.correct = !answer.correct
  }
}
function onTypeChange(q) {
  // Switching to single: keep only the first correct answer selected.
  if (q.type === 'single') {
    let seen = false
    q.answers.forEach((a) => {
      if (a.correct && !seen) seen = true
      else a.correct = false
    })
    if (!seen && q.answers[0]) q.answers[0].correct = true
  }
}

// ---- CSV -----------------------------------------------------------------
async function exportCsv() {
  try {
    const text = await api.exportQuizCsv(draft.value.id)
    const blob = new Blob([text], { type: 'text/csv' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `quiz-${draft.value.id}-questions.csv`
    a.click()
    URL.revokeObjectURL(url)
  } catch (e) {
    msg.value = e.message
  }
}
async function importCsv(e) {
  const file = e.target.files?.[0]
  if (!file || !draft.value) return
  importing.value = true
  msg.value = ''
  try {
    const res = await api.importQuizCsv(draft.value.id, file)
    msg.value = `Imported ${res.imported} question(s).`
    await load()
    if (res.quiz) selectQuiz(res.quiz)
  } catch (err) {
    msg.value = err.message || 'Import failed. Expected columns: question, type, answer, correct.'
  } finally {
    importing.value = false
    e.target.value = ''
  }
}

onMounted(load)
</script>

<template>
  <section>
    <header class="mb-6">
      <h1 class="font-display text-3xl font-semibold">Quiz</h1>
      <p class="text-slate-400 mt-1">Build MCQ quizzes, set the pass score and reward, and pick which one is live.</p>
    </header>

    <!-- Kiosk quiz behaviour -->
    <div class="glass-card p-5 sm:p-6 mb-5 divide-y divide-white/10">
      <ToggleSwitch
        v-model="kioskForm.quiz_enabled"
        label="Enable quiz on kiosk"
        hint="Show the 'Take the Quiz' button on the kiosk (only appears when a quiz is set active below)."
      />
      <div class="pt-4 flex justify-end">
        <button class="btn-accent btn-sm" @click="saveKioskSettings">Save</button>
      </div>
    </div>

    <!-- Prize wheel style (global — shared by every quiz's wheel reward) -->
    <div class="glass-card p-5 sm:p-6 mb-5">
      <h2 class="font-display text-lg font-semibold mb-1">Prize wheel style</h2>
      <p class="hint !mt-0 mb-4">Shared look for every quiz's spinning wheel. Segment colors are set per-reward below.</p>
      <WheelStyleFields v-model="wheelStyleForm" />
      <div class="pt-4 flex justify-end">
        <button class="btn-accent btn-sm" @click="saveWheelStyle">Save wheel style</button>
      </div>
    </div>

    <!-- Voucher email (SMTP) -->
    <div class="glass-card p-5 sm:p-6 mb-5">
      <div class="flex items-center justify-between mb-3">
        <h2 class="font-display text-lg font-semibold">Voucher email (SMTP)</h2>
        <span class="text-xs glass rounded-full px-3 py-1">{{ smtpForm.smtp_host ? 'configured' : 'not set' }}</span>
      </div>
      <p class="hint !mt-0 mb-4">Only needed for voucher rewards set to “Send by email”. Left blank, those wins are logged and the guest is told it’ll be emailed.</p>
      <div class="grid sm:grid-cols-2 gap-4">
        <div>
          <label class="label" for="smtphost">SMTP host</label>
          <input id="smtphost" v-model="smtpForm.smtp_host" class="field" placeholder="smtp.gmail.com" />
        </div>
        <div>
          <label class="label" for="smtpport">Port</label>
          <input id="smtpport" v-model.number="smtpForm.smtp_port" type="number" class="field max-w-[8rem]" />
        </div>
        <div>
          <label class="label" for="smtpuser">Username</label>
          <input id="smtpuser" v-model="smtpForm.smtp_user" class="field" autocomplete="off" />
        </div>
        <div>
          <label class="label" for="smtppass">Password</label>
          <input id="smtppass" v-model="smtpPassword" type="password" class="field" autocomplete="new-password"
                 :placeholder="smtpPasswordSet ? '•••••••• (leave blank to keep)' : ''" />
        </div>
        <div>
          <label class="label" for="smtpfrom">From address</label>
          <input id="smtpfrom" v-model="smtpForm.smtp_from" class="field" placeholder="Pixel <booth@example.com>" />
        </div>
        <div class="flex items-end">
          <ToggleSwitch v-model="smtpForm.smtp_tls" label="Use STARTTLS" hint="Recommended for port 587." />
        </div>
      </div>
      <div class="pt-4 flex justify-end">
        <button class="btn-accent btn-sm" @click="saveSmtp">Save email settings</button>
      </div>
    </div>

    <div class="grid lg:grid-cols-[18rem_1fr] gap-5">
      <!-- Quiz list -->
      <aside class="glass-card p-4 h-max">
        <div class="flex items-center justify-between mb-3">
          <h2 class="font-display font-semibold">Quizzes</h2>
          <button class="btn-accent btn-sm" :disabled="saving" @click="newQuiz">+ New</button>
        </div>
        <p v-if="loading" class="hint">Loading…</p>
        <p v-else-if="!quizzes.length" class="hint">No quizzes yet. Create one to get started.</p>
        <ul class="space-y-1.5">
          <li v-for="q in quizzes" :key="q.id">
            <button
              class="w-full text-left rounded-xl px-3 py-2.5 transition-colors border"
              :class="selectedId === q.id
                ? 'bg-brand-500/15 border-brand-400/30 text-brand-100'
                : 'border-white/10 hover:bg-white/5'"
              @click="selectQuiz(q)"
            >
              <div class="flex items-center justify-between gap-2">
                <span class="font-display font-medium truncate">{{ q.title || 'Untitled' }}</span>
                <span
                  v-if="activeId === q.id"
                  class="shrink-0 text-[10px] font-semibold rounded-full bg-emerald-500/20 text-emerald-300 px-2 py-0.5"
                >LIVE</span>
              </div>
              <p class="hint !mt-0.5">{{ q.questions.length }} question(s) · pass {{ q.pass_score }}%</p>
            </button>
          </li>
        </ul>
      </aside>

      <!-- Editor -->
      <div v-if="draft" class="space-y-5">
        <!-- Meta + activation -->
        <div class="glass-card p-5 sm:p-6">
          <div class="flex flex-wrap items-center justify-between gap-3 mb-4">
            <h2 class="font-display text-lg font-semibold">Quiz details</h2>
            <div class="flex items-center gap-2">
              <span
                v-if="activeId === draft.id"
                class="text-xs font-semibold rounded-full bg-emerald-500/20 text-emerald-300 px-3 py-1"
              >Live on kiosk</span>
              <button v-else class="btn-ghost btn-sm" @click="activate(draft)">Make active</button>
              <button class="btn-ghost btn-sm text-red-300" @click="removeQuiz(draft)">Delete</button>
            </div>
          </div>

          <div class="grid sm:grid-cols-2 gap-4">
            <div>
              <label class="label" for="qtitle">Title</label>
              <input id="qtitle" v-model="draft.title" class="field" placeholder="Movie Trivia" />
            </div>
            <div>
              <label class="label" for="qpass">Pass score (%)</label>
              <input id="qpass" v-model.number="draft.pass_score" type="number" min="0" max="100" class="field max-w-[8rem]" />
            </div>
          </div>
          <div class="mt-4">
            <label class="label" for="qdesc">Description (optional)</label>
            <input id="qdesc" v-model="draft.description" class="field" placeholder="Shown on the quiz intro screen" />
          </div>
        </div>

        <!-- Questions -->
        <div class="glass-card p-5 sm:p-6">
          <div class="flex items-center justify-between mb-4">
            <div>
              <h2 class="font-display text-lg font-semibold">Questions</h2>
              <p class="hint !mt-0.5">{{ draft.questions.length }} question(s) · {{ totalAnswers }} answer(s)</p>
            </div>
            <div class="flex items-center gap-2">
              <label class="btn-ghost btn-sm cursor-pointer inline-flex">
                <input type="file" accept=".csv,text/csv" class="hidden" @change="importCsv" />
                <span v-if="importing" class="h-4 w-4 rounded-full border-2 border-white border-t-transparent animate-spin"></span>
                Import CSV
              </label>
              <button class="btn-ghost btn-sm" @click="exportCsv">Export CSV</button>
            </div>
          </div>

          <p v-if="!draft.questions.length" class="hint mb-3">No questions yet. Add one or import a CSV.</p>

          <div class="space-y-4">
            <div v-for="(q, qi) in draft.questions" :key="q.id" class="rounded-2xl border border-white/10 p-4 bg-white/[0.03]">
              <div class="flex items-start justify-between gap-3 mb-3">
                <span class="grid place-items-center h-7 w-7 shrink-0 rounded-lg bg-brand-500/20 text-brand-200 font-display text-sm">{{ qi + 1 }}</span>
                <input v-model="q.text" class="field flex-1" placeholder="Type the question…" />
                <select v-model="q.type" class="field max-w-[9rem]" @change="onTypeChange(q)">
                  <option value="single">Single answer</option>
                  <option value="multi">Multiple answers</option>
                </select>
                <button class="btn-ghost btn-sm text-red-300 shrink-0" @click="removeQuestion(qi)" aria-label="Remove question">✕</button>
              </div>

              <ul class="space-y-2 pl-10">
                <li v-for="(a, ai) in q.answers" :key="a.id" class="flex items-center gap-2.5">
                  <button
                    type="button"
                    class="shrink-0 h-6 w-6 grid place-items-center border transition-colors"
                    :class="[
                      q.type === 'single' ? 'rounded-full' : 'rounded-md',
                      a.correct ? 'bg-emerald-500 border-emerald-400 text-ink-950' : 'border-white/25 text-transparent hover:border-white/50',
                    ]"
                    :aria-pressed="a.correct"
                    :title="a.correct ? 'Correct answer' : 'Mark correct'"
                    @click="setCorrect(q, a)"
                  >
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><path d="M20 6 9 17l-5-5" stroke-linecap="round" stroke-linejoin="round"/></svg>
                  </button>
                  <input v-model="a.text" class="field flex-1" :placeholder="`Answer ${ai + 1}`" />
                  <button class="btn-ghost btn-sm text-slate-400 shrink-0" :disabled="q.answers.length <= 1" @click="removeAnswer(q, ai)" aria-label="Remove answer">✕</button>
                </li>
              </ul>
              <button class="btn-ghost btn-sm mt-2 ml-10" @click="addAnswer(q)">+ Add answer</button>
            </div>
          </div>

          <button class="btn-primary btn-sm mt-4" @click="addQuestion">+ Add question</button>
          <p class="hint mt-2">Green tick marks the correct answer(s). Single-answer questions use radios; multiple-answer questions use checkboxes.</p>
        </div>

        <!-- Reward -->
        <div class="glass-card p-5 sm:p-6">
          <div class="flex items-start justify-between gap-3 mb-1">
            <h2 class="font-display text-lg font-semibold">Reward for passing</h2>
            <button class="btn-ghost btn-sm shrink-0" @click="resetUsage">Reset usage counts</button>
          </div>
          <p class="hint mb-4">Given when a guest scores at or above the pass score. Set a max uses limit to cap how many times a reward (or wheel segment) can be won.</p>
          <RewardFields v-model="draft.reward" :allow-wheel="true" />
        </div>

        <!-- Save bar -->
        <div class="flex items-center justify-end gap-3 sticky bottom-0 py-3">
          <span v-if="msg" class="hint mr-auto" aria-live="polite">{{ msg }}</span>
          <button class="btn-primary" :disabled="saving" @click="saveQuiz">
            <span v-if="saving" class="h-4 w-4 rounded-full border-2 border-ink-950 border-t-transparent animate-spin"></span>
            Save quiz
          </button>
        </div>
      </div>

      <!-- Empty state -->
      <div v-else class="glass-card p-8 grid place-items-center text-center">
        <div>
          <div class="mx-auto mb-3 h-12 w-12 rounded-2xl glass grid place-items-center text-2xl">🎯</div>
          <p class="font-display text-lg">Select a quiz to edit</p>
          <p class="hint">or create a new one to start building questions.</p>
        </div>
      </div>
    </div>
  </section>
</template>
