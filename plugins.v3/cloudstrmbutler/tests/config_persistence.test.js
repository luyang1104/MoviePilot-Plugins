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
    get: async () => ({ enabled: true, rule_0_local: '/source' }),
  }
  const payload = { enabled: true, rule_0_local: '/source' }

  await savePluginConfig(api, payload)

  assert.deepEqual(calls, [['plugin/CloudStrmButler', payload]])
})

test('savePluginConfig rejects when MoviePilot stores a different enabled state', async () => {
  const api = {
    put: async () => ({ success: true, data: null }),
    get: async () => ({ enabled: false }),
  }

  await assert.rejects(
    () => savePluginConfig(api, { enabled: true }),
    /enabled|启用|保存后/i,
  )
})

test('savePluginConfig accepts wrapped persisted configuration', async () => {
  const persisted = {
    enabled: true,
    rule_0_local: '/source',
    rule_0_strm: '/strm',
    rule_0_cloud: '/cloud',
    rule_0_format: 'http://host/{cloud_file}',
  }
  const api = {
    put: async () => ({ success: true, data: null }),
    get: async () => ({ success: true, data: { code: 0, data: persisted } }),
  }

  assert.deepEqual(
    await savePluginConfig(api, {
      enabled: true,
      monitor_confs: '',
      rule_0_local: '/source',
      rule_0_strm: '/strm',
      rule_0_cloud: '/cloud',
      rule_0_format: 'http://host/{cloud_file}',
      rule_0_delete: false,
    }),
    persisted,
  )
})

test('savePluginConfig accepts the host config response with code and data', async () => {
  const persisted = { enabled: false, interval: 20 }
  const api = {
    put: async () => ({ code: 0, data: null }),
    get: async () => ({ code: 0, data: persisted }),
  }

  assert.deepEqual(
    await savePluginConfig(api, { enabled: false, interval: 20 }),
    persisted,
  )
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
