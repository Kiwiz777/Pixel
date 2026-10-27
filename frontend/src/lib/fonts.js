// App font sets (see fonts.css). The id lives in the `ui_font` setting.
export const FONT_SETS = [
  { id: 'playful', label: 'Playful', description: 'Fredoka + Nunito — the original rounded look' },
  { id: 'clean', label: 'Clean', description: 'Inter — neutral and easy to read' },
  { id: 'futuristic', label: 'Futuristic', description: 'Orbitron + Exo 2 — sci-fi / 2050 events' },
  { id: 'elegant', label: 'Elegant', description: 'Playfair Display + Lato — galas and weddings' },
]

/** Switch the whole app's font set. Unknown ids fall back to playful. */
export function applyFont(id) {
  const known = FONT_SETS.some((f) => f.id === id)
  document.documentElement.dataset.font = known ? id : 'playful'
}
