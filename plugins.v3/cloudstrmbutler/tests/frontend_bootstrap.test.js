import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

test('frontend bootstrap registers Vuetify components and directives', async () => {
  const source = await readFile(new URL('../src/main.js', import.meta.url), 'utf8')

  assert.equal(source.includes("import * as components from 'vuetify/components'"), true)
  assert.equal(source.includes("import * as directives from 'vuetify/directives'"), true)
  assert.equal(source.includes('components,'), true)
  assert.equal(source.includes('directives,'), true)
})
