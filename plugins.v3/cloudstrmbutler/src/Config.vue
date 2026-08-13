<template>
  <v-card class="cloudstrm-config">
    <v-card-item>
      <v-card-title>云盘Strm小管家 - 配置</v-card-title>
      <template #append>
        <v-btn icon variant="text" @click="emit('close')">
          <v-icon>mdi-close</v-icon>
        </v-btn>
      </template>
    </v-card-item>

    <v-divider />

    <v-card-text class="overflow-y-auto" style="max-height: 70vh;">
      <v-alert v-if="error" type="error" class="mb-4" closable>{{ error }}</v-alert>

      <!-- 基础设置 -->
      <div class="text-subtitle-1 font-weight-bold mt-2 mb-2">基础设置</div>
      <v-row dense>
        <v-col cols="6" sm="3">
          <v-switch v-model="config.enabled" label="启用插件" color="primary" density="compact" hide-details />
        </v-col>
        <v-col cols="6" sm="3">
          <v-switch v-model="config.monitor" label="实时监控" color="primary" density="compact" hide-details />
        </v-col>
        <v-col cols="6" sm="3">
          <v-switch v-model="config.cover" label="覆盖已有文件" color="primary" density="compact" hide-details />
        </v-col>
        <v-col cols="6" sm="3">
          <v-switch v-model="config.notify" label="入库通知" color="primary" density="compact" hide-details />
        </v-col>
      </v-row>

      <v-row dense class="mt-2">
        <v-col cols="6" sm="3">
          <v-switch v-model="config.copy_files" label="复制旁车文件" color="primary" density="compact" hide-details />
        </v-col>
        <v-col cols="6" sm="3">
          <v-switch v-model="config.copy_subtitles" label="复制字幕" color="primary" density="compact" hide-details />
        </v-col>
        <v-col cols="6" sm="3">
          <v-switch v-model="config.refresh_emby" label="刷新Emby" color="primary" density="compact" hide-details />
        </v-col>
        <v-col cols="6" sm="3">
          <v-switch v-model="config.uriencode" label="URL编码" color="primary" density="compact" hide-details />
        </v-col>
      </v-row>

      <v-row dense class="mt-2">
        <v-col cols="12" sm="4">
          <v-text-field v-model="config.interval" label="消息延迟(秒)" type="number" variant="outlined" density="compact" hide-details />
        </v-col>
        <v-col cols="12" sm="4">
          <v-text-field v-model="config.scan_interval" label="全量扫描周期(分钟)" type="number" variant="outlined" density="compact" hide-details />
        </v-col>
        <v-col cols="12" sm="4">
          <v-text-field v-model="config.url" label="任务推送URL" variant="outlined" density="compact" hide-details />
        </v-col>
      </v-row>

      <v-divider class="my-4" />

      <!-- 目录配置 -->
      <div class="d-flex align-center mb-2">
        <div class="text-subtitle-1 font-weight-bold">目录配置</div>
        <v-spacer />
        <v-btn size="small" variant="tonal" color="primary" prepend-icon="mdi-plus" @click="addRule">
          新增规则
        </v-btn>
      </div>

      <v-alert v-if="config.rules.length === 0" type="info" variant="tonal" class="mb-2">
        暂无映射规则，请点击"新增规则"添加。
      </v-alert>

      <div v-for="(rule, index) in config.rules" :key="rule._key" class="rule-card mb-3">
        <div class="d-flex align-center rule-card-header">
          <span class="text-body-2 font-weight-medium">规则 {{ index + 1 }}</span>
          <v-spacer />
          <v-btn icon size="x-small" variant="text" color="error" @click="removeRule(index)" title="删除此规则">
            <v-icon size="18">mdi-delete</v-icon>
          </v-btn>
        </div>

        <v-row dense>
          <v-col cols="12">
            <v-combobox
              v-model="rule.category"
              label="分类标签"
              multiple
              chips
              closable-chips
              variant="outlined"
              density="compact"
              hide-details
              placeholder="输入标签后回车，如：国产剧、日韩剧"
            />
          </v-col>
        </v-row>

        <v-row dense class="mt-2">
          <v-col cols="12" sm="6">
            <v-text-field
              v-model="rule.local"
              label="CD2 挂载目录（MoviePilot 中路径）"
              variant="outlined"
              density="compact"
              hide-details
              placeholder="/CloudNAS/CloudDrive/WebDrive/国产剧"
            />
          </v-col>
          <v-col cols="12" sm="6">
            <v-text-field
              v-model="rule.strm"
              label="STRM 生成目录"
              variant="outlined"
              density="compact"
              hide-details
              placeholder="/CloudNAS/云盘Strm/media/国产剧"
            />
          </v-col>
        </v-row>

        <v-row dense class="mt-2">
          <v-col cols="12" sm="5">
            <v-text-field
              v-model="rule.cloud"
              label="OpenList 云盘目录"
              variant="outlined"
              density="compact"
              hide-details
              placeholder="/media/国产剧"
            />
          </v-col>
          <v-col cols="12" sm="5">
            <v-text-field
              v-model="rule.format"
              label="STRM 格式化模板"
              variant="outlined"
              density="compact"
              hide-details
              placeholder="http://192.168.1.10:5244/d{cloud_file}"
            />
          </v-col>
          <v-col cols="12" sm="2" class="d-flex align-center">
            <v-switch v-model="rule.monitor" label="监控" color="primary" density="compact" hide-details />
          </v-col>
        </v-row>
      </div>

      <v-divider class="my-4" />

      <!-- 高级设置 -->
      <v-expansion-panels variant="accordion">
        <v-expansion-panel>
          <v-expansion-panel-title>高级设置</v-expansion-panel-title>
          <v-expansion-panel-text>
            <v-row dense>
              <v-col cols="12" sm="6">
                <v-textarea
                  v-model="config.rmt_mediaext"
                  label="视频格式扩展名"
                  rows="2"
                  variant="outlined"
                  density="compact"
                  hide-details
                  placeholder=".mp4, .mkv, .ts, .iso, .rmvb, .avi, .mov, .mpeg, .mpg, .wmv, .3gp, .asf, .m4v, .flv, .m2ts, .strm, .tp, .f4v"
                />
              </v-col>
              <v-col cols="12" sm="6">
                <v-textarea
                  v-model="config.other_mediaext"
                  label="非媒体文件格式"
                  rows="2"
                  variant="outlined"
                  density="compact"
                  hide-details
                  placeholder=".nfo, .jpg, .png, .json"
                />
              </v-col>
            </v-row>
            <v-row dense class="mt-2">
              <v-col cols="12" sm="6">
                <v-textarea
                  v-model="config.emby_path"
                  label="媒体库路径映射"
                  rows="2"
                  variant="outlined"
                  density="compact"
                  hide-details
                  placeholder="本地路径=>Emby路径，多组用英文逗号分隔"
                />
              </v-col>
              <v-col cols="12" sm="6">
                <v-textarea
                  v-model="config.path_replacements"
                  label="路径替换规则"
                  rows="2"
                  variant="outlined"
                  density="compact"
                  hide-details
                  placeholder="源路径=>目标路径，每行一条规则"
                />
              </v-col>
            </v-row>
          </v-expansion-panel-text>
        </v-expansion-panel>
      </v-expansion-panels>
    </v-card-text>

    <v-card-actions>
      <v-btn v-if="hasPage" color="info" variant="tonal" prepend-icon="mdi-database-eye-outline" @click="emit('switch')">
        查看数据
      </v-btn>
      <v-spacer />
      <v-btn color="secondary" variant="tonal" @click="resetForm">重置</v-btn>
      <v-btn color="primary" variant="flat" prepend-icon="mdi-content-save" :loading="saving" @click="saveConfig" class="ml-2">
        保存配置
      </v-btn>
    </v-card-actions>
  </v-card>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'

const props = defineProps({
  initialConfig: { type: Object, default: () => ({}) },
  api: { type: Object, default: () => {} },
})

const emit = defineEmits(['save', 'close', 'switch'])

const error = ref(null)
const saving = ref(false)
const hasPage = ref(false)

const defaultConfig = {
  enabled: false,
  monitor: false,
  cover: false,
  notify: false,
  copy_files: false,
  copy_subtitles: false,
  refresh_emby: false,
  uriencode: false,
  onlyonce: false,
  interval: 10,
  scan_interval: 0,
  url: '',
  rmt_mediaext: '.mp4, .mkv, .ts, .iso, .rmvb, .avi, .mov, .mpeg, .mpg, .wmv, .3gp, .asf, .m4v, .flv, .m2ts, .strm, .tp, .f4v',
  other_mediaext: '.nfo, .jpg, .png, .json',
  emby_path: '',
  path_replacements: '',
  mediaservers: [],
  rules: [],
}

const config = reactive(structuredClone(defaultConfig))

let _ruleCounter = 0

function makeRule(data = {}) {
  return {
    _key: `rule_${Date.now()}_${++_ruleCounter}`,
    category: data.category || [],
    local: data.local || '',
    strm: data.strm || '',
    cloud: data.cloud || '',
    format: data.format || '',
    monitor: data.monitor !== undefined ? data.monitor : true,
  }
}

onMounted(() => {
  if (props.initialConfig && Object.keys(props.initialConfig).length > 0) {
    const ic = props.initialConfig
    config.enabled = Boolean(ic.enabled)
    config.monitor = Boolean(ic.monitor)
    config.cover = Boolean(ic.cover)
    config.notify = Boolean(ic.notify)
    config.copy_files = Boolean(ic.copy_files)
    config.copy_subtitles = Boolean(ic.copy_subtitles)
    config.refresh_emby = Boolean(ic.refresh_emby)
    config.uriencode = Boolean(ic.uriencode)
    config.onlyonce = Boolean(ic.onlyonce)
    config.interval = ic.interval != null ? Number(ic.interval) : 10
    config.scan_interval = ic.scan_interval != null ? Number(ic.scan_interval) : 0
    config.url = String(ic.url || '')
    config.rmt_mediaext = String(ic.rmt_mediaext || config.rmt_mediaext)
    config.other_mediaext = String(ic.other_mediaext || config.other_mediaext)
    config.emby_path = String(ic.emby_path || '')
    config.path_replacements = String(ic.path_replacements || '')
    config.mediaservers = Array.isArray(ic.mediaservers) ? [...ic.mediaservers] : []

    // Parse rules from structured keys or from monitor_confs
    config.rules = parseRules(ic)
  }
})

function parseRules(ic) {
  const rules = []

  // Try structured keys first
  for (let i = 0; ; i++) {
    const local = String(ic[`rule_${i}_local`] || '').trim()
    const strm = String(ic[`rule_${i}_strm`] || '').trim()
    if (!local && !strm && !ic[`rule_${i}_delete`]) break

    const deleteFlag = String(ic[`rule_${i}_delete`] || '').trim()
    if (deleteFlag === '1' || deleteFlag === 'true' || deleteFlag === 'True') continue

    rules.push(makeRule({
      category: parseCategory(ic[`rule_${i}_category`]),
      local,
      strm,
      cloud: String(ic[`rule_${i}_cloud`] || '').trim(),
      format: String(ic[`rule_${i}_format`] || '').trim(),
      monitor: ic[`rule_${i}_monitor`] !== undefined ? Boolean(ic[`rule_${i}_monitor`]) : true,
    }))
  }

  // Fallback to legacy monitor_confs
  if (rules.length === 0 && ic.monitor_confs) {
    const lines = String(ic.monitor_confs).split('\n')
    for (const rawLine of lines) {
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
      const cloud = parts[2].trim()
      const format = parts[3].trim()

      if (!local && !strm) continue

      rules.push(makeRule({
        category: parseCategory(category),
        local,
        strm,
        cloud,
        format,
        monitor: monitorFlag !== '0',
      }))
    }
  }

  return rules
}

function parseCategory(value) {
  if (!value) return []
  if (Array.isArray(value)) return value.map(v => String(v).trim()).filter(Boolean)
  const str = String(value).trim()
  if (!str) return []
  return str.split(/[,，]+/).map(v => v.trim()).filter(Boolean)
}

function addRule() {
  config.rules.push(makeRule())
}

function removeRule(index) {
  config.rules.splice(index, 1)
}

function resetForm() {
  Object.assign(config, structuredClone(defaultConfig))
  error.value = null
}

async function saveConfig() {
  saving.value = true
  error.value = null

  try {
    const payload = {}
    payload.enabled = config.enabled
    payload.monitor = config.monitor
    payload.cover = config.cover
    payload.notify = config.notify
    payload.copy_files = config.copy_files
    payload.copy_subtitles = config.copy_subtitles
    payload.refresh_emby = config.refresh_emby
    payload.uriencode = config.uriencode
    payload.onlyonce = config.onlyonce
    payload.interval = config.interval
    payload.scan_interval = config.scan_interval
    payload.url = config.url
    payload.rmt_mediaext = config.rmt_mediaext
    payload.other_mediaext = config.other_mediaext
    payload.emby_path = config.emby_path
    payload.path_replacements = config.path_replacements
    payload.mediaservers = config.mediaservers

    // Serialize rules to structured keys
    for (let i = 0; i < config.rules.length; i++) {
      const rule = config.rules[i]
      payload[`rule_${i}_category`] = (rule.category || []).join(',')
      payload[`rule_${i}_local`] = rule.local
      payload[`rule_${i}_strm`] = rule.strm
      payload[`rule_${i}_cloud`] = rule.cloud
      payload[`rule_${i}_format`] = rule.format
      payload[`rule_${i}_monitor`] = rule.monitor
      payload[`rule_${i}_delete`] = false
    }

    // Also generate legacy monitor_confs for backward compatibility
    const lines = config.rules.map(rule => {
      const line = `${rule.local}#${rule.strm}#${rule.cloud}#${rule.format}`
      const category = (rule.category || []).join(',')
      const suffix = (category ? `@${category}` : '') + (rule.monitor ? '' : '$0')
      return line + suffix
    })
    payload.monitor_confs = lines.join('\n')

    emit('save', payload)
  } catch (err) {
    error.value = err.message || '保存失败'
  } finally {
    saving.value = false
  }
}
</script>

<style scoped>
.rule-card {
  border: 1px solid rgba(var(--v-border-color), 0.4);
  border-radius: 8px;
  padding: 12px;
  background: rgba(var(--v-theme-surface), 0.3);
}
.rule-card-header {
  margin-bottom: 8px;
  padding-bottom: 6px;
  border-bottom: 1px solid rgba(var(--v-border-color), 0.2);
}
</style>
