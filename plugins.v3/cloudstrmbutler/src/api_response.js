export function unwrapApiResponse(response) {
  if (response && 'success' in response && response.data && typeof response.data === 'object') {
    const inner = response.data
    if (inner.msg === undefined && response.message) return { ...inner, msg: response.message }
    return inner
  }
  return response || {}
}
