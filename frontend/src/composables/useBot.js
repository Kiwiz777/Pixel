import { ref } from 'vue'
import { api } from '../lib/api'
import * as diag from './useDiagnostics'

/**
 * Conversation + voice engine for the Kiosk.
 *
 * Exposes a reactive `botState` ('idle'|'listening'|'thinking'|'speaking') that
 * drives <BotFace/>, plus:
 *   - ask(prompt)            : one-shot LLM turn (+TTS)
 *   - speak(text)            : say fixed text (TTS only - no LLM, no mic)
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
  const history = ref([]) // [{role, content}] - the live thread for this guest
  // Messages (not turns) sent back as context. 16 = 8 exchanges; enough for the
  // bot to remember a name and topic without paying for the whole session.
  const HISTORY_MESSAGES = 16
  const listening = ref(false) // reactive so the button label updates on auto-stop
  const conversing = ref(false)
  // Why the last listen produced no usable text: '' | 'no-speech' |
  // 'unintelligible' | 'network'. Callers use it to tell the guest what went
  // wrong instead of going quiet.
  const listenIssue = ref('')

  // Spoken locally when the network is the problem - asking the LLM to phrase
  // an apology is exactly what cannot be done when the connection is down.
  const OFFLINE_MESSAGE = {
    ar: 'في مشكلة في الاتصال، حاول تاني من فضلك.',
    en: "I'm having trouble connecting. Please try again.",
    de: 'Verbindungsproblem. Bitte versuche es erneut.',
    ru: 'Проблема соединения. Попробуйте ещё раз.',
    fr: 'Problème de connexion. Réessayez, s’il vous plaît.',
  }

  let mediaRecorder = null
  let chunks = []
  let audioEl = null
  let micStream = null

  // --- Voice activity detection (auto-stop on silence) ---
  let audioCtx = null
  let analyser = null
  let vadTimer = null
  let speechStarted = false
  let voicedMs = 0 // cumulative ms above SILENCE_RMS this turn
  let silenceStart = 0
  let recordStart = 0
  let pendingLang = null
  let pendingPrompt = null // per-screen STT recognition bias
  let finishing = false
  let resolveListen = null // resolves the current listenOnce() promise
  const SILENCE_RMS = 0.012 // below this = "silence"
  // Total time above the threshold before we believe someone actually spoke.
  // A single loud sample (a cough, a door, mic self-noise) used to be enough to
  // arm a recording; Whisper then hallucinates YouTube subtitle boilerplate
  // ("subscribe to the channel") to fill the silence.
  const MIN_VOICED_MS = 350
  const SILENCE_HOLD_MS = 650 // stop this long after speech ends
  const NO_SPEECH_MS = 6000 // if nobody speaks, end the turn (guest left)
  const MAX_RECORD_MS = 20000 // hard cap per turn

  // Recognition bias per language. Written IN that language on purpose: the
  // prompt conditions output script and phrasing, so an English prompt on
  // Arabic audio pushes the decoder toward Latin script. Only used when the
  // language is known - a mismatched prompt is worse than none.
  const STT_PROMPTS = {
    'ar-EG':
      'محادثة قصيرة بالعامية المصرية مع روبوت تصوير اسمه بيكسل. ' +
      'أمثلة: مساء الفل، إزيك، عامل ايه، عايز صورة، يلا بينا، تمام كده.',
    'ar-GULF':
      'محادثة قصيرة باللهجة الخليجية مع روبوت تصوير اسمه بيكسل. ' +
      'أمثلة: شلونك، وش أخبارك، أبغى صورة، يالله.',
  }

  function promptForLanguage(lang) {
    return lang ? STT_PROMPTS[lang] || '' : ''
  }

  // --- Conversation loop ---
  let convLang = null
  let turns = 0
  let misheard = 0 // consecutive turns we could not make out
  const MAX_MISHEARD = 2
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
  async function ask(prompt, { speak = true, direction = false } = {}) {
    if (!prompt?.trim()) return
    error.value = ''
    if (!direction) lastUser.value = prompt
    setState('thinking')
    try {
      const res = await diag.timed('chat', () =>
        api.chat(prompt, history.value.slice(-HISTORY_MESSAGES), false),
      )
      lastReply.value = res.text

      // A "direction" is a stage instruction we wrote ("Greet the guest and ask
      // their name"), not something a person said. Recording it as a user turn
      // makes the model answer the director instead of the guest, and it starts
      // parroting the instructions back - which is where the stilted, repetitive
      // "if you need help please ask" replies came from.
      if (!direction) {
        history.value.push({ role: 'user', content: prompt })
        diag.logEvent('user', prompt)
      }
      history.value.push({ role: 'assistant', content: res.text })
      diag.logEvent('bot', res.text, `${res.provider || ''} ${res.model || ''}`.trim())

      if (speak && res.text) {
        // Voice is a nice-to-have: a TTS failure must not blank the reply
        // the guest can already read.
        try {
          await playAudio(await diag.timed('tts', () => api.tts(res.text)))
        } catch {
          setState('idle')
        }
      } else {
        setState('idle')
      }
      return res
    } catch (e) {
      error.value = e.message || 'The bot could not respond. Check AI keys in Admin.'
      diag.logEvent('error', error.value)
      setState('idle')
    }
  }

  /**
   * Say a fixed line out loud - the welcome-on-arrival greeting. No LLM call
   * and nothing added to the thread: it's a hello, not a conversation turn.
   *
   *   src         - a saved clip URL: play it, no TTS call (offline, free).
   *   fallbackSrc - live TTS first; if that fails (no internet / no key),
   *                 play this saved clip instead of going silent.
   */
  async function speak(text, { src = null, fallbackSrc = null } = {}) {
    if (!text?.trim()) return
    diag.logEvent('bot', text, src ? 'welcome · saved voice' : 'welcome')
    if (src) return playSrc(src)
    try {
      await playAudio(await diag.timed('tts', () => api.tts(text)))
    } catch {
      if (fallbackSrc) return playSrc(fallbackSrc)
      setState('idle') // voice is optional; the bubble already shows the text
    }
  }

  /**
   * Change the language mid-conversation.
   *
   * Recording starts the instant the guest taps, but the language hint isn't
   * needed until the clip is uploaded - seconds later, once they stop talking.
   * That gap is what lets the kiosk's double-tap pin a dialect without
   * delaying the start of the recording.
   */
  function setConversationLanguage(lang) {
    convLang = lang
    pendingLang = lang
    pendingPrompt = promptForLanguage(lang)
    diag.logEvent('state', `language set to ${lang || 'auto-detect'}`)
  }

  /**
   * Wipe the thread. Called when a guest walks away so the next person doesn't
   * inherit a stranger's conversation.
   */
  function resetConversation() {
    history.value = []
    lastUser.value = ''
    lastReply.value = ''
    diag.logEvent('state', 'conversation reset')
  }

  function playAudio(blob) {
    const url = URL.createObjectURL(blob)
    // Revoke afterwards, otherwise every turn leaks a blob.
    return playSrc(url).finally(() => URL.revokeObjectURL(url))
  }

  /** Play any audio URL (a TTS blob URL or a saved clip) with the speaking face. */
  function playSrc(src) {
    return new Promise((resolve) => {
      setState('speaking')
      audioEl = new Audio(src)
      const done = () => {
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
  function listenOnce(language = null, sttPrompt = null) {
    return new Promise((resolve) => {
      resolveListen = resolve
      error.value = ''
      pendingLang = language
      // Caller-supplied hint wins (the contact form describes its fields);
      // otherwise fall back to the dialect prompt for this language.
      pendingPrompt = sttPrompt || promptForLanguage(language)
      finishing = false
      speechStarted = false
      voicedMs = 0
      silenceStart = 0
      navigator.mediaDevices
        .getUserMedia({
          // Mono, cleaned up: Whisper works from a 16k mono mixdown anyway, and
          // room noise is what pushes it toward inventing text.
          audio: {
            channelCount: 1,
            echoCancellation: true,
            noiseSuppression: true,
            autoGainControl: true,
          },
        })
        .then((stream) => {
          micStream = stream
          chunks = []
          // Pin the codec rather than taking the browser default, and give it
          // enough bitrate that speech survives. 'opus' in WebM is what Chromium
          // picks anyway; being explicit avoids surprises on the Pi's build.
          const mime = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus']
            .find((m) => window.MediaRecorder?.isTypeSupported?.(m))
          mediaRecorder = new MediaRecorder(stream, mime
            ? { mimeType: mime, audioBitsPerSecond: 64000 }
            : undefined)
          mediaRecorder.ondataavailable = (e) => e.data.size && chunks.push(e.data)
          // Timeslice: flush a chunk every 250ms so a hard stop can never lose
          // everything recorded so far.
          mediaRecorder.start(250)
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
        diag.setMicLevel(rms) // the diagnostics meter reuses the VAD's own reading
        const now = Date.now()
        if (rms >= SILENCE_RMS) {
          speechStarted = true
          voicedMs += 100 // this loop's interval
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
    // Wait for the recorder to flush BEFORE killing the source tracks. Stopping
    // them first cuts the tail off the recording and can leave the WebM
    // container unfinalised - Whisper then decodes it poorly and falls back to
    // the most probable phrase it knows instead of what was actually said.
    await stopped
    micStream?.getTracks().forEach((t) => t.stop())
    let text = null
    listenIssue.value = '' // 'no-speech' | 'unintelligible' | 'network'
    if (speechStarted && voicedMs >= MIN_VOICED_MS) {
      setState('thinking')
      try {
        // Label the blob with what was actually recorded - a mismatched
        // container hint makes the server-side decode guess wrong.
        const type = mediaRecorder?.mimeType || 'audio/webm'
        const blob = new Blob(chunks, { type })
        const res = await diag.timed('stt', () => api.stt(blob, pendingLang, pendingPrompt))
        text = res?.text || null
        // Whisper's own language/duration report is the fastest way to tell a
        // bad recording (0.4s, wrong language) from a bad transcription.
        const detail = [
          `${Math.round(blob.size / 1024)} KB`,
          `${Math.round(voicedMs)}ms voiced`,
          res?.duration ? `${res.duration}s audio` : '',
          res?.language || '',
          pendingLang ? `asked:${pendingLang}` : 'autodetect',
          // So you can confirm from the panel that the dialect note went out.
          pendingPrompt ? 'hint:on' : 'hint:off',
          res?.filtered ? `FILTERED: ${res.raw}` : '',
        ].filter(Boolean).join(' · ')
        diag.logEvent('stt', text || '(nothing usable)', detail, res?.audio_url || '')
        // Empty here means Whisper returned nothing, or returned invented
        // boilerplate that the server filtered out. Either way we genuinely
        // did not understand - say so rather than going quiet.
        if (!text) listenIssue.value = 'unintelligible'
      } catch (e) {
        listenIssue.value = 'network'
        error.value = e.message || 'Could not reach speech recognition.'
        diag.logEvent('error', `stt failed: ${error.value}`)
      }
    } else {
      // Either nothing above the threshold at all, or a blip too short to be
      // speech (a cough, a door). Nobody actually said anything.
      listenIssue.value = 'no-speech'
      diag.logEvent('stt', '(no speech detected)', `${Math.round(voicedMs)}ms voiced`)
    }
    mediaRecorder = null
    micStream = null
    const r = resolveListen
    resolveListen = null
    if (r) r(text)
  }

  /**
   * Tell the guest why we got nothing, instead of silently returning to idle.
   *
   * 'unintelligible' goes through the LLM so the apology is in the right
   * language and in Pixel's voice. 'network' cannot - the network is the thing
   * that is broken - so it uses a local string.
   */
  async function reportListenIssue(language = null) {
    const issue = listenIssue.value
    if (!issue) return

    if (issue === 'network') {
      const base = (language || 'en').split('-')[0]
      lastReply.value = OFFLINE_MESSAGE[base] || OFFLINE_MESSAGE.en
      setState('idle')
      return
    }

    const label = language ? ` Reply ONLY in ${language}.` : ''
    const instruction = issue === 'no-speech'
      ? `You heard nothing at all. Say in one short friendly sentence that you didn't hear anything and invite them to try again.${label}`
      : `You could not make out what the guest said. Say in one short friendly sentence that you didn't catch it and ask them to repeat.${label}`
    try {
      await ask(instruction, { direction: true })
    } catch {
      // Even the apology failed - fall back to a local one rather than nothing.
      const base = (language || 'en').split('-')[0]
      lastReply.value = OFFLINE_MESSAGE[base] || OFFLINE_MESSAGE.en
      setState('idle')
    }
  }

  /** Manual single voice turn (the "Talk to Me" button uses this). */
  async function startListening(language = null) {
    const text = await listenOnce(language)
    if (text) await ask(text)
    else await reportListenIssue(language)
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
      // The opener is our instruction to the bot, not the guest speaking.
      if (openingPrompt) await ask(openingPrompt, { direction: true })
      while (conversing.value && turns < MAX_TURNS) {
        const text = await listenOnce(convLang)
        if (!conversing.value) break
        if (!text) {
          // Genuine silence means the guest walked off - end the conversation.
          // But "I couldn't make that out" deserves a retry, not a hang-up.
          if (listenIssue.value === 'no-speech') break
          const wasNetwork = listenIssue.value === 'network'
          await reportListenIssue(convLang)
          // Don't loop forever apologising if the mic or the network is broken.
          if (wasNetwork || ++misheard >= MAX_MISHEARD) break
          continue
        }
        misheard = 0 // a good turn clears the streak
        if (FAREWELL.test(text)) {
          await ask(`The guest said: "${text}". Give a brief, warm goodbye.`, { direction: true })
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
    botState, lastUser, lastReply, error, history, conversing, listenIssue,
    ask, speak, startListening, stopListening, listenOnce, isRecording, setState,
    converse, endConversation, resetConversation, reportListenIssue,
    setConversationLanguage,
  }
}
