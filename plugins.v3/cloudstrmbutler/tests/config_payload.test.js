import test from 'node:test'
import assert from 'node:assert/strict'
import { reactive } from 'vue'

import {
  buildConfigPayload,
  normalizeBoolean,
  parseConfigRules,
  serializeConfig,
  validateRuleForSave,
} from '../src/config_payload.js'
import { unwrapApiResponse } from '../src/api_response.js'

test('buildConfigPayload preserves settings and marks removed rule slots', () => {
  const payload = buildConfigPayload({
    enabled: false,
    monitor: true,
    cover: false,
    notify: true,
    copy_files: false,
    copy_subtitles: true,
    refresh_emby: false,
    uriencode: true,
    onlyonce: false,
    interval: '15',
    scan_interval: '30',
    url: 'http://example.test/push',
    rmt_mediaext: '.mkv',
    other_mediaext: '.nfo',
    emby_path: '/media=>/library',
    path_replacements: '/old=>/new',
    mediaservers: ['Emby'],
    reliable_engine: false,
    cleanup_mode: 'confirm',
    cleanup_probe: '.probe',
    subtitle_formats: '.srt, .vtt',
    rules: [{
      category: ['movie', '4K'],
      local: '/source',
      strm: '/strm',
      cloud: '/cloud',
      format: 'http://host/{cloud_file}',
      monitor: false,
    }],
  }, 2)

  assert.equal(payload.enabled, false)
  assert.equal(payload.monitor, true)
  assert.equal(payload.interval, 15)
  assert.equal(payload.scan_interval, 30)
  assert.deepEqual(payload.mediaservers, ['Emby'])
  assert.equal(payload.rule_0_category, 'movie,4K')
  assert.equal(payload.rule_0_monitor, false)
  assert.equal(payload.rule_0_delete, false)
  assert.equal(payload.rule_1_delete, true)
  assert.equal(payload.rule_0_local, '/source')
  assert.equal(payload.rule_0_format, 'http://host/{cloud_file}')
  assert.equal(payload.subtitle_formats, '.srt, .vtt')
})

test('buildConfigPayload preserves Chinese paths, categories, and cloud template tokens', () => {
  const payload = buildConfigPayload({
    rules: [{
      category: ['\u56fd\u4ea7\u5267', '\u65e5\u97e9\u5267'],
      local: '/CloudNAS/\u4e91\u76d8/\u56fd\u4ea7\u5267',
      strm: '/CloudNAS/STRM/\u56fd\u4ea7\u5267',
      cloud: '/media/\u56fd\u4ea7\u5267',
      format: 'http://192.168.1.10:5244/d{cloud_file}',
    }],
  })

  assert.equal(payload.rule_0_category, '\u56fd\u4ea7\u5267,\u65e5\u97e9\u5267')
  assert.equal(payload.rule_0_local, '/CloudNAS/\u4e91\u76d8/\u56fd\u4ea7\u5267')
  assert.equal(payload.rule_0_strm, '/CloudNAS/STRM/\u56fd\u4ea7\u5267')
  assert.equal(payload.rule_0_cloud, '/media/\u56fd\u4ea7\u5267')
  assert.equal(payload.rule_0_format, 'http://192.168.1.10:5244/d{cloud_file}')
})

test('invalid rules are rejected before a save payload is created', () => {
  assert.match(
    validateRuleForSave({ local: '', strm: '/strm', format: '{cloud_file}', cloud: '/cloud' }),
    /来源目录|STRM/,
  )
  assert.match(
    validateRuleForSave({ local: '/source', strm: '/strm', format: '{cloud_file}', cloud: '' }),
    /OpenList|云盘/,
  )
  assert.throws(
    () => buildConfigPayload({ rules: [{ local: '/source', strm: '/strm', format: 'literal' }] }),
    /模板|local_file|cloud_file/,
  )
})

test('normalizeBoolean handles values returned as strings', () => {
  assert.equal(normalizeBoolean(false), false)
  assert.equal(normalizeBoolean(true), true)
  assert.equal(normalizeBoolean('false'), false)
  assert.equal(normalizeBoolean('0'), false)
  assert.equal(normalizeBoolean('off'), false)
  assert.equal(normalizeBoolean('true'), true)
  assert.equal(normalizeBoolean('1'), true)
  assert.equal(normalizeBoolean('on'), true)
})

test('serializeConfig accepts Vue reactive configuration objects', () => {
  const config = reactive({
    enabled: false,
    rules: [{ _key: 'ui-only', local: '/source', monitor: true }],
  })

  assert.equal(
    serializeConfig(config),
    JSON.stringify({ enabled: false, rules: [{ local: '/source', monitor: true }] }),
  )
})

test('structured rule slots take precedence over legacy text when all rules are deleted', () => {
  const rules = parseConfigRules({
    rule_0_delete: true,
    monitor_confs: '/legacy#/strm#/cloud#{cloud_file}',
  })

  assert.deepEqual(rules, [])
})

test('legacy rule parsing keeps additional template separators and monitor flags', () => {
  const rules = parseConfigRules({
    monitor_confs: '/source#/strm#/cloud#http://host/{cloud_file}#part@movie$nomonitor',
  })

  assert.equal(rules.length, 1)
  assert.equal(rules[0].format, 'http://host/{cloud_file}#part')
  assert.deepEqual(rules[0].category, ['movie'])
  assert.equal(rules[0].monitor, false)
})

test('unwrapApiResponse accepts legacy and wrapped MoviePilot responses', () => {
  assert.deepEqual(
    unwrapApiResponse({ code: 0, data: { items: [] } }),
    { code: 0, data: { items: [] } },
  )
  assert.deepEqual(
    unwrapApiResponse({ success: true, data: { code: 0, data: { items: [] } } }),
    { code: 0, data: { items: [] } },
  )
  assert.deepEqual(
    unwrapApiResponse({ success: false, message: '保存失败', data: { code: 1 } }),
    { code: 1, msg: '保存失败' },
  )
})
