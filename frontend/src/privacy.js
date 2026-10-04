export const CONSENT_VERSION = '2026-10-04'
const DAY = 86400000
const key = (mode, kind) => `geolab_${kind}_${mode}`
const storage = () => globalThis.localStorage
const empty = () => ({ decided: false, history: false, analytics: false })
const blocked = new Set()
const remove = (mode, kind) => { try { storage().removeItem(key(mode, kind)) } catch { /* unavailable */ } }

export function readConsent(mode, now = Date.now()) {
  if (blocked.has(mode)) return empty()
  try {
    const value = JSON.parse(storage().getItem(key(mode, 'privacy')))
    if (value?.version !== CONSENT_VERSION || !Number.isFinite(value.expires_at) || value.expires_at <= now || value.expires_at > now + 180 * DAY
      || typeof value.history !== 'boolean' || typeof value.analytics !== 'boolean') return empty()
    return { ...value, decided: true }
  } catch { return empty() }
}

export function saveConsent(mode, choices) {
  try {
    storage().setItem(key(mode, 'privacy'), JSON.stringify({ version: CONSENT_VERSION,
      history: Boolean(choices.history), analytics: Boolean(choices.analytics), expires_at: Date.now() + 180 * DAY }))
    blocked.delete(mode)
    if (!choices.history) clearHistory(mode)
    return true
  } catch {
    // A full storage quota must not leave an earlier analytics grant active after withdrawal.
    blocked.add(mode)
    remove(mode, 'privacy')
    clearHistory(mode)
    return false
  }
}

export function clearHistory(mode) { remove(mode, 'history') }

export function loadHistory(mode) {
  if (!readConsent(mode).history) { clearHistory(mode); return [] }
  try {
    const value = JSON.parse(storage().getItem(key(mode, 'history')))
    // Legacy, unconsented history is deliberately not migrated into the new system.
    if (value?.version !== 1 || !Number.isFinite(value.expires_at) || value.expires_at <= Date.now()
      || value.expires_at > Date.now() + 30 * DAY || !Array.isArray(value.messages)) {
      clearHistory(mode)
      return []
    }
    return value.messages.filter((m) => m && typeof m === 'object' && typeof m.role === 'string').slice(-12)
  } catch { clearHistory(mode); return [] }
}

export function saveHistory(mode, messages) {
  if (!readConsent(mode).history) { clearHistory(mode); return }
  for (const limit of [12, 2]) {
    try {
      storage().setItem(key(mode, 'history'), JSON.stringify({ version: 1,
        expires_at: Date.now() + 30 * DAY, messages: messages.slice(-limit) }))
      return
    } catch { /* retry with the most recent search only */ }
  }
  clearHistory(mode)
}

export function visitor(mode) {
  if (!readConsent(mode).analytics) return null
  try {
    const value = JSON.parse(storage().getItem(key(mode, 'visitor')))
    if (/^[a-f0-9]{32}$/.test(value?.id) && value.expires_at > Date.now()
      && value.expires_at <= Date.now() + 90 * DAY) return value.id
    const id = Array.from(crypto.getRandomValues(new Uint8Array(16)), (b) => b.toString(16).padStart(2, '0')).join('')
    storage().setItem(key(mode, 'visitor'), JSON.stringify({ id, expires_at: Date.now() + 90 * DAY }))
    return id
  } catch { return null }
}

let requests = Promise.resolve()
const withdrawals = new Map()
async function post(apiUrl, path, payload) {
  const response = await fetch(`${apiUrl}/${path}`, { method: 'POST',
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) })
  if (!response.ok) throw new Error('Optional telemetry unavailable')
}

export function analyticsEvent(mode, apiUrl, event) {
  requests = requests.catch(() => {}).then(async () => {
    // Recheck at send time: an in-flight search must not undo a subsequent withdrawal.
    const id = visitor(mode)
    if (id) await post(apiUrl, 'analytics/event', { visitor_id: id, consent: true,
      consent_version: CONSENT_VERSION, event })
  })
  return requests.catch(() => {})
}

export function withdrawAnalytics(mode, apiUrl) {
  try {
    const value = JSON.parse(storage().getItem(key(mode, 'visitor')))
    if (value?.id) {
      const pending = { id: value.id, expires_at: Date.now() + 7 * DAY }
      withdrawals.set(mode, pending)
      try { storage().setItem(key(mode, 'withdrawal'), JSON.stringify(pending)) } catch { /* retry in memory */ }
    }
  } catch { /* unavailable */ }
  remove(mode, 'visitor')
  return retryWithdrawal(mode, apiUrl)
}

export function retryWithdrawal(mode, apiUrl) {
  requests = requests.catch(() => {}).then(async () => {
    let pending = withdrawals.get(mode)
    if (!pending) {
      try { pending = JSON.parse(storage().getItem(key(mode, 'withdrawal'))) } catch { /* unavailable */ }
    }
    if (!pending) return
    if (pending.expires_at <= Date.now()) { remove(mode, 'withdrawal'); withdrawals.delete(mode); return }
    await post(apiUrl, 'analytics/withdraw', { visitor_id: pending.id })
    remove(mode, 'withdrawal')
    withdrawals.delete(mode)
  })
  return requests
}
