import { ref } from 'vue'

/**
 * App-wide on-screen keyboard state.
 *
 * Module-scope so any page can raise it without prop-drilling. It types into
 * whatever input/textarea currently has focus, which means it works on every
 * screen - kiosk forms, the admin dashboard - without those screens knowing
 * it exists.
 */
export const open = ref(false)
export const lang = ref('en') // en | ar
export const target = ref(null) // the focused <input>/<textarea>

export function openKeyboard(el = null) {
  if (el) target.value = el
  open.value = true
}

export function closeKeyboard() {
  open.value = false
}

export function toggleKeyboard() {
  open.value = !open.value
}

/** Remember the last focused text field so the keyboard knows where to type. */
export function rememberTarget(el) {
  if (!el) return
  const tag = el.tagName?.toLowerCase()
  if (tag !== 'input' && tag !== 'textarea') return
  if (tag === 'input' && !/^(text|search|tel|url|email|password|number|)$/.test(el.type || '')) return
  target.value = el
}

/**
 * Insert text at the caret of the remembered field.
 *
 * Sets the value through the native setter and dispatches a real `input`
 * event, because assigning `el.value` directly does not notify Vue's v-model -
 * the field would show the character and then lose it on the next render.
 */
function applyValue(el, value, caret) {
  const proto = el instanceof HTMLTextAreaElement
    ? window.HTMLTextAreaElement.prototype
    : window.HTMLInputElement.prototype
  const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set
  if (setter) setter.call(el, value)
  else el.value = value
  el.dispatchEvent(new Event('input', { bubbles: true }))
  el.setSelectionRange?.(caret, caret)
}

export function typeChar(char) {
  const el = target.value
  if (!el) return
  const start = el.selectionStart ?? el.value.length
  const end = el.selectionEnd ?? start
  applyValue(el, el.value.slice(0, start) + char + el.value.slice(end), start + char.length)
  el.focus()
}

export function backspace() {
  const el = target.value
  if (!el) return
  const start = el.selectionStart ?? el.value.length
  const end = el.selectionEnd ?? start
  // Nothing selected: eat the character before the caret instead.
  const from = start === end ? Math.max(0, start - 1) : start
  applyValue(el, el.value.slice(0, from) + el.value.slice(end), from)
  el.focus()
}

export function submitTarget() {
  const el = target.value
  if (!el) return
  el.form?.requestSubmit?.()
  el.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))
}
