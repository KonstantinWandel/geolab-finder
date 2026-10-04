import test from 'node:test'
import assert from 'node:assert/strict'
import { readConsent, saveConsent, loadHistory, saveHistory, visitor, analyticsEvent, withdrawAnalytics } from './privacy.js'

class MemoryStorage {
  values = new Map()
  getItem(k) { return this.values.get(k) ?? null }
  setItem(k, v) { this.values.set(k, v) }
  removeItem(k) { this.values.delete(k) }
}
test('unconsented and legacy history creates no identity and sends nothing', async () => {
  globalThis.localStorage = new MemoryStorage()
  localStorage.setItem('geolab_history_soep', '[{"role":"user","content":"old"}]')
  let sent = 0
  globalThis.fetch = async () => { sent++; return { ok: true } }
  assert.equal(readConsent('soep').decided, false)
  assert.deepEqual(loadHistory('soep'), [])
  assert.equal(visitor('soep'), null)
  await analyticsEvent('soep', '/api', 'search')
  assert.equal(sent, 0)
  saveHistory('soep', [{ role: 'user' }])
  assert.equal(localStorage.getItem('geolab_history_soep'), null)
})
test('choices are independent, history is bounded, ids are scoped and withdrawal follows events', async () => {
  globalThis.localStorage = new MemoryStorage()
  const sent = []
  globalThis.fetch = async (url, req) => { sent.push({ url, body: JSON.parse(req.body) }); return { ok: true } }
  saveConsent('soep', { history: true, analytics: false })
  saveHistory('soep', Array.from({ length: 20 }, () => ({ role: 'user' })))
  assert.equal(loadHistory('soep').length, 12)
  assert.equal(visitor('soep'), null)
  saveConsent('soep', { history: false, analytics: true })
  saveConsent('inkar', { history: false, analytics: true })
  const id = visitor('soep')
  assert.match(id, /^[a-f0-9]{32}$/)
  assert.notEqual(id, visitor('inkar'))
  assert.equal(loadHistory('soep').length, 0)
  await analyticsEvent('soep', '/api', 'search')
  assert.equal(sent[0].body.visitor_id, id)
  assert.equal('question' in sent[0].body, false)
  const queued = analyticsEvent('soep', '/api', 'search')
  saveConsent('soep', { history: false, analytics: false })
  const withdraw = withdrawAnalytics('soep', '/api')
  await queued
  await withdraw
  assert.equal(sent.filter((r) => r.url.endsWith('/event')).length, 1)
  assert.equal(sent.at(-1).body.visitor_id, id)
  assert.equal(localStorage.getItem('geolab_visitor_soep'), null)
  assert.equal(localStorage.getItem('geolab_withdrawal_soep'), null)
})
test('quota failure when withdrawing invalidates an earlier grant', async () => {
  globalThis.localStorage = new MemoryStorage()
  saveConsent('soep', { analytics: true, history: true })
  const id = visitor('soep')
  const sent = []
  globalThis.fetch = async (url, req) => { sent.push({ url, body: JSON.parse(req.body) }); return { ok: true } }
  localStorage.setItem = () => { throw new Error('quota') }
  assert.equal(saveConsent('soep', { analytics: false, history: false }), false)
  assert.equal(readConsent('soep').analytics, false)
  assert.equal(visitor('soep'), null)
  await analyticsEvent('soep', '/api', 'search')
  // Deletion still needs to work when there is no room for a retry record.
  await withdrawAnalytics('soep', '/api')
  assert.equal(sent.length, 1)
  assert.equal(sent[0].body.visitor_id, id)
  assert.equal(sent[0].url, '/api/analytics/withdraw')
  assert.equal(localStorage.getItem('geolab_visitor_soep'), null)
})
test('expired/malformed preferences and blocked storage fail closed', () => {
  globalThis.localStorage = new MemoryStorage()
  localStorage.setItem('geolab_privacy_soep', JSON.stringify({ version: '2026-10-04', history: true, analytics: true }))
  assert.equal(readConsent('soep').decided, false)
  saveConsent('soep', { history: true })
  localStorage.setItem('geolab_history_soep', JSON.stringify({ version: 1, expires_at: 0, messages: [{ role: 'user' }] }))
  assert.deepEqual(loadHistory('soep'), [])
  Object.defineProperty(globalThis, 'localStorage', { configurable: true, get() { throw new Error('blocked') } })
  assert.equal(readConsent('soep').decided, false)
  assert.equal(saveConsent('soep', { history: true }), false)
  assert.deepEqual(loadHistory('soep'), [])
  assert.equal(visitor('soep'), null)
})
