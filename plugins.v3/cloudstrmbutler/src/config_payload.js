const FALSE_VALUES = new Set(['', '0', 'false', 'no', 'off', 'n'])
const TRUE_VALUES = new Set(['1', 'true', 'yes', 'on', 'y'])

export function normalizeBoolean(value, fallback = false) {
  if (value === undefined || value === null) return fallback
  if (typeof value === 'boolean') return value
  if (typeof value === 'number') return value !== 0

  const normalized = String(value).trim().toLowerCase()
  if (FALSE_VALUES.has(normalized)) return false
  if (TRUE_VALUES.has(normalized)) return true
  return Boolean(value)
}

function normalizePathBoundary(value) {
  const raw = String(value || '').trim().replace(/\\/g, '/')
  const drive = /^[A-Za-z]:/.test(raw) ? raw.slice(0, 2).toLowerCase() : ''
  const absolute = raw.startsWith('/') || Boolean(drive)
  const segments = []

  for (const segment of raw.slice(drive ? 2 : 0).split('/')) {
    if (!segment || segment === '.') continue
    if (segment === '..') {
      if (segments.length && segments[segments.length - 1] !== '..') segments.pop()
      else if (!absolute) segments.push(segment)
      continue
    }
    segments.push(segment)
  }

  let normalized = (drive + (absolute ? '/' : '') + segments.join('/')) || (absolute ? '/' : '.')
  if (drive) normalized = normalized.toLowerCase()
  if (normalized !== '/' && !(drive && normalized === drive + '/')) normalized = normalized.endsWith('/') ? normalized.slice(0, -1) : normalized
  return normalized
}

function isPathWithin(path, root) {
  if (path === root) return true
  if (root === '/') return !/^[a-z]:\//.test(path)
  if (root === '.') return path !== '..' && !path.startsWith('../')
  return path.startsWith(root.endsWith('/') ? root : root + '/')
}

export function validateRuleForSave(rule = {}) {
  const local = String(rule.local || '').trim()
  const strm = String(rule.strm || '').trim()
  const cloud = String(rule.cloud || '').trim()
  const format = String(rule.format || '').trim()

  if (!local || !strm) return '每条路径规则都需要填写来源目录和 STRM 输出目录。'
  const localBoundary = normalizePathBoundary(local)
  const strmBoundary = normalizePathBoundary(strm)
  if (isPathWithin(strmBoundary, localBoundary)) {
    return 'STRM 输出目录不能位于来源目录内。'
  }
  if (!format || !['{local_file}', '{cloud_file}'].some(token => format.includes(token))) {
    return '每条路径规则的 STRM 模板必须包含 {local_file} 或 {cloud_file}。'
  }
  if (format.includes('{cloud_file}') && !cloud) {
    return '使用 {cloud_file} 模板的路径规则需要填写 OpenList 云盘目录。'
  }
  return ''
}

export function serializeConfig(value = {}) {
  const snapshot = { ...value }
  snapshot.rules = (Array.isArray(value.rules) ? value.rules : []).map(rule => {
    const { _key, ...plainRule } = rule || {}
    return { ...plainRule }
  })
  return JSON.stringify(snapshot)
}

function parseCategory(value) {
  if (!value) return []
  if (Array.isArray(value)) return value.map(item => String(item).trim()).filter(Boolean)
  return String(value).split(/[,，]+/).map(item => item.trim()).filter(Boolean)
}

export function parseConfigRules(config = {}) {
  const rules = []
  let structuredSlots = 0

  Object.keys(config).forEach(key => {
    const match = /^rule_(\d+)_/.exec(key)
    if (match) structuredSlots = Math.max(structuredSlots, Number(match[1]) + 1)
  })

  for (let index = 0; index < structuredSlots; index += 1) {
    const prefix = 'rule_' + index + '_'
    const local = String(config[prefix + 'local'] || '').trim()
    const strm = String(config[prefix + 'strm'] || '').trim()
    if (normalizeBoolean(config[prefix + 'delete']) || (!local && !strm)) continue
    rules.push({
      category: parseCategory(config[prefix + 'category']),
      local,
      strm,
      cloud: String(config[prefix + 'cloud'] || '').trim(),
      format: String(config[prefix + 'format'] || '').trim(),
      monitor: config[prefix + 'monitor'] !== undefined
        ? normalizeBoolean(config[prefix + 'monitor'])
        : true,
    })
  }

  // Structured slots are authoritative, including an all-deleted payload.
  if (structuredSlots || !config.monitor_confs) return rules

  for (const rawLine of String(config.monitor_confs).split('\n')) {
    let line = rawLine.trim()
    if (!line || line.startsWith('#')) continue

    let monitorFlag = null
    if ((line.match(/\$/g) || []).length === 1) {
      const parts = line.split('$')
      line = parts[0]
      monitorFlag = parts[1].trim()
    }

    let category = null
    if ((line.match(/@/g) || []).length === 1) {
      const parts = line.split('@')
      line = parts[0]
      category = parts[1].trim()
    }

    if ((line.match(/#/g) || []).length < 3) continue
    const parts = line.split('#')
    const local = parts[0].trim()
    const strm = parts[1].trim()
    if (!local && !strm) continue
    rules.push({
      category: parseCategory(category),
      local,
      strm,
      cloud: parts[2].trim(),
      format: parts.slice(3).join('#').trim(),
      monitor: !['0', 'nomonitor', 'false', 'off'].includes(String(monitorFlag || '').toLowerCase()),
    })
  }

  return rules
}

function nonNegativeNumber(value, fallback = 0) {
  const number = Number(value)
  return Number.isFinite(number) ? Math.max(0, number) : fallback
}

export function buildConfigPayload(config = {}, savedRuleSlotCount = 0) {
  const rules = Array.isArray(config.rules) ? config.rules : []
  const invalidRule = rules.map(validateRuleForSave).find(Boolean)
  if (invalidRule) throw new Error(invalidRule)

  const payload = {
    enabled: normalizeBoolean(config.enabled),
    monitor: normalizeBoolean(config.monitor),
    cover: normalizeBoolean(config.cover),
    notify: normalizeBoolean(config.notify),
    copy_files: normalizeBoolean(config.copy_files),
    copy_subtitles: normalizeBoolean(config.copy_subtitles),
    refresh_emby: normalizeBoolean(config.refresh_emby),
    uriencode: normalizeBoolean(config.uriencode),
    onlyonce: normalizeBoolean(config.onlyonce),
    interval: nonNegativeNumber(config.interval, 10),
    scan_interval: nonNegativeNumber(config.scan_interval),
    url: String(config.url || ''),
    rmt_mediaext: String(config.rmt_mediaext || ''),
    other_mediaext: String(config.other_mediaext || ''),
    subtitle_formats: String(config.subtitle_formats || ''),
    emby_path: String(config.emby_path || ''),
    path_replacements: String(config.path_replacements || ''),
    mediaservers: Array.isArray(config.mediaservers) ? [...config.mediaservers] : [],
    reliable_engine: normalizeBoolean(config.reliable_engine, true),
    cleanup_mode: config.cleanup_mode || 'off',
    cleanup_probe: String(config.cleanup_probe || ''),
    // Clear the legacy text field when the structured editor is used.
    monitor_confs: '',
    config_version: 2,
  }

  rules.forEach((rule, index) => {
    const prefix = 'rule_' + index + '_'
    payload[prefix + 'category'] = (rule.category || []).map(item => String(item).trim()).filter(Boolean).join(',')
    payload[prefix + 'local'] = String(rule.local || '').trim()
    payload[prefix + 'strm'] = String(rule.strm || '').trim()
    payload[prefix + 'cloud'] = String(rule.cloud || '').trim()
    payload[prefix + 'format'] = String(rule.format || '').trim()
    payload[prefix + 'monitor'] = normalizeBoolean(rule.monitor, true)
    payload[prefix + 'delete'] = false
  })

  for (let index = rules.length; index < Math.max(0, Number(savedRuleSlotCount) || 0); index += 1) {
    payload['rule_' + index + '_delete'] = true
  }

  return payload
}
