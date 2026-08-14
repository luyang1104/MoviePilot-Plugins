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

export async function savePluginConfig(api, payload) {
  if (!api || typeof api.put !== 'function') {
    throw new Error('MoviePilot 配置保存接口不可用')
  }

  const response = await api.put('plugin/CloudStrmButler', payload)
  const result = unwrapApiResponse(response)
  const hasCode = result && Object.prototype.hasOwnProperty.call(result, 'code')
  const failed = response?.success === false
    || result?.success === false
    || (hasCode && Number(result.code) !== 0)

  if (failed) {
    throw new Error(result?.msg || response?.message || '配置保存失败')
  }

  if (typeof api.get !== 'function') {
    throw new Error('MoviePilot 配置读取接口不可用，无法确认保存结果')
  }

  const persistedResponse = await api.get('plugin/CloudStrmButler')
  const persistedResult = unwrapApiResponse(persistedResponse)
  const persistedHasCode = persistedResult && Object.prototype.hasOwnProperty.call(persistedResult, 'code')
  const persistedFailed = persistedResponse?.success === false
    || persistedResult?.success === false
    || (persistedHasCode && Number(persistedResult.code) !== 0)

  if (persistedFailed) {
    throw new Error(persistedResult?.msg || persistedResponse?.message || '读取保存后的配置失败')
  }

  const persisted = persistedResult?.data && typeof persistedResult.data === 'object'
    && !Array.isArray(persistedResult.data)
    ? persistedResult.data
    : persistedResult
  if (!persisted || typeof persisted !== 'object') {
    throw new Error('MoviePilot 未返回保存后的配置')
  }

  for (const [key, expected] of Object.entries(payload)) {
    // The backend removes the legacy text field once structured rules are saved.
    if (key === 'monitor_confs') continue
    if (key.endsWith('_delete') && !expected) continue
    if (persisted[key] === undefined || !sameConfigValue(key, expected, persisted[key])) {
      throw new Error('保存后的配置未确认：' + key)
    }
  }

  return persisted
}
