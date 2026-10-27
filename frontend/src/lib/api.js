// Thin fetch wrapper. Admin endpoints require a bearer token which we keep in
// localStorage (entered once on the Admin login gate).
const ADMIN_TOKEN_KEY = 'pb_admin_token'

export function getAdminToken() {
  return localStorage.getItem(ADMIN_TOKEN_KEY) || ''
}
export function setAdminToken(token) {
  localStorage.setItem(ADMIN_TOKEN_KEY, token)
}
export function clearAdminToken() {
  localStorage.removeItem(ADMIN_TOKEN_KEY)
}

async function request(method, path, { body, admin = false, isForm = false } = {}) {
  const headers = {}
  if (admin) headers['Authorization'] = `Bearer ${getAdminToken()}`
  let payload = body
  if (body && !isForm) {
    headers['Content-Type'] = 'application/json'
    payload = JSON.stringify(body)
  }
  const res = await fetch(path, { method, headers, body: payload })
  if (!res.ok) {
    let detail = res.statusText
    try {
      detail = (await res.json()).detail || detail
    } catch {
      /* non-json error */
    }
    const err = new Error(detail)
    err.status = res.status
    throw err
  }
  const ct = res.headers.get('content-type') || ''
  if (ct.includes('application/json')) return res.json()
  return res
}

export const api = {
  get: (p, o) => request('GET', p, o),
  post: (p, body, o) => request('POST', p, { ...o, body }),
  put: (p, body, o) => request('PUT', p, { ...o, body }),
  del: (p, o) => request('DELETE', p, o),

  // Convenience wrappers ------------------------------------------------
  health: () => request('GET', '/api/health'),

  // Kiosk (public)
  publicSettings: () => request('GET', '/api/settings/public'),
  // If `frameBlob` is provided (browser camera), send it; else server grabs.
  capture: (frameBlob) => {
    if (!frameBlob) return request('POST', '/api/photobooth/capture')
    const fd = new FormData()
    fd.append('frame', frameBlob, 'frame.jpg')
    return request('POST', '/api/photobooth/capture', { body: fd, isForm: true })
  },
  // style_index = an Admin style card; the server resolves its prompt.
  enhance: (capture_id, prompt, style_index = null) =>
    request('POST', '/api/photobooth/enhance', { body: { capture_id, prompt, style_index } }),
  applyFrame: (capture_id, use_enhanced = true) =>
    request('POST', '/api/photobooth/frame', { body: { capture_id, use_enhanced } }),
  print: (capture_id) =>
    request('POST', '/api/photobooth/print', { body: { capture_id } }),
  // Public: match a live face descriptor against enrolled users (kiosk).
  matchFace: (descriptor, peek = false) =>
    request('POST', '/api/users/match', { body: { descriptor, peek } }),
  // Public: register a brand-new guest from the onboarding chat (kiosk),
  // including a face snapshot for the Admin thumbnail.
  enrollFace: ({ name, bio = '', language = 'en', descriptor, faceBlob = null }) => {
    const fd = new FormData()
    fd.append('name', name)
    fd.append('bio', bio)
    fd.append('language', language)
    fd.append('descriptor', JSON.stringify(descriptor))
    if (faceBlob) fd.append('face', faceBlob, 'snap.jpg')
    return request('POST', '/api/users/enroll', { body: fd, isForm: true })
  },
  // Public: persona-free extraction (e.g. pull a name from a spoken reply).
  extract: (text, instruction) =>
    request('POST', '/api/ai/extract', { body: { text, instruction } }),
  chat: (prompt, history = [], speak = false) =>
    request('POST', '/api/ai/chat', { body: { prompt, history, speak } }),
  // Separate from chat() on purpose: the reply text can be shown while the
  // audio is still being synthesized, instead of waiting for both.
  tts: async (text, voice_id) => {
    const res = await request('POST', '/api/ai/tts', { body: { text, voice_id } })
    return res.blob()
  },

  // Soft save + share (public: kiosk capture modal)
  shareOptions: () => request('GET', '/api/share/options'),
  shareSave: (capture_id) => request('POST', '/api/share/save', { body: { capture_id } }),
  shareEmail: (capture_id, email) =>
    request('POST', '/api/share/email', { body: { capture_id, email } }),
  shareWhatsApp: (capture_id, phone) =>
    request('POST', '/api/share/whatsapp', { body: { capture_id, phone } }),
  // QR mode: guest scans, sends the code to the booth, booth replies with the photo.
  waCode: (capture_id) => request('POST', '/api/share/whatsapp/code', { body: { capture_id } }),
  waCodeStatus: (code) => request('GET', `/api/share/whatsapp/code/${encodeURIComponent(code)}`),
  waCodeRetry: (code) => request('POST', `/api/share/whatsapp/code/${encodeURIComponent(code)}/retry`),
  // Soft save + share (admin)
  shareStatus: () => request('GET', '/api/share/status', { admin: true }),
  emailTest: () => request('POST', '/api/share/email/test', { admin: true }),
  waStatus: () => request('GET', '/api/share/whatsapp/status', { admin: true }),
  waStart: () => request('POST', '/api/share/whatsapp/start', { admin: true }),
  waStop: () => request('POST', '/api/share/whatsapp/stop', { admin: true }),
  waLogout: () => request('POST', '/api/share/whatsapp/logout', { admin: true }),
  waTest: (phone) => request('POST', '/api/share/whatsapp/test', { body: { phone }, admin: true }),
  savedPhotos: (day) =>
    request('GET', `/api/share/photos${day ? `?day=${encodeURIComponent(day)}` : ''}`, { admin: true }),
  // <img>/<a> can't send the bearer header, so the token rides in the query.
  savedPhotoUrl: (file) =>
    `/api/share/photos/file/${file.split('/').map(encodeURIComponent).join('/')}?token=${encodeURIComponent(getAdminToken())}`,

  // Contact us (public: kiosk)
  submitContact: (body) => request('POST', '/api/contacts', { body }),
  parseContact: (text) => request('POST', '/api/contacts/parse', { body: { text } }),
  // Contact us (admin)
  contacts: () => request('GET', '/api/contacts', { admin: true }),
  deleteContact: (id) => request('DELETE', `/api/contacts/${id}`, { admin: true }),
  clearContacts: () => request('DELETE', '/api/contacts', { admin: true }),

  // Quiz (public: kiosk)
  activeQuiz: () => request('GET', '/api/quiz/active'),
  submitQuiz: (quiz_id, answers) =>
    request('POST', '/api/quiz/submit', { body: { quiz_id, answers } }),
  voucherEmail: (label, code, email) =>
    request('POST', '/api/quiz/voucher-email', { body: { label, code, email } }),
  voucherPrint: (label, code) =>
    request('POST', '/api/quiz/voucher-print', { body: { label, code } }),
  stt: (blob, language, prompt) => {
    const fd = new FormData()
    // Extension must match the recorded container or the decode guesses wrong.
    const ext = (blob.type || '').includes('ogg') ? 'ogg' : 'webm'
    fd.append('file', blob, `speech.${ext}`)
    if (language) fd.append('language', language)
    // Per-screen recognition bias (the contact form describes what it expects).
    if (prompt) fd.append('prompt', prompt)
    return request('POST', '/api/ai/stt', { body: fd, isForm: true })
  },

  // Admin (token-gated)
  getSettings: () => request('GET', '/api/settings', { admin: true }),
  saveSettings: (values) => request('PUT', '/api/settings', { body: values, admin: true }),
  voices: () => request('GET', '/api/settings/voices', { admin: true }),
  // Live model list from a provider (kind = chat | image | tts | stt).
  liveModels: (kind, provider) =>
    request('GET', `/api/settings/models/${kind}/${encodeURIComponent(provider)}`, { admin: true }),
  // Pre-generate welcome lines as MP3s (offline, no per-greeting token cost).
  saveVoiceClips: (texts) => request('POST', '/api/ai/voice-clips', { body: { texts }, admin: true }),
  listUsers: () => request('GET', '/api/users', { admin: true }),
  addUser: (formData) => request('POST', '/api/users', { body: formData, admin: true, isForm: true }),
  updateUser: (id, body) => request('PUT', `/api/users/${id}`, { body, admin: true }),
  deleteUser: (id) => request('DELETE', `/api/users/${id}`, { admin: true }),
  logs: (type, limit = 100) =>
    request('GET', `/api/logs?${type ? `type=${type}&` : ''}limit=${limit}`, { admin: true }),
  clearLogs: (type) =>
    request('DELETE', `/api/logs${type ? `?type=${type}` : ''}`, { admin: true }),
  printers: () => request('GET', '/api/printer', { admin: true }),
  printerMedia: (printer) =>
    request('GET', `/api/printer/media${printer ? `?printer=${encodeURIComponent(printer)}` : ''}`, { admin: true }),
  setDefaultPrinter: (name) =>
    request('POST', '/api/printer/default', { body: { name }, admin: true }),
  updatePrintConfig: (body) =>
    request('PUT', '/api/printer/config', { body, admin: true }),
  testPrint: () => request('POST', '/api/printer/test', { admin: true }),
  uploadFrame: (file) => {
    const fd = new FormData()
    fd.append('file', file)
    return request('POST', '/api/photobooth/frame-overlay', { body: fd, admin: true, isForm: true })
  },
  uploadStyleImage: (file) => {
    const fd = new FormData()
    fd.append('file', file)
    return request('POST', '/api/photobooth/style-image', { body: fd, admin: true, isForm: true })
  },
  listBackgrounds: () => request('GET', '/api/photobooth/backgrounds', { admin: true }),
  uploadBackground: (file) => {
    const fd = new FormData()
    fd.append('file', file)
    return request('POST', '/api/photobooth/backgrounds', { body: fd, admin: true, isForm: true })
  },
  deleteBackground: (file) =>
    request('DELETE', `/api/photobooth/backgrounds/${encodeURIComponent(file)}`, { admin: true }),

  // Quiz (admin)
  listQuizzes: () => request('GET', '/api/quiz', { admin: true }),
  getQuiz: (id) => request('GET', `/api/quiz/${id}`, { admin: true }),
  createQuiz: (body) => request('POST', '/api/quiz', { body, admin: true }),
  updateQuiz: (id, body) => request('PUT', `/api/quiz/${id}`, { body, admin: true }),
  deleteQuiz: (id) => request('DELETE', `/api/quiz/${id}`, { admin: true }),
  activateQuiz: (id) => request('POST', `/api/quiz/${id}/activate`, { admin: true }),
  resetRewardUsage: (id) => request('POST', `/api/quiz/${id}/reset-usage`, { admin: true }),
  importQuizCsv: (id, file) => {
    const fd = new FormData()
    fd.append('file', file)
    return request('POST', `/api/quiz/${id}/import`, { body: fd, admin: true, isForm: true })
  },
  exportQuizCsv: async (id) => {
    const res = await request('GET', `/api/quiz/${id}/export.csv`, { admin: true })
    return res.text() // request() returns the raw Response for non-JSON bodies
  },
  uploadRewardImage: (file) => {
    const fd = new FormData()
    fd.append('file', file)
    return request('POST', '/api/quiz/reward-image', { body: fd, admin: true, isForm: true })
  },
  // Real-person video avatar clips (state = idle|talking|listening|thinking|wave)
  uploadAvatarVideo: (state, file) => {
    const fd = new FormData()
    fd.append('file', file)
    return request('POST', `/api/settings/avatar-video/${state}`, { body: fd, admin: true, isForm: true })
  },
  deleteAvatarVideo: (state) => request('DELETE', `/api/settings/avatar-video/${state}`, { admin: true }),
  uploadWheelImage: (kind, file) => {
    const fd = new FormData()
    fd.append('file', file)
    return request('POST', `/api/settings/wheel-image/${kind}`, { body: fd, admin: true, isForm: true })
  },
}

// Build a ws:// URL from the current origin (works behind the Vite proxy).
export function wsUrl(path) {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  return `${proto}://${location.host}${path}`
}
