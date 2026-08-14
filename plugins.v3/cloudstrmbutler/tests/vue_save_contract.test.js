import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

test('Vue config delegates persistence to the MoviePilot host save event', async () => {
  const source = await readFile(new URL('../src/Config.vue', import.meta.url), 'utf8')

  assert.match(source, /emit\(['"]save['"],\s*payload\)/)
  assert.doesNotMatch(source, /savePluginConfig/)
  assert.doesNotMatch(source, /props\.api\.(put|get)/)
})
