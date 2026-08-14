import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

test('standard Vue config still delegates persistence to the MoviePilot host', async () => {
  const source = await readFile(new URL('../src/Config.vue', import.meta.url), 'utf8')

  assert.match(source, /emit\(['"]save['"],\s*payload\)/)
  assert.match(source, /if \(props\.embedded\)/)
  assert.match(source, /savePluginConfig\(props\.api, payload\)/)
})

test('embedded Page config reloads the canonical MoviePilot config', async () => {
  const source = await readFile(new URL('../src/Page.vue', import.meta.url), 'utf8')

  assert.match(source, /readPluginConfig\(props\.api\)/)
  assert.match(source, /plugin\/CloudStrmButler/)
})

test('embedded Page polls live status and cleans the timer on unmount', async () => {
  const source = await readFile(new URL('../src/Page.vue', import.meta.url), 'utf8')

  assert.match(source, /onUnmounted/)
  assert.match(source, /setInterval/)
  assert.match(source, /clearInterval/)
  assert.match(source, /service_running/)
  assert.match(source, /run\.skipped/)
  assert.doesNotMatch(source, /status\.enabled \|\| status\.scan_running/)
})
