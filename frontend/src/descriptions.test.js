import test from 'node:test'
import assert from 'node:assert/strict'
import { descriptionSections } from './descriptions.js'

test('official bilingual fields are selected without rewriting notes or distinct variants', () => {
  const row = { source_key: 'soep', soep_version: 'v41', rich_description:
    'Repeated label (code) im Datensatz [en].\nEnglish label: Income.\nKonzept: income.\nOfficial note: Monthly income in the main job, not annual income.\nFragetext: German question\nQuestion wording: First wording | First wording | Second wording\nAntwortkategorien: 1: yes; 2: no\nVerteilung: Range: 0 to 100' }
  const sections = descriptionSections(row, 'en')
  assert.equal(sections[0].text, 'Monthly income in the main job, not annual income.')
  assert.equal(sections[1].text, 'First wording\n\nSecond wording')
  assert.equal(sections[2].language, 'de')
  assert.equal(sections[2].text, '1: yes; 2: no')
  assert.equal(row.rich_description.includes('Repeated label'), true)
  const flattened = { ...row, description_original: row.rich_description,
    rich_description: row.rich_description.replaceAll('\n', ' ') }
  assert.deepEqual(descriptionSections(flattened, 'en'), sections)
})
test('unstructured descriptions are preserved and regional headings retain method limitations', () => {
  const original = { source_key: 'inkar', rich_description: 'Actual definition. Important limitations: denominators differ.' }
  assert.equal(descriptionSections(original)[0].text, original.rich_description)
  const regional = { source_key: 'regionalatlas', label: 'Label', rich_description: 'Label: Aussage: Area. Indikatorberechnung: Divide by total. Regionale Besonderheiten: Not comparable before 2016.' }
  const sections = descriptionSections(regional)
  assert.deepEqual(sections.map((s) => s.text), ['Area.', 'Divide by total.', 'Not comparable before 2016.'])
  const dated = descriptionSections({ ...regional, rich_description: 'Label am 31.12.: Aussage: Area.' })
  assert.equal(dated[0].text, 'Label am 31.12.:')
})
