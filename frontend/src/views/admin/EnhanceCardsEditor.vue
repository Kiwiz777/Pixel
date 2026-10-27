<script setup>
/**
 * Editor for the AI Enhance style cards (Photobooth tab, "Style cards" mode).
 * Each card: emoji, title, description, accent colour, optional artwork, and
 * the prompt it runs. Edits the array in place via v-model; the parent saves.
 */
import { ref } from 'vue'
import { api } from '../../lib/api'
import StyleCard from '../../components/StyleCard.vue'

const cards = defineModel({ type: Array, required: true })
const MAX_CARDS = 12
const COLORS = ['#F97316', '#2563EB', '#8B5CF6', '#EC4899', '#10B981', '#D97706', '#0EA5E9', '#EF4444']

const uploading = ref(-1)
const msg = ref('')

function addCard() {
  if (cards.value.length >= MAX_CARDS) return
  cards.value.push({
    emoji: '✨', title: '', description: '', prompt: '', image: '',
    color: COLORS[cards.value.length % COLORS.length],
  })
}

function remove(i) {
  cards.value.splice(i, 1)
}

function move(i, dir) {
  const j = i + dir
  if (j < 0 || j >= cards.value.length) return
  const list = cards.value
  ;[list[i], list[j]] = [list[j], list[i]]
}

async function upload(i, e) {
  const file = e.target.files?.[0]
  if (!file) return
  uploading.value = i
  msg.value = ''
  try {
    cards.value[i].image = (await api.uploadStyleImage(file)).image
  } catch (err) {
    msg.value = err.message || 'Upload failed.'
  } finally {
    uploading.value = -1
    e.target.value = ''
  }
}

const incomplete = (c) => !c.title?.trim() || !c.prompt?.trim()
</script>

<template>
  <div>
    <ol class="space-y-4">
      <li
        v-for="(card, i) in cards" :key="i"
        class="rounded-2xl border border-white/10 bg-ink-900/50 p-4"
        :class="incomplete(card) ? 'border-amber-400/40' : ''"
      >
        <div class="flex flex-col md:flex-row gap-4">
          <div class="md:w-52 shrink-0">
            <StyleCard :card="card" compact />
            <div class="flex items-center gap-2 mt-2">
              <label class="btn-ghost btn-sm cursor-pointer flex-1">
                <input type="file" accept="image/png,image/jpeg,image/webp" class="hidden" @change="upload(i, $event)" />
                <span v-if="uploading === i" class="h-4 w-4 rounded-full border-2 border-white border-t-transparent animate-spin"></span>
                {{ card.image ? 'Replace art' : 'Add art' }}
              </label>
              <button v-if="card.image" class="btn-ghost btn-sm" @click="card.image = ''">Remove</button>
            </div>
          </div>

          <div class="flex-1 min-w-0 grid gap-3">
            <div class="flex gap-3">
              <div class="w-20 shrink-0">
                <label class="label" :for="`sc-emoji-${i}`">Emoji</label>
                <input :id="`sc-emoji-${i}`" v-model="card.emoji" class="field text-center text-xl !px-2" maxlength="4" />
              </div>
              <div class="flex-1 min-w-0">
                <label class="label" :for="`sc-title-${i}`">Title</label>
                <input :id="`sc-title-${i}`" v-model="card.title" class="field" maxlength="40" placeholder="e.g. Cartoon Pop" />
              </div>
              <div class="shrink-0">
                <label class="label" :for="`sc-color-${i}`">Colour</label>
                <input
                  :id="`sc-color-${i}`" v-model="card.color" type="color"
                  class="h-11 w-14 rounded-lg bg-transparent border border-white/10 cursor-pointer"
                />
              </div>
            </div>
            <div>
              <label class="label" :for="`sc-desc-${i}`">Description</label>
              <input :id="`sc-desc-${i}`" v-model="card.description" class="field" maxlength="80" placeholder="One short line guests read on the card" />
            </div>
            <div>
              <label class="label" :for="`sc-prompt-${i}`">Prompt</label>
              <textarea
                :id="`sc-prompt-${i}`" v-model="card.prompt" rows="3" class="field"
                placeholder="What the image AI should do with the photo…"
              ></textarea>
              <p class="hint">Never shown to guests.</p>
            </div>
            <div class="flex flex-wrap items-center gap-2">
              <button class="btn-ghost btn-sm" :disabled="i === 0" :aria-label="`Move ${card.title || 'card'} up`" @click="move(i, -1)">↑</button>
              <button class="btn-ghost btn-sm" :disabled="i === cards.length - 1" :aria-label="`Move ${card.title || 'card'} down`" @click="move(i, 1)">↓</button>
              <span v-if="incomplete(card)" class="hint !mt-0 text-amber-300">Needs a title and a prompt to show on the kiosk.</span>
              <button class="btn-danger btn-sm ml-auto" @click="remove(i)">Delete</button>
            </div>
          </div>
        </div>
      </li>
    </ol>

    <p v-if="!cards.length" class="hint">No style cards yet. Add at least one, or the kiosk falls back to the single prompt.</p>
    <div class="flex items-center gap-3 mt-4">
      <button class="btn-ghost btn-sm" :disabled="cards.length >= MAX_CARDS" @click="addCard">+ Add style</button>
      <span class="hint !mt-0">{{ cards.length }} / {{ MAX_CARDS }}</span>
    </div>
    <p v-if="msg" class="hint text-red-300 mt-2" role="alert">{{ msg }}</p>
  </div>
</template>
