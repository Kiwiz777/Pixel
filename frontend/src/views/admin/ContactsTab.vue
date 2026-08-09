<script setup>
/**
 * Contacts tab: submissions from the kiosk "Contact us" form, with CSV export.
 */
import { computed, onMounted, ref } from 'vue'
import { api } from '../../lib/api'

const props = defineProps({ settings: Object })
const emit = defineEmits(['save'])

const contacts = ref([])
const loading = ref(false)
const msg = ref('')

const enabled = computed(() => props.settings?.contact_form_enabled ?? true)

async function load() {
  loading.value = true
  try {
    contacts.value = (await api.contacts()).contacts
  } catch (e) {
    msg.value = e.message
  } finally {
    loading.value = false
  }
}

async function remove(id) {
  await api.deleteContact(id)
  await load()
}

async function clearAll() {
  if (!confirm(`Delete all ${contacts.value.length} contacts? This cannot be undone.`)) return
  await api.clearContacts()
  await load()
  msg.value = 'All contacts deleted.'
}

function toggleForm() {
  emit('save', { contact_form_enabled: !enabled.value })
}

function exportCsv() {
  const esc = (v) => `"${String(v ?? '').replace(/"/g, '""')}"`
  const rows = [
    ['Name', 'Job title', 'Company', 'Phone', 'Email', 'Source', 'Received'],
    ...contacts.value.map((c) => [
      c.name, c.job_title, c.company, c.phone, c.email, c.source, c.created_at,
    ]),
  ]
  const blob = new Blob([rows.map((r) => r.map(esc).join(',')).join('\n')], {
    type: 'text/csv;charset=utf-8',
  })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `contacts-${new Date().toISOString().slice(0, 10)}.csv`
  link.click()
  URL.revokeObjectURL(url)
}

function when(iso) {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString()
}

onMounted(load)
</script>

<template>
  <section>
    <header class="mb-5">
      <h1 class="font-display text-2xl font-semibold">Contacts</h1>
      <p class="text-slate-400 mt-1">Details guests left through the kiosk form.</p>
    </header>

    <div class="glass-card p-5 sm:p-6 mb-5 flex flex-wrap items-center justify-between gap-3">
      <div>
        <p class="font-display font-semibold">Contact Us button</p>
        <p class="hint !mt-0">
          {{ enabled ? 'Shown on the kiosk.' : 'Hidden from the kiosk.' }}
        </p>
      </div>
      <button class="btn-ghost btn-sm" @click="toggleForm">
        {{ enabled ? 'Hide it' : 'Show it' }}
      </button>
    </div>

    <div class="glass-card p-5 sm:p-6">
      <div class="flex flex-wrap items-center justify-between gap-3 mb-4">
        <h2 class="font-display text-lg font-semibold">
          Submissions
          <span class="hint !mt-0 ml-1">({{ contacts.length }})</span>
        </h2>
        <div class="flex gap-2">
          <button class="btn-ghost btn-sm" @click="load">↻ Refresh</button>
          <button class="btn-ghost btn-sm" :disabled="!contacts.length" @click="exportCsv">Export CSV</button>
          <button class="btn-ghost btn-sm text-red-300" :disabled="!contacts.length" @click="clearAll">Delete all</button>
        </div>
      </div>

      <p v-if="loading" class="hint">Loading…</p>
      <p v-else-if="!contacts.length" class="hint">
        Nothing yet. Submissions from the kiosk appear here.
      </p>

      <div v-else class="overflow-x-auto">
        <table class="w-full text-left text-sm">
          <thead class="text-slate-400">
            <tr class="border-b border-white/10">
              <th scope="col" class="py-2 pr-4 font-display font-semibold">Name</th>
              <th scope="col" class="py-2 pr-4 font-display font-semibold">Role</th>
              <th scope="col" class="py-2 pr-4 font-display font-semibold">Phone</th>
              <th scope="col" class="py-2 pr-4 font-display font-semibold">Email</th>
              <th scope="col" class="py-2 pr-4 font-display font-semibold">Via</th>
              <th scope="col" class="py-2 pr-4 font-display font-semibold">Received</th>
              <th scope="col" class="py-2"><span class="sr-only">Actions</span></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="c in contacts" :key="c.id" class="border-b border-white/5">
              <td class="py-2.5 pr-4 text-slate-100">{{ c.name }}</td>
              <td class="py-2.5 pr-4 text-slate-300">
                <span v-if="c.job_title || c.company">
                  {{ [c.job_title, c.company].filter(Boolean).join(' · ') }}
                </span>
                <span v-else class="text-slate-500">—</span>
              </td>
              <td class="py-2.5 pr-4 tabular-nums">
                <a v-if="c.phone" :href="`tel:${c.phone}`" class="hover:text-electric-300">{{ c.phone }}</a>
                <span v-else class="text-slate-500">—</span>
              </td>
              <td class="py-2.5 pr-4">
                <a v-if="c.email" :href="`mailto:${c.email}`" class="hover:text-electric-300">{{ c.email }}</a>
                <span v-else class="text-slate-500">—</span>
              </td>
              <td class="py-2.5 pr-4 text-slate-400">{{ c.source === 'voice' ? 'Voice' : 'Typed' }}</td>
              <td class="py-2.5 pr-4 text-slate-400">{{ when(c.created_at) }}</td>
              <td class="py-2.5 text-right">
                <button class="btn-ghost btn-sm" :aria-label="`Delete ${c.name}`" @click="remove(c.id)">✕</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <p v-if="msg" class="hint mt-4" aria-live="polite">{{ msg }}</p>
  </section>
</template>
