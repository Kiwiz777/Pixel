import RobotAvatar from './RobotAvatar.vue'
import KidAvatar from './KidAvatar.vue'
import ReceptionistAvatar from './ReceptionistAvatar.vue'
import FoxAvatar from './FoxAvatar.vue'
import VideoAvatar from './VideoAvatar.vue'

/**
 * Kiosk characters (Admin -> Avatar & Welcome). Every avatar takes the same
 * props - state, mood, size, waving - so <BotFace/> can swap them freely.
 * `glow` tints the halo behind the character. `motion: 'subtle'` makes the
 * shell drop its cartoon effects (bob, hop, ripples, thinking dots) for
 * realistic characters that animate themselves.
 */
export const AVATARS = [
  { id: 'robot', label: 'Robot', description: 'Pixel, the glowing-eyed companion screen', comp: RobotAvatar, glow: '34, 211, 238' },
  { id: 'kid', label: 'Cartoon Kid', description: 'Playful and friendly — great for family events', comp: KidAvatar, glow: '249, 115, 22' },
  { id: 'receptionist', label: 'Receptionist', description: 'Realistic host with a headset — corporate and expos', comp: ReceptionistAvatar, glow: '56, 189, 248', motion: 'subtle' },
  { id: 'fox', label: 'Fox Mascot', description: 'Cute brand-orange mascot — kids, malls, festivals', comp: FoxAvatar, glow: '251, 146, 60' },
  // Real person from uploaded clips; takes an extra `video` prop ({ clips, shape }).
  { id: 'video', label: 'Real Person', description: 'Video of a real host — filmed or AI-generated', comp: VideoAvatar, glow: '56, 189, 248', motion: 'subtle', video: true },
]

export function avatarById(id) {
  return AVATARS.find((a) => a.id === id) || AVATARS[0]
}
