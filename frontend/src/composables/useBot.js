import { ref } from 'vue'
import { api } from '../lib/api'

/**
 * Conversation + voice engine for the Kiosk.
 *
 * Exposes a reactive `botState` ('idle'|'listening'|'thinking'|'speaking') that
 * drives <BotFace/>, plus:
 *   - ask(prompt)            : one-shot LLM turn (+TTS)
 *   - startListening(lang)   : single voice turn (record -> STT -> ask), VAD auto-stops
 *   - converse(lang, opener) : full back-and-forth loop (greet -> listen -> reply -> ...)
 *
 * The conversation loop is what makes the robot actually TALK WITH a guest
 * instead of saying a single greeting. It ends when the guest goes silent,
 * says goodbye, hits the turn cap, or endConversation() is called.
 */
export function useBot() {
  const botState = ref('idle')
  const lastUser = ref('')
  const lastReply = ref('')
  const error = ref('')
  const history = ref([]) // [{role, content}]
  const listening = ref(false) // reactive so the button label updates on auto-stop
  const conversing = ref(false)

  let mediaRecorder = null
  let chunks = []
  let audioEl = null
  let micStream = null

  // --- Voice activity detection (auto-stop on silence) ---
  let audioCtx = null
  let analyser = null
  let vadTimer = null
  let speechStarted = false
  let silenceStart = 0
  let recordStart = 0
  let pendingLang = null
  let finishing = false
  let resolveListen = null // resolves the current listenOnce() promise
  const SILENCE_RMS = 0.012 // below this = "silence"
  const SILENCE_HOLD_MS = 650 // stop this long after speech ends
  const NO_SPEECH_MS = 6000 // if nobody speaks, end the turn (guest left)
  const MAX_RECORD_MS = 20000 // hard cap per turn

  // --- Conversation loop ---
  let convLang = null
  let turns = 0
  const MAX_TURNS = 8
  const FAREWELL = /\b(bye|goodbye|see you|that's all|thank you|thanks|tschüss|auf wiedersehen|пока|до свидания|au revoir|merci|مع السلامة|سلام|شكرا|باي)\b/i

  function setState(s) {
    botState.value = s
  }

  // ------------------------------------------------------------------ chat
  /**
   * Send a text prompt to the LLM and (optionally) speak the answer.
   *
   * Text and audio are fetched in two steps rather than one. Asking the
   * server to do both (`speak: true`) means nothing reaches the guest until
   * the MP3 has finished synthesizing - a second or more after the words
   * themselves were ready. Showing the reply first makes the turn feel far
   * quicker even though total time is unchanged.
   */
  async function ask(prompt, { speak = true } = {}) {
    if (!prompt?.trim()) return
    error.value = ''
    lastUser.value = prompt
    setState('thinking')
    try {
      const res = await api.chat(prompt, history.value.slice(-8), false)
      lastReply.value = res.text
      history.value.push({ role: 'user', content: prompt })
      history.value.push({ role: 'assistant', content: res.text })

      if (speak && res.text) {
        // Voice is a nice-to-have: a TTS failure must not blank the reply
        // the guest can already read.
        try {
          await playAudio(await api.tts(res.text))
        } catch {
          setState('idle')
        }
      } else {
        setState('idle')
      }
      return res
    } catch (e) {
      error.value = e.message || 'The bot could not respond. Check AI keys in Admin.'
      setState('idle')
    }
  }

  function playAudio(blob) {
    return new Promise((resolve) => {
      setState('speaking')
      const url = URL.createObjectURL(blob)
      audioEl = new Audio(url)
      const done = () => {
        URL.revokeObjectURL(url) // otherwise every turn leaks a blob
        setState('idle')
        resolve()
      }
      audioEl.onended = done
      audioEl.onerror = done
      audioEl.play().catch(done)
    })
  }

  // ------------------------------------------------------------- listening
  /**
   * Record one turn and resolve with the transcript (or null if the guest
   * said nothing). Does NOT call the LLM — the caller decides what to do.
   */
  function listenOnce(language = null) {
    return new Promise((resolve) => {
      resolveListen = resolve
      error.value = ''
      pendingLang = language
      finishing = false
      speechStarted = false
      silenceStart = 0
      navigator.mediaDevices
        .getUserMedia({ audio: true })
        .then((stream) => {
          micStream = stream
          chunks = []
          mediaRecorder = new MediaRecorder(stream)
          mediaRecorder.ondataavailable = (e) => e.data.size && chunks.push(e.data)
          mediaRecorder.start()
          recordStart = Date.now()
          setState('listening')
          listening.value = true
          startVAD()
        })
        .catch(() => {
          error.value = 'Microphone permission denied.'
          setState('idle')
          listening.value = false
          resolveListen = null
          resolve(null)
        })
    })
  }

  function startVAD() {
    try {
      audioCtx = new (window.AudioContext || window.webkitAudioContext)()
      const source = audioCtx.createMediaStreamSource(micStream)
      analyser = audioCtx.createAnalyser()
      analyser.fftSize = 1024
      source.connect(analyser)
      const buf = new Float32Array(analyser.fftSize)
      vadTimer = setInterval(() => {
        analyser.getFloatTimeDomainData(buf)
        let sum = 0
        for (let i = 0; i < buf.length; i++) sum += buf[i] * buf[i]
        const rms = Math.sqrt(sum / buf.length)
        const now = Date.now()
        if (rms >= SILENCE_RMS) {
          speechStarted = true
          silenceStart = 0
        } else if (speechStarted) {
          if (!silenceStart) silenceStart = now
          else if (now - silenceStart > SILENCE_HOLD_MS) return finishListening()
        } else if (now - recordStart > NO_SPEECH_MS) {
          return finishListening() // nobody spoke -> end turn
        }
        if (now - recordStart > MAX_RECORD_MS) finishListening()
      }, 100)
    } catch {
      // Web Audio unavailable: rely on manual stop only.
    }
  }

  function teardownVAD() {
    if (vadTimer) clearInterval(vadTimer)
    vadTimer = null
    if (audioCtx) {
      audioCtx.close().catch(() => {})
      audioCtx = null
    }
    analyser = null
  }

  /** Stop the current turn, transcribe, and resolve listenOnce(). Idempotent. */
  async function finishListening() {
    if (finishing || !mediaRecorder) return
    finishing = true
    listening.value = false
    teardownVAD()
    const stopped = new Promise((r) => (mediaRecorder.onstop = r))
    try {
      mediaRecorder.stop()
    } catch {
      /* already stopped */
    }
    micStream?.getTracks().forEach((t) => t.stop())
    await stopped
    let text = null
    if (speechStarted) {
      setState('thinking')
      try {
        const blob = new Blob(chunks, { type: 'audio/webm' })
        text = (await api.stt(blob, pendingLang))?.text || null
      } catch (e) {
        error.value = e.message || 'Could not understand audio.'
      }
    }
    mediaRecorder = null
    micStream = null
    const r = resolveListen
    resolveListen = null
    if (r) r(text)
  }

  /** Manual single voice turn (the "Talk to Me" button uses this). */
  async function startListening(language = null) {
    const text = await listenOnce(language)
    if (text) await ask(text)
    else setState('idle')
  }

  /** Manual stop / send (tap the button again before VAD fires). */
  async function stopListening(language) {
    if (language != null) pendingLang = language
    await finishListening()
  }

  function isRecording() {
    return listening.value
  }

  // ----------------------------------------------------------- conversation
  /**
   * Run a full conversation: speak the opener (greeting), then loop
   * listen -> reply until the guest leaves / says bye / the cap is hit.
   */
  async function converse(language = null, openingPrompt = null) {
    if (conversing.value) return
    conversing.value = true
    convLang = language
    turns = 0
    try {
      if (openingPrompt) await ask(openingPrompt)
      while (conversing.value && turns < MAX_TURNS) {
        const text = await listenOnce(convLang)
        if (!conversing.value) break
        if (!text) break // silence -> guest gone
        if (FAREWELL.test(text)) {
          await ask(`The guest said: "${text}". Give a brief, warm goodbye.`)
          break
        }
        turns += 1
        await ask(text)
      }
    } finally {
      conversing.value = false
      if (botState.value === 'listening') setState('idle')
    }
  }

  function endConversation() {
    conversing.value = false
    if (listening.value) finishListening()
  }

  return {
    botState, lastUser, lastReply, error, history, conversing,
    ask, startListening, stopListening, listenOnce, isRecording, setState,
    converse, endConversation,
  }
}
