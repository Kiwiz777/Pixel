import { ref } from 'vue'

/**
 * Shared diagnostics bus for on-site debugging.
 *
 * Module-scope state on purpose: the bot writes to it from wherever it lives
 * (KioskView's instance, the contact modal's, anywhere) and a single overlay
 * reads it. Passing this through props would mean threading it through every
 * component that touches speech.
 *
 * Everything here is capped and cheap - it stays resident even when the
 * overlays are hidden, so turning them on shows recent history immediately
 * rather than an empty panel.
 */
const MAX_EVENTS = 60
const MAX_TIMINGS = 30

// Live microphone RMS, 0..1, fed by the VAD loop that already computes it.
export const micLevel = ref(0)
// Conversation + STT trail: {id, at, kind, text, detail}
export const events = ref([])
// AI request timings: {id, at, label, ms, ok, detail}
export const timings = ref([])

let seq = 0

function push(list, item, cap) {
  list.value.push({ id: ++seq, at: Date.now(), ...item })
  if (list.value.length > cap) list.value.splice(0, list.value.length - cap)
}

/**
 * kind: 'stt' | 'user' | 'bot' | 'state' | 'error'
 * `audio` is a URL to the kept recording, so STT lines can be replayed.
 */
export function logEvent(kind, text, detail = '', audio = '') {
  push(events, { kind, text, detail, audio }, MAX_EVENTS)
}

export function logTiming(label, ms, ok = true, detail = '') {
  push(timings, { label, ms: Math.round(ms), ok, detail }, MAX_TIMINGS)
}

/**
 * Time an async call and record it. Re-throws so callers keep their own error
 * handling - this only observes.
 */
export async function timed(label, fn) {
  const started = performance.now()
  try {
    const result = await fn()
    logTiming(label, performance.now() - started, true)
    return result
  } catch (e) {
    logTiming(label, performance.now() - started, false, e?.message || 'failed')
    throw e
  }
}

export function setMicLevel(rms) {
  micLevel.value = rms
}

export function clearDiagnostics() {
  events.value = []
  timings.value = []
}

/** Mean/worst for a label, for the overlay's summary row. */
export function timingStats(label) {
  const rows = timings.value.filter((t) => t.label === label && t.ok)
  if (!rows.length) return null
  const values = rows.map((r) => r.ms)
  return {
    n: values.length,
    avg: Math.round(values.reduce((a, b) => a + b, 0) / values.length),
    max: Math.max(...values),
    last: values[values.length - 1],
  }
}
