import assert from 'node:assert/strict'
import test from 'node:test'
import { formatIndexDate, makeTranslator } from './i18n.js'

test('index dates use the selected interface language without time or filter text', () => {
  const timestamp = '2026-10-04T18:58:38.625994+00:00'
  assert.equal(makeTranslator('de')('filter.indexBuilt', {
    date: formatIndexDate(timestamp, 'de'),
  }), 'Index vom 04.10.2026')
  assert.equal(makeTranslator('en')('filter.indexBuilt', {
    date: formatIndexDate(timestamp, 'en'),
  }), 'Index as of 4 October 2026')
})

test('index dates follow the Berlin calendar date independently of the browser timezone', () => {
  const timestamp = '2026-10-04T22:30:00+00:00'
  assert.equal(formatIndexDate(timestamp, 'de'), '05.10.2026')
  assert.equal(formatIndexDate(timestamp, 'en'), '5 October 2026')
})

test('missing or invalid index dates do not display a raw timestamp', () => {
  for (const value of [undefined, null, '', '   ', 'invalid', 0, {}]) {
    assert.equal(formatIndexDate(value, 'de'), '')
  }
})
