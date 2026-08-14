import test from 'node:test'
import assert from 'node:assert/strict'

import { readPluginConfig, savePluginConfig } from '../src/config_persistence.js'

test('embedded config save writes and rereads MoviePilot canonical config', async () => {
  const calls = []
  const persisted = {
    enabled: true,
    rule_0_category: '\u56fd\u4ea7\u5267,\u65e5\u97e9\u5267',
    rule_0_local: '/CloudNAS/\u4e91\u76d8/\u56fd\u4ea7\u5267',
    rule_0_strm: '/CloudNAS/STRM/\u56fd\u4ea7\u5267',
    rule_0_cloud: '/media/\u56fd\u4ea7\u5267',
    rule_0_format: 'http://192.168.1.10:5244/d{cloud_file}',
    interval: 15,
  }
  const api = {
    put: async (...args) => {
      calls.push(args)
      return { success: true, data: null }
    },
    get: async () => persisted,
  }
  const payload = {
    enabled: true,
    interval: 15,
    monitor_confs: '',
    rule_0_category: '\u56fd\u4ea7\u5267,\u65e5\u97e9\u5267',
    rule_0_local: '/CloudNAS/\u4e91\u76d8/\u56fd\u4ea7\u5267',
    rule_0_strm: '/CloudNAS/STRM/\u56fd\u4ea7\u5267',
    rule_0_cloud: '/media/\u56fd\u4ea7\u5267',
    rule_0_format: 'http://192.168.1.10:5244/d{cloud_file}',
    rule_0_delete: false,
  }

  assert.deepEqual(await savePluginConfig(api, payload), persisted)
  assert.deepEqual(calls, [['plugin/CloudStrmButler', payload]])
})

test('embedded config save rejects when MoviePilot rereads a different value', async () => {
  const api = {
    put: async () => ({ success: true, data: null }),
    get: async () => ({ enabled: false }),
  }

  await assert.rejects(
    () => savePluginConfig(api, { enabled: true }),
    /enabled|保存后的配置未确认/,
  )
})

test('readPluginConfig accepts MoviePilot envelope and code/data responses', async () => {
  const persisted = { enabled: true, interval: 20 }
  const api = {
    get: async () => ({ success: true, data: { code: 0, data: persisted } }),
  }

  assert.deepEqual(await readPluginConfig(api), persisted)
})

test('savePluginConfig rejects when the host save API is missing', async () => {
  await assert.rejects(
    () => savePluginConfig({}, { enabled: true }),
    /MoviePilot/,
  )
})
