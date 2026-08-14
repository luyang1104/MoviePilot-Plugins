import test from 'node:test'
import assert from 'node:assert/strict'

import { savePluginConfig } from '../src/config_persistence.js'

test('savePluginConfig persists through MoviePilot plugin PUT endpoint', async () => {
  const calls = []
  const api = {
    put: async (...args) => {
      calls.push(args)
      return { success: true, data: null }
    },
  }
  const payload = { enabled: true, rule_0_local: '/source' }

  await savePluginConfig(api, payload)

  assert.deepEqual(calls, [['plugin/CloudStrmButler', payload]])
})

test('savePluginConfig rejects a failed MoviePilot response', async () => {
  const api = {
    put: async () => ({ success: false, message: '保存失败' }),
  }

  await assert.rejects(
    () => savePluginConfig(api, { enabled: true }),
    /保存失败/,
  )
})

test('savePluginConfig rejects when the host save API is missing', async () => {
  await assert.rejects(
    () => savePluginConfig({}, { enabled: true }),
    /MoviePilot/,
  )
})
