<script setup>
/**
 * QuizModal - the kiosk MCQ experience.
 *
 * Flow: intro → one question per screen (radio/checkbox) with Next / Skip /
 * Cancel, Finish on the last → server-scored result. On a win it reveals the
 * reward (spinning the prize wheel when configured). Photo-based rewards emit
 * `reward` so the kiosk can launch a capture session; display rewards (image /
 * voucher) are shown here.
 */
import { ref, reactive, computed, onMounted } from 'vue'
import { api } from '../lib/api'
import PrizeWheel from './PrizeWheel.vue'

const props = defineProps({
  wheelStyle: { type: Object, default: () => ({}) }, // global wheel_style setting (Admin > Quiz > Wheel style)
})
const emit = defineEmits(['close', 'reward'])

const stage = ref('loading') // loading | intro | quiz | submitting | result | error
const quiz = ref(null)
const index = ref(0)
const answers = reactive({}) // qid -> array of answer ids
const result = ref(null)
const errorMsg = ref('')

// wheel spin
const spinning = ref(false)

// voucher delivery
const voucherEmailInput = ref('')
const voucherState = ref('idle') // idle | sending | sent | error
const voucherMsg = ref('')

const question = computed(() => quiz.value?.questions?.[index.value] || null)
const total = computed(() => quiz.value?.questions?.length || 0)
const isLast = computed(() => index.value >= total.value - 1)
const answeredCount = computed(() => Object.values(answers).filter((a) => a && a.length).length)

onMounted(async () => {
  try {
    const res = await api.activeQuiz()
    if (!res.quiz || !res.quiz.questions?.length) {
      errorMsg.value = 'No quiz is available right now.'
      stage.value = 'error'
      return
    }
    quiz.value = res.quiz
    stage.value = 'intro'
  } catch (e) {
    errorMsg.value = e.message || 'Could not load the quiz.'
    stage.value = 'error'
  }
})

function start() {
  Object.keys(answers).forEach((k) => delete answers[k])
  result.value = null
  spinning.value = false
  voucherState.value = 'idle'
  voucherMsg.value = ''
  voucherEmailInput.value = ''
  index.value = 0
  stage.value = 'quiz'
}

function isSelected(q, aId) {
  return (answers[q.id] || []).includes(aId)
}
function pick(q, aId) {
  if (q.type === 'multi') {
    const cur = answers[q.id] || []
    answers[q.id] = cur.includes(aId) ? cur.filter((x) => x !== aId) : [...cur, aId]
  } else {
    answers[q.id] = [aId]
  }
}

function primary() {
  if (isLast.value) finish()
  else index.value++
}
function skip() {
  if (question.value) answers[question.value.id] = []
  if (isLast.value) finish()
  else index.value++
}
function back() {
  if (index.value > 0) index.value--
}

async function finish() {
  stage.value = 'submitting'
  try {
    result.value = await api.submitQuiz(quiz.value.id, answers)
    // A prize wheel spins first; the reward reveal waits for it to settle.
    spinning.value = !!(result.value.passed && result.value.wheel_segments?.length)
    stage.value = 'result'
  } catch (e) {
    errorMsg.value = e.message || 'Could not submit the quiz.'
    stage.value = 'error'
  }
}

// Segment labels for the wheel (never codes — server already stripped them).
const wheelSegments = computed(() =>
  (result.value?.wheel_segments || []).map((s) => ({ label: rewardTitle(s), color: s.color })),
)

// ---- reward presentation -------------------------------------------------
const reward = computed(() => result.value?.reward || null)
const isPhotoReward = computed(() => ['prints', 'ai_enhance'].includes(reward.value?.type))
const isVoucher = computed(() => reward.value?.type === 'voucher')
const voucherDelivery = computed(() => reward.value?.delivery || 'show')

function rewardTitle(rw) {
  if (!rw) return ''
  switch (rw.type) {
    case 'prints': {
      const p = rw.photos_count ?? 1
      const c = rw.prints_count ?? 1
      return `${p} free photo${p > 1 ? 's' : ''}${c ? ` · ${c} print${c > 1 ? 's' : ''} each` : ''}`
    }
    case 'ai_enhance': {
      const n = rw.enhance_count ?? 1
      return `${n} AI-enhanced photo${n > 1 ? 's' : ''}`
    }
    case 'voucher':
      // Label/name only — never the code (matters on the spinning wheel).
      return rw.label || rw.voucher_text || 'A voucher'
    case 'image':
      return 'A special prize'
    default:
      return 'A prize'
  }
}

function claimPhoto() {
  emit('reward', reward.value)
  emit('close')
}

async function sendVoucherEmail() {
  const email = voucherEmailInput.value.trim()
  if (!email.includes('@')) {
    voucherState.value = 'error'
    voucherMsg.value = 'Enter a valid email address.'
    return
  }
  voucherState.value = 'sending'
  voucherMsg.value = ''
  try {
    const res = await api.voucherEmail(reward.value.label || '', reward.value.code || '', email)
    voucherState.value = 'sent'
    voucherMsg.value = res.sent
      ? `Sent! Check ${email} for your code.`
      : `We’ve got it — your code will be emailed to ${email}.`
  } catch (e) {
    voucherState.value = 'error'
    voucherMsg.value = e.message || 'Could not send the email.'
  }
}

async function printVoucher() {
  voucherState.value = 'sending'
  voucherMsg.value = ''
  try {
    await api.voucherPrint(reward.value.label || '', reward.value.code || '')
    voucherState.value = 'sent'
    voucherMsg.value = 'Your voucher is printing — grab it from the printer!'
  } catch (e) {
    voucherState.value = 'error'
    voucherMsg.value = e.message || 'Could not print the voucher.'
  }
}
</script>

<template>
  <div class="fixed inset-0 z-[60] grid place-items-center p-4" role="dialog" aria-modal="true">
    <div class="absolute inset-0 bg-ink-950/80 backdrop-blur-md"></div>

    <div class="modal glass-card relative w-full max-w-2xl p-6 sm:p-8">
      <!-- Loading -->
      <div v-if="stage === 'loading'" class="py-16 grid place-items-center">
        <div class="h-10 w-10 rounded-full border-2 border-electric-400 border-t-transparent animate-spin"></div>
      </div>

      <!-- Error / unavailable -->
      <div v-else-if="stage === 'error'" class="text-center py-8">
        <div class="mx-auto mb-4 h-14 w-14 rounded-2xl glass grid place-items-center text-2xl">🤖</div>
        <p class="font-display text-xl">{{ errorMsg }}</p>
        <button class="btn-primary mt-6" @click="emit('close')">Close</button>
      </div>

      <!-- Intro -->
      <div v-else-if="stage === 'intro'" class="text-center py-4">
        <div class="mx-auto mb-4 h-16 w-16 rounded-2xl bg-brand-500/20 grid place-items-center text-3xl">🎯</div>
        <h2 class="font-display text-3xl font-semibold">{{ quiz.title }}</h2>
        <p v-if="quiz.description" class="text-slate-300 mt-2 max-w-md mx-auto">{{ quiz.description }}</p>
        <p class="hint mt-3">{{ total }} question{{ total > 1 ? 's' : '' }} · score {{ quiz.pass_score }}% or more to win a reward.</p>
        <div class="flex justify-center gap-3 mt-7">
          <button class="btn-ghost text-lg px-6 py-3" @click="emit('close')">Not now</button>
          <button class="btn-primary text-lg px-7 py-3" @click="start">Start quiz</button>
        </div>
      </div>

      <!-- Question -->
      <div v-else-if="stage === 'quiz' && question">
        <!-- progress -->
        <div class="flex items-center justify-between mb-1">
          <span class="hint">Question {{ index + 1 }} of {{ total }}</span>
          <button class="hint hover:text-slate-200" @click="emit('close')">Cancel ✕</button>
        </div>
        <div class="h-1.5 rounded-full bg-white/10 overflow-hidden mb-6">
          <div class="h-full bg-brand-500 transition-all duration-300" :style="{ width: `${((index + 1) / total) * 100}%` }"></div>
        </div>

        <h2 class="font-display text-2xl font-semibold mb-1">{{ question.text || 'Question' }}</h2>
        <p class="hint mb-5">{{ question.type === 'multi' ? 'Select all that apply.' : 'Select one answer.' }}</p>

        <ul class="space-y-3">
          <li v-for="a in question.answers" :key="a.id">
            <button
              type="button"
              class="w-full flex items-center gap-3.5 text-left rounded-2xl border px-4 py-4 transition-colors"
              :class="isSelected(question, a.id)
                ? 'bg-brand-500/15 border-brand-400/50 text-white'
                : 'border-white/12 hover:bg-white/5 hover:border-white/25'"
              @click="pick(question, a.id)"
            >
              <span
                class="shrink-0 h-6 w-6 grid place-items-center border-2 transition-colors"
                :class="[
                  question.type === 'multi' ? 'rounded-md' : 'rounded-full',
                  isSelected(question, a.id) ? 'bg-brand-500 border-brand-400 text-ink-950' : 'border-white/40 text-transparent',
                ]"
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><path d="M20 6 9 17l-5-5" stroke-linecap="round" stroke-linejoin="round"/></svg>
              </span>
              <span class="text-lg">{{ a.text }}</span>
            </button>
          </li>
        </ul>

        <!-- controls -->
        <div class="flex items-center gap-3 mt-7">
          <button v-if="index > 0" class="btn-ghost" @click="back">← Back</button>
          <button class="btn-ghost ml-auto" @click="skip">Skip</button>
          <button class="btn-primary px-7" @click="primary">{{ isLast ? 'Finish' : 'Next →' }}</button>
        </div>
      </div>

      <!-- Submitting -->
      <div v-else-if="stage === 'submitting'" class="py-16 grid place-items-center text-center">
        <div class="h-10 w-10 rounded-full border-2 border-electric-400 border-t-transparent animate-spin mb-4"></div>
        <p class="font-display text-electric-300">Scoring your answers…</p>
      </div>

      <!-- Result -->
      <div v-else-if="stage === 'result'" class="text-center py-2">
        <!-- Passed -->
        <template v-if="result.passed">
          <div class="mx-auto mb-3 h-16 w-16 rounded-2xl bg-emerald-500/20 grid place-items-center text-3xl">🎉</div>
          <h2 class="font-display text-3xl font-semibold text-emerald-300">You won!</h2>
          <p v-if="!spinning" class="text-slate-300 mt-1">Score: {{ result.score }}% ({{ result.correct_count }}/{{ result.total }})</p>

          <!-- Prize wheel (only while spinning; fades out to reveal the reward) -->
          <transition name="wheel">
            <div v-if="spinning" class="mt-5 grid place-items-center">
              <PrizeWheel
                :segments="wheelSegments" :winner="result.wheel_index ?? -1"
                :theme="wheelStyle"
                :size="wheelStyle?.size_px || 340"
                :preroll-ms="wheelStyle?.preroll_ms ?? 2000"
                :spin-ms="wheelStyle?.spin_ms ?? 5600"
                :hold-ms="wheelStyle?.hold_ms ?? 1300"
                @done="spinning = false"
              />
              <p class="hint mt-2 animate-pulse">Spinning for your prize…</p>
            </div>
          </transition>

          <!-- Reward reveal -->
          <div v-if="!spinning" class="mt-5">
            <!-- image prize -->
            <div v-if="reward?.type === 'image'" class="rounded-2xl overflow-hidden bg-ink-900 max-w-md mx-auto">
              <img v-if="reward.image_path" :src="`/media/rewards/${reward.image_path}`" alt="Your prize" class="w-full object-contain" />
            </div>

            <!-- voucher -->
            <div v-else-if="isVoucher" class="glass rounded-2xl px-5 py-5 max-w-md mx-auto">
              <p class="hint">You won</p>
              <p class="font-display text-xl text-brand-200 mt-0.5">{{ rewardTitle(reward) }}</p>

              <!-- show code -->
              <div v-if="voucherDelivery === 'show'" class="mt-3">
                <p class="hint">Your code</p>
                <p class="font-display text-2xl tracking-widest text-white select-all">{{ reward.code }}</p>
              </div>

              <!-- email code -->
              <div v-else-if="voucherDelivery === 'email'" class="mt-4">
                <template v-if="voucherState !== 'sent'">
                  <label class="hint block mb-1.5">Enter your email and we’ll send your code:</label>
                  <div class="flex gap-2">
                    <input v-model="voucherEmailInput" type="email" class="field" placeholder="you@example.com" />
                    <button class="btn-primary shrink-0" :disabled="voucherState === 'sending'" @click="sendVoucherEmail">
                      <span v-if="voucherState === 'sending'" class="h-4 w-4 rounded-full border-2 border-ink-950 border-t-transparent animate-spin"></span>
                      Send
                    </button>
                  </div>
                </template>
                <p v-if="voucherMsg" class="hint mt-2" :class="voucherState === 'error' ? 'text-red-300' : 'text-emerald-300'">{{ voucherMsg }}</p>
              </div>

              <!-- print only -->
              <div v-else class="mt-4">
                <template v-if="voucherState !== 'sent'">
                  <p class="hint mb-2">Your code will be printed — no peeking! 😄</p>
                  <button class="btn-primary" :disabled="voucherState === 'sending'" @click="printVoucher">
                    <span v-if="voucherState === 'sending'" class="h-4 w-4 rounded-full border-2 border-ink-950 border-t-transparent animate-spin"></span>
                    🖨️ Print my voucher
                  </button>
                </template>
                <p v-if="voucherMsg" class="hint mt-2" :class="voucherState === 'error' ? 'text-red-300' : 'text-emerald-300'">{{ voucherMsg }}</p>
              </div>
            </div>

            <!-- out of stock: passed, but nothing left to give -->
            <div v-else-if="reward?.type === 'none'" class="glass rounded-2xl px-5 py-4 max-w-md mx-auto">
              <p class="text-slate-300">All our rewards have been claimed for now — thanks for playing!</p>
            </div>

            <!-- prints / ai_enhance / other -->
            <div v-else class="glass rounded-2xl px-5 py-4 max-w-md mx-auto">
              <p class="hint">Your reward</p>
              <p class="font-display text-xl text-brand-200 mt-0.5">{{ rewardTitle(reward) }}</p>
            </div>

            <div class="flex justify-center gap-3 mt-7">
              <button v-if="isPhotoReward" class="btn-primary text-lg px-7 py-3" @click="claimPhoto">
                📸 Take my photo
              </button>
              <button class="btn-ghost text-lg px-6 py-3" @click="emit('close')">
                {{ isPhotoReward ? 'Maybe later' : 'Done' }}
              </button>
            </div>
          </div>
        </template>

        <!-- Failed -->
        <template v-else>
          <div class="mx-auto mb-3 h-16 w-16 rounded-2xl bg-white/10 grid place-items-center text-3xl">😅</div>
          <h2 class="font-display text-3xl font-semibold">So close!</h2>
          <p class="text-slate-300 mt-1">
            You scored {{ result.score }}% — you needed {{ result.pass_score }}% to win.
          </p>
          <div class="flex justify-center gap-3 mt-7">
            <button class="btn-ghost text-lg px-6 py-3" @click="emit('close')">Close</button>
            <button class="btn-primary text-lg px-7 py-3" @click="start">Try again</button>
          </div>
        </template>
      </div>
    </div>
  </div>
</template>

<style scoped>
.modal { animation: pop 0.28s cubic-bezier(0.16, 1, 0.3, 1); }
@keyframes pop {
  from { opacity: 0; transform: scale(0.94) translateY(8px); }
  to { opacity: 1; transform: scale(1) translateY(0); }
}
@media (prefers-reduced-motion: reduce) {
  .modal { animation: none; }
}

/* Wheel fades and scales out so only the reward remains. */
.wheel-leave-active { transition: opacity 0.6s ease, transform 0.6s cubic-bezier(0.16, 1, 0.3, 1); }
.wheel-enter-active { transition: opacity 0.4s ease; }
.wheel-leave-to { opacity: 0; transform: scale(0.85); }
.wheel-enter-from { opacity: 0; }
</style>
