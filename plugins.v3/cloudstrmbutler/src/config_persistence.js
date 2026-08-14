import { unwrapApiResponse } from './api_response.js'
import { normalizeBoolean } from './config_payload.js'

const BOOLEAN_KEYS = new Set([
  'enabled', 'monitor', 'cover', 'notify', 'copy_files', 'copy_subtitles',
  'refresh_emby', 'uriencode', 'onlyonce', 'reliable_engine',
])
const NUMBER_KEYS = new Set(['interval', 'scan_interval', 'config_version'])

function sameConfigValue(key, expected, actual) {
  if (BOOLEAN_KEYS.has(key)) {
    return normalizeBoolean(actual) === normalizeBoolean(expected)
  }
  if (NUMBER_KEYS.has(key)) {
    return Number(actual) === Number(expected)
  }
  if (Array.isArray(expected)) {
    return Array.isArray(actual) && JSON.stringify(actual) === JSON.stringify(expected)
  }
  return String(actual ?? '') === String(expected ?? '')
}

function responseError(response, result, fallback) {
  if (response?.success === false || result?.success === false) {
    return result?.msg || response?.message || fallback
  }
  if (Object.prototype.hasOwnProperty.call(result || {}, 'code') && Number(result.code) !== 0) {
    return result?.msg || result?.message || response?.message || fallback
  }
  return ''
}

function extractConfig(response) {
  let result = unwrapApiResponse(response)
  const failure = responseError(response, result, '读取保存后的配置失败')
  if (failure) throw new Error(failure)

  if (Object.prototype.hasOwnProperty.call(result || {}, 'code')) {
    result = result.data
  }
  if (result && typeof result === 'object' && !Array.isArray(result)
      && Object.prototype.hasOwnProperty.call(result, 'success')
      && Object.prototype.hasOwnProperty.call(result, 'data')) {
    if (result.success === false) throw new Error(result.message || '读取保存后的配置失败')
    result = result.data
  }

  if (!result || typeof result !== 'object' || Array.isArray(result)) {
    throw new Error('MoviePilot 未返回保存后的配置')
  }
  return result
}

export async function readPluginConfig(api) {
  if (!api || typeof api.get !== 'function') {
    throw new Error('MoviePilot 配置读取接口不可用')
  }
  return extractConfig(await api.get('plugin/CloudStrmButler'))
}

export async function savePluginConfig(api, payload) {
  if (!api || typeof api.put !== 'function') {
    throw new Error('MoviePilot 配置保存接口不可用')
  }

  const response = await api.put('plugin/CloudStrmButler', payload)
  const result = unwrapApiResponse(response)
  const failure = responseError(response, result, '配置保存失败')
  if (failure) throw new Error(failure)

  const persisted = await readPluginConfig(api)
  for (const [key, expected] of Object.entries(payload)) {
    // MoviePilot removes the legacy text field after structured rules are saved.
    if (key === 'monitor_confs') continue
    if (key.endsWith('_delete') && !expected) continue
    if (persisted[key] === undefined || !sameConfigValue(key, expected, persisted[key])) {
      throw new Error('保存后的配置未确认：' + key)
    }
  }

  return persisted
}
