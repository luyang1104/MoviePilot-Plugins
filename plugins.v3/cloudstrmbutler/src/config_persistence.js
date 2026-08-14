import { unwrapApiResponse } from './api_response.js'

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

  return result
}
