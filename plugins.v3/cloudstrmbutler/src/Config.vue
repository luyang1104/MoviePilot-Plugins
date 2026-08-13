<template>
  <v-card class="cloudstrm-config">
    <v-card-item class="config-header">
      <div>
        <v-card-title class="pa-0">运行设置</v-card-title>
        <v-card-subtitle class="pa-0 mt-1">先配置同步行为，再维护路径规则与兼容选项。</v-card-subtitle>
      </div>
      <template #append>
        <v-btn icon="mdi-close" variant="text" title="关闭设置" @click="emit('close')" />
      </template>
    </v-card-item>

    <v-divider />

    <v-card-text class="config-body pa-4 pa-sm-6">
      <v-alert v-if="error" type="error" variant="tonal" closable class="mb-5" @click:close="error = null">{{ error }}</v-alert>

      <section class="setting-section">
        <div class="section-heading">
          <div><h2>基础运行</h2><p>控制插件是否工作，以及同步完成后的常用行为。</p></div>
          <v-chip :color="config.enabled ? 'success' : 'secondary'" variant="tonal" size="small">{{ config.enabled ? '已启用' : '未启用' }}</v-chip>
        </div>
        <v-sheet class="settings-surface" border rounded="lg">
          <v-row dense>
            <v-col cols="12" sm="6" lg="3"><v-switch v-model="config.enabled" label="启用插件" color="primary" density="comfortable" hide-details><template #details>启用后才会启动同步服务。</template></v-switch></v-col>
            <v-col cols="12" sm="6" lg="3"><v-switch v-model="config.monitor" label="实时监控" color="primary" density="comfortable" hide-details><template #details>监听目录中的文件变化。</template></v-switch></v-col>
            <v-col cols="12" sm="6" lg="3"><v-switch v-model="config.notify" label="入库通知" color="primary" density="comfortable" hide-details><template #details>同步完成后发送通知。</template></v-switch></v-col>
            <v-col cols="12" sm="6" lg="3"><v-switch v-model="config.refresh_emby" label="刷新 Emby" color="primary" density="comfortable" hide-details><template #details>将变更通知到已配置媒体库。</template></v-switch></v-col>
          </v-row>
          <v-divider class="my-4" />
          <v-row dense>
            <v-col cols="12" sm="6" lg="3"><v-switch v-model="config.cover" label="覆盖已有文件" color="primary" density="comfortable" hide-details><template #details>生成时允许替换同名输出。</template></v-switch></v-col>
            <v-col cols="12" sm="6" lg="3"><v-switch v-model="config.copy_files" label="复制旁车文件" color="primary" density="comfortable" hide-details><template #details>复制 nfo、图片等其他文件。</template></v-switch></v-col>
            <v-col cols="12" sm="6" lg="3"><v-switch v-model="config.copy_subtitles" label="复制字幕" color="primary" density="comfortable" hide-details><template #details>复制同名字幕文件。</template></v-switch></v-col>
            <v-col cols="12" sm="6" lg="3"><v-switch v-model="config.uriencode" label="URL 编码" color="primary" density="comfortable" hide-details><template #details>对生成链接中的路径编码。</template></v-switch></v-col>
          </v-row>
        </v-sheet>
      </section>

      <section class="setting-section">
        <div class="section-heading">
          <div><h2>可靠同步与清理</h2><p>队列、失败记录和清理策略均在可靠同步引擎启用后生效。</p></div>
        </div>
        <v-sheet class="settings-surface" border rounded="lg">
          <v-row dense align="center">
            <v-col cols="12" md="4"><v-switch v-model="config.reliable_engine" label="启用可靠同步引擎" color="primary" density="comfortable" hide-details><template #details>使用持久化队列和失败重试记录。</template></v-switch></v-col>
            <v-col cols="12" md="4"><v-select v-model="config.cleanup_mode" label="缺失文件清理策略" :items="cleanupModes" variant="outlined" density="compact" hide-details /></v-col>
            <v-col cols="12" md="4"><v-text-field v-model.trim="config.cleanup_probe" label="清理探针文件" hint="可选。探针不存在时跳过扫描清理。" persistent-hint variant="outlined" density="compact" /></v-col>
          </v-row>
          <v-row dense class="mt-1">
            <v-col cols="12" md="4"><v-text-field v-model.number="config.interval" label="消息延迟（秒）" type="number" min="0" variant="outlined" density="compact" hide-details /></v-col>
            <v-col cols="12" md="4"><v-text-field v-model.number="config.scan_interval" label="全量扫描周期（分钟）" type="number" min="0" hint="填写 0 可关闭定时扫描。" persistent-hint variant="outlined" density="compact" /></v-col>
            <v-col cols="12" md="4"><v-text-field v-model.trim="config.url" label="任务推送 URL" hint="可选。用于接收外部任务推送。" persistent-hint variant="outlined" density="compact" /></v-col>
          </v-row>
        </v-sheet>
      </section>

      <section class="setting-section">
        <div class="section-heading">
          <div><h2>路径规则</h2><p>每条规则将来源目录映射到 STRM 输出目录与云盘路径。</p></div>
          <v-btn color="primary" variant="flat" prepend-icon="mdi-plus" @click="openRuleEditor()">新增路径规则</v-btn>
        </div>

        <v-alert v-if="!config.rules.length" type="info" variant="tonal" class="mb-3">
          还没有路径规则。新增一条规则后，才能将目录中的媒体映射为 STRM 文件。
        </v-alert>

        <v-sheet v-else class="rule-list" border rounded="lg">
          <article v-for="(rule, index) in config.rules" :key="rule._key" class="rule-row">
            <div class="rule-flow">
              <div class="rule-path"><span>来源目录</span><strong class="path">{{ rule.local || '尚未设置来源目录' }}</strong><div class="rule-tags"><v-chip v-for="tag in rule.category" :key="tag" size="x-small" variant="tonal">{{ tag }}</v-chip><small v-if="!rule.category.length">未设置分类标签</small></div></div>
              <v-icon icon="mdi-arrow-right" class="flow-arrow" />
              <div class="rule-path"><span>STRM 输出目录</span><strong class="path">{{ rule.strm || '尚未设置输出目录' }}</strong><small>云盘：{{ rule.cloud || '尚未设置' }}</small></div>
            </div>
            <div class="rule-actions">
              <v-chip :color="rule.monitor ? 'success' : 'secondary'" size="small" variant="tonal">{{ rule.monitor ? '监控中' : '未监控' }}</v-chip>
              <v-btn icon="mdi-pencil-outline" variant="text" size="small" title="编辑路径规则" @click="openRuleEditor(index)" />
              <v-btn icon="mdi-delete-outline" color="error" variant="text" size="small" title="删除路径规则" @click="requestRemoveRule(index)" />
            </div>
          </article>
        </v-sheet>
      </section>

      <section class="setting-section">
        <v-expansion-panels variant="accordion">
          <v-expansion-panel>
            <v-expansion-panel-title>高级兼容设置</v-expansion-panel-title>
            <v-expansion-panel-text>
              <p class="advanced-intro">这些选项适合已有路径映射、媒体库或文件格式兼容需求的用户。</p>
              <v-row dense>
                <v-col cols="12" md="6"><v-textarea v-model="config.rmt_mediaext" label="视频格式扩展名" rows="3" auto-grow variant="outlined" density="compact" hint="使用英文逗号分隔，例如 .mp4, .mkv" persistent-hint /></v-col>
                <v-col cols="12" md="6"><v-textarea v-model="config.other_mediaext" label="旁车文件格式" rows="3" auto-grow variant="outlined" density="compact" hint="使用英文逗号分隔，例如 .nfo, .jpg" persistent-hint /></v-col>
                <v-col cols="12" md="6"><v-textarea v-model="config.emby_path" label="媒体库路径映射" rows="3" auto-grow variant="outlined" density="compact" hint="本地路径=>Emby 路径，多组用英文逗号分隔。" persistent-hint /></v-col>
                <v-col cols="12" md="6"><v-textarea v-model="config.path_replacements" label="路径替换规则" rows="3" auto-grow variant="outlined" density="compact" hint="来源路径=>目标路径，每行一条。" persistent-hint /></v-col>
              </v-row>
            </v-expansion-panel-text>
          </v-expansion-panel>
        </v-expansion-panels>
      </section>
    </v-card-text>

    <v-divider />
    <v-card-actions class="config-actions px-4 py-3 px-sm-6">
      <div v-if="isDirty" class="unsaved-hint"><v-icon icon="mdi-circle" size="9" class="mr-2" />有未保存的更改</div>
      <div v-else class="saved-hint"><v-icon icon="mdi-check-circle-outline" size="17" class="mr-2" />所有更改已保存</div>
      <v-spacer />
      <v-btn variant="tonal" :disabled="!isDirty || saving" @click="resetForm">放弃更改</v-btn>
      <v-btn color="primary" variant="flat" prepend-icon="mdi-content-save" :disabled="!isDirty" :loading="saving" @click="saveConfig">保存更改</v-btn>
    </v-card-actions>
  </v-card>

  <v-dialog v-model="ruleDialog" max-width="760" persistent scrollable>
    <v-card class="config-dialog-card">
      <v-card-item>
        <div>
          <v-card-title class="pa-0">{{ editingRuleIndex === null ? '新增路径规则' : '编辑路径规则' }}</v-card-title>
          <v-card-subtitle class="pa-0 mt-1">{{ ruleStepLabels[ruleStep - 1] }}</v-card-subtitle>
        </div>
        <template #append><v-btn icon="mdi-close" variant="text" title="关闭规则编辑" @click="closeRuleEditor" /></template>
      </v-card-item>
      <v-divider />
      <v-card-text class="pa-4 pa-sm-6">
        <v-stepper v-model="ruleStep" alt-labels hide-actions class="rule-stepper mb-6">
          <v-stepper-header>
            <v-stepper-item :value="1" title="基本信息" />
            <v-divider />
            <v-stepper-item :value="2" title="路径映射" />
            <v-divider />
            <v-stepper-item :value="3" title="输出方式" />
          </v-stepper-header>
        </v-stepper>
        <v-alert v-if="ruleError" type="error" variant="tonal" class="mb-4">{{ ruleError }}</v-alert>
        <template v-if="ruleStep === 1">
          <div class="dialog-section-heading"><h2>给规则一个容易识别的标签</h2><p>标签用于在规则列表中快速判断这条映射处理什么内容。</p></div>
          <v-combobox v-model="ruleDraft.category" label="分类标签" multiple chips closable-chips variant="outlined" hint="输入标签后按回车，例如 国产剧、日剧。" persistent-hint class="mb-5" />
          <v-switch v-model="ruleDraft.monitor" label="实时监控此目录" color="primary" inset hide-details />
          <div class="text-caption text-medium-emphasis mt-2">关闭后，规则仍可参与扫描，但不处理目录的实时变更。</div>
        </template>
        <template v-else-if="ruleStep === 2">
          <div class="dialog-section-heading"><h2>定义路径映射</h2><p>来源目录中的文件会在输出目录中按相同相对路径生成。</p></div>
          <v-text-field v-model.trim="ruleDraft.local" label="来源目录" prepend-inner-icon="mdi-folder-outline" variant="outlined" hint="MoviePilot 看到的挂载路径。" persistent-hint class="mb-4" />
          <v-text-field v-model.trim="ruleDraft.strm" label="STRM 输出目录" prepend-inner-icon="mdi-folder-arrow-right-outline" variant="outlined" hint="生成的 STRM 与旁车文件存放位置。" persistent-hint class="mb-4" />
          <v-text-field v-model.trim="ruleDraft.cloud" label="OpenList 云盘目录" prepend-inner-icon="mdi-cloud-outline" variant="outlined" hint="用于替换生成链接中的云盘路径。" persistent-hint />
        </template>
        <template v-else>
          <div class="dialog-section-heading"><h2>选择输出方式</h2><p>模板必须包含 <code>{local_file}</code> 或 <code>{cloud_file}</code>，否则无法写入正确链接。</p></div>
          <v-text-field v-model.trim="ruleDraft.format" label="STRM 格式模板" variant="outlined" hint="例如 http://127.0.0.1:5244/d{cloud_file}" persistent-hint />
          <v-sheet class="mapping-preview mt-5" border rounded="lg">
            <div class="text-caption text-medium-emphasis mb-2">映射预览</div>
            <div class="preview-line"><span class="path">{{ previewSource }}</span><v-icon icon="mdi-arrow-right" size="18" /><strong class="path">{{ previewOutput }}</strong></div>
            <div class="preview-link mt-3">{{ previewTemplate }}</div>
          </v-sheet>
        </template>
      </v-card-text>
      <v-divider />
      <v-card-actions class="pa-4">
        <v-btn v-if="ruleStep > 1" variant="text" @click="ruleStep -= 1">上一步</v-btn>
        <v-spacer />
        <v-btn variant="tonal" @click="closeRuleEditor">取消</v-btn>
        <v-btn v-if="ruleStep < 3" color="primary" variant="flat" @click="nextRuleStep">下一步</v-btn>
        <v-btn v-else color="primary" variant="flat" @click="commitRule">保存规则</v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>

  <v-dialog v-model="removeRuleDialog" max-width="460">
    <v-card class="config-dialog-card">
      <v-card-title>删除路径规则？</v-card-title>
      <v-card-text>这只会从尚未保存的配置中移除规则。点击“保存更改”后，新的规则列表才会生效。</v-card-text>
      <v-card-actions class="pa-4"><v-spacer /><v-btn variant="tonal" @click="removeRuleDialog = false">取消</v-btn><v-btn color="error" variant="flat" @click="removeRule">删除规则</v-btn></v-card-actions>
    </v-card>
  </v-dialog>

  <v-snackbar v-model="notice.visible" :color="notice.color" timeout="3500">{{ notice.text }}</v-snackbar>
</template>

<script setup>
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'

const props = defineProps({
  initialConfig: { type: Object, default: () => ({}) },
  api: { type: Object, default: () => ({}) },
})
const emit = defineEmits(['save', 'close', 'switch'])

const error = ref(null)
const saving = ref(false)
const ready = ref(false)
const savedSnapshot = ref('')
const savedRuleSlotCount = ref(0)
const ruleDialog = ref(false)
const removeRuleDialog = ref(false)
const editingRuleIndex = ref(null)
const removeRuleIndex = ref(null)
const ruleStep = ref(1)
const ruleError = ref('')
const ruleDraft = reactive({})
const notice = reactive({ visible: false, text: '', color: 'success' })

const defaultConfig = {
  enabled: false, monitor: false, cover: false, notify: false, copy_files: false, copy_subtitles: false, refresh_emby: false, uriencode: false, onlyonce: false, interval: 10, scan_interval: 0, url: '',
  rmt_mediaext: '.mp4, .mkv, .ts, .iso, .rmvb, .avi, .mov, .mpeg, .mpg, .wmv, .3gp, .asf, .m4v, .flv, .m2ts, .strm, .tp, .f4v',
  other_mediaext: '.nfo, .jpg, .png, .json', emby_path: '', path_replacements: '', mediaservers: [], reliable_engine: false, cleanup_mode: 'off', cleanup_probe: '', rules: [],
}
const cleanupModes = [
  { title: '关闭自动清理', value: 'off' },
  { title: '仅处理实时删除事件', value: 'event' },
  { title: '扫描后创建待确认批次', value: 'confirm' },
]
const ruleStepLabels = ['基本信息', '路径映射', '输出方式']
const config = reactive(structuredClone(defaultConfig))

let ruleCounter = 0
const isDirty = computed(() => ready.value && serializeConfig(config) !== savedSnapshot.value)
const previewSource = computed(() => joinPath(ruleDraft.local, '示例/第 01 集.mkv') || '来源目录/示例/第 01 集.mkv')
const previewOutput = computed(() => joinPath(ruleDraft.strm, '示例/第 01 集.strm') || 'STRM 输出目录/示例/第 01 集.strm')
const previewTemplate = computed(() => {
  const cloudPath = joinPath(ruleDraft.cloud, '示例/第 01 集.mkv') || '{cloud_file}'
  return String(ruleDraft.format || '尚未设置 STRM 模板').replaceAll('{local_file}', previewSource.value).replaceAll('{cloud_file}', cloudPath)
})

function makeRule(data = {}) {
  return {
    _key: `rule_${Date.now()}_${++ruleCounter}`,
    category: Array.isArray(data.category) ? [...data.category] : parseCategory(data.category),
    local: String(data.local || ''), strm: String(data.strm || ''), cloud: String(data.cloud || ''), format: String(data.format || ''),
    monitor: data.monitor !== undefined ? Boolean(data.monitor) : true,
  }
}

function parseCategory(value) {
  if (!value) return []
  if (Array.isArray(value)) return value.map(item => String(item).trim()).filter(Boolean)
  return String(value).split(/[,，]+/).map(item => item.trim()).filter(Boolean)
}

function joinPath(root, leaf) {
  const base = String(root || '').replace(/[\\/]+$/, '')
  return base ? `${base}/${leaf}` : ''
}

function serializeConfig(value) {
  const snapshot = structuredClone(value)
  snapshot.rules = (snapshot.rules || []).map(({ _key, ...rule }) => rule)
  return JSON.stringify(snapshot)
}

function applyConfig(source) {
  const incoming = source || {}
  savedRuleSlotCount.value = ruleSlotCount(incoming)
  Object.assign(config, structuredClone(defaultConfig), {
    enabled: Boolean(incoming.enabled), monitor: Boolean(incoming.monitor), cover: Boolean(incoming.cover), notify: Boolean(incoming.notify),
    copy_files: Boolean(incoming.copy_files), copy_subtitles: Boolean(incoming.copy_subtitles), refresh_emby: Boolean(incoming.refresh_emby), uriencode: Boolean(incoming.uriencode), onlyonce: Boolean(incoming.onlyonce),
    interval: incoming.interval != null ? Number(incoming.interval) : 10, scan_interval: incoming.scan_interval != null ? Number(incoming.scan_interval) : 0, url: String(incoming.url || ''),
    rmt_mediaext: String(incoming.rmt_mediaext || defaultConfig.rmt_mediaext), other_mediaext: String(incoming.other_mediaext || defaultConfig.other_mediaext),
    emby_path: String(incoming.emby_path || ''), path_replacements: String(incoming.path_replacements || ''), mediaservers: Array.isArray(incoming.mediaservers) ? [...incoming.mediaservers] : [],
    reliable_engine: Boolean(incoming.reliable_engine), cleanup_mode: cleanupModes.some(mode => mode.value === incoming.cleanup_mode) ? incoming.cleanup_mode : 'off', cleanup_probe: String(incoming.cleanup_probe || ''),
    rules: parseRules(incoming),
  })
}

function ruleSlotCount(incoming) {
  let highestIndex = -1
  Object.keys(incoming || {}).forEach(key => {
    const match = /^rule_(\d+)_/.exec(key)
    if (match) highestIndex = Math.max(highestIndex, Number(match[1]))
  })
  return highestIndex + 1
}

function parseRules(incoming) {
  const rules = []
  let highestIndex = -1
  Object.keys(incoming).forEach(key => {
    const match = /^rule_(\d+)_(?:local|strm)$/.exec(key)
    if (match) highestIndex = Math.max(highestIndex, Number(match[1]))
  })
  for (let index = 0; index <= highestIndex; index += 1) {
    const local = String(incoming[`rule_${index}_local`] || '').trim()
    const strm = String(incoming[`rule_${index}_strm`] || '').trim()
    const deleted = ['1', 'true', 'yes', 'on'].includes(String(incoming[`rule_${index}_delete`] || '').trim().toLowerCase())
    if (!deleted && (local || strm)) {
      rules.push(makeRule({ category: incoming[`rule_${index}_category`], local, strm, cloud: incoming[`rule_${index}_cloud`], format: incoming[`rule_${index}_format`], monitor: incoming[`rule_${index}_monitor`] !== undefined ? incoming[`rule_${index}_monitor`] : true }))
    }
  }
  if (rules.length || !incoming.monitor_confs) return rules
  for (const rawLine of String(incoming.monitor_confs).split('\n')) {
    let line = rawLine.trim()
    if (!line || line.startsWith('#')) continue
    let monitor = true
    if (line.includes('$')) { const [ruleLine, flag] = line.split('$', 2); line = ruleLine; monitor = !['0', 'nomonitor', 'false', 'off'].includes(String(flag).trim().toLowerCase()) }
    let category = ''
    if (line.includes('@')) { const [ruleLine, tags] = line.split('@', 2); line = ruleLine; category = tags }
    const parts = line.split('#')
    if (parts.length < 4) continue
    rules.push(makeRule({ local: parts[0].trim(), strm: parts[1].trim(), cloud: parts[2].trim(), format: parts.slice(3).join('#').trim(), category, monitor }))
  }
  return rules
}

function showNotice(text, color = 'success') { notice.text = text; notice.color = color; notice.visible = true }

function openRuleEditor(index = null) {
  editingRuleIndex.value = index
  Object.assign(ruleDraft, makeRule(index === null ? { format: '{cloud_file}' } : config.rules[index]))
  ruleStep.value = 1
  ruleError.value = ''
  ruleDialog.value = true
}

function closeRuleEditor() {
  ruleDialog.value = false
  ruleError.value = ''
  Object.keys(ruleDraft).forEach(key => delete ruleDraft[key])
}

function validateRule(step) {
  if (step >= 2 && !String(ruleDraft.local || '').trim()) return '请填写来源目录。'
  if (step >= 2 && !String(ruleDraft.strm || '').trim()) return '请填写 STRM 输出目录。'
  if (step >= 3 && !String(ruleDraft.format || '').trim()) return '请填写 STRM 格式模板。'
  if (step >= 3 && !['{local_file}', '{cloud_file}'].some(token => String(ruleDraft.format).includes(token))) return 'STRM 格式模板必须包含 {local_file} 或 {cloud_file}。'
  if (step >= 3 && String(ruleDraft.format).includes('{cloud_file}') && !String(ruleDraft.cloud || '').trim()) return '使用 {cloud_file} 模板时，请填写 OpenList 云盘目录。'
  return ''
}

function nextRuleStep() {
  ruleError.value = validateRule(ruleStep.value)
  if (!ruleError.value) ruleStep.value += 1
}

function commitRule() {
  ruleError.value = validateRule(3)
  if (ruleError.value) return
  const rule = makeRule(ruleDraft)
  if (editingRuleIndex.value === null) config.rules.push(rule)
  else config.rules.splice(editingRuleIndex.value, 1, rule)
  closeRuleEditor()
  showNotice(editingRuleIndex.value === null ? '路径规则已加入待保存更改' : '路径规则已更新，记得保存更改')
}

function requestRemoveRule(index) { removeRuleIndex.value = index; removeRuleDialog.value = true }
function removeRule() {
  if (removeRuleIndex.value !== null) config.rules.splice(removeRuleIndex.value, 1)
  removeRuleIndex.value = null
  removeRuleDialog.value = false
  showNotice('路径规则已移除，记得保存更改')
}

function resetForm() {
  if (!savedSnapshot.value) return
  const restored = JSON.parse(savedSnapshot.value)
  Object.assign(config, restored, { rules: (restored.rules || []).map(makeRule) })
  error.value = null
  showNotice('已放弃未保存的更改', 'info')
}

function buildPayload() {
  const payload = {
    enabled: config.enabled, monitor: config.monitor, cover: config.cover, notify: config.notify, copy_files: config.copy_files, copy_subtitles: config.copy_subtitles,
    refresh_emby: config.refresh_emby, uriencode: config.uriencode, onlyonce: config.onlyonce, interval: Math.max(0, Number(config.interval) || 0),
    scan_interval: Math.max(0, Number(config.scan_interval) || 0), url: config.url, rmt_mediaext: config.rmt_mediaext, other_mediaext: config.other_mediaext,
    emby_path: config.emby_path, path_replacements: config.path_replacements, mediaservers: config.mediaservers, reliable_engine: config.reliable_engine, cleanup_mode: config.cleanup_mode, cleanup_probe: config.cleanup_probe, config_version: 2,
  }
  config.rules.forEach((rule, index) => {
    payload[`rule_${index}_category`] = (rule.category || []).join(',')
    payload[`rule_${index}_local`] = rule.local
    payload[`rule_${index}_strm`] = rule.strm
    payload[`rule_${index}_cloud`] = rule.cloud
    payload[`rule_${index}_format`] = rule.format
    payload[`rule_${index}_monitor`] = rule.monitor
    payload[`rule_${index}_delete`] = false
  })
  for (let index = config.rules.length; index < savedRuleSlotCount.value; index += 1) {
    payload[`rule_${index}_delete`] = true
  }
  return payload
}

async function saveConfig() {
  saving.value = true
  error.value = null
  try {
    const invalidRule = config.rules.find(rule => validateRuleForSave(rule))
    if (invalidRule) throw new Error(validateRuleForSave(invalidRule))
    emit('save', buildPayload())
    savedRuleSlotCount.value = config.rules.length
    savedSnapshot.value = serializeConfig(config)
    showNotice('配置已提交，新的同步设置将按宿主保存流程应用。')
  } catch (err) {
    error.value = err.message || '保存配置失败'
  } finally {
    saving.value = false
  }
}

function validateRuleForSave(rule) {
  if (!String(rule.local || '').trim() || !String(rule.strm || '').trim()) return '每条路径规则都需要来源目录和 STRM 输出目录。'
  if (!String(rule.format || '').trim() || !['{local_file}', '{cloud_file}'].some(token => String(rule.format).includes(token))) return '每条路径规则的 STRM 模板都必须包含 {local_file} 或 {cloud_file}。'
  if (String(rule.format).includes('{cloud_file}') && !String(rule.cloud || '').trim()) return '使用 {cloud_file} 模板的路径规则需要填写 OpenList 云盘目录。'
  return ''
}

onMounted(async () => {
  applyConfig(props.initialConfig)
  await nextTick()
  savedSnapshot.value = serializeConfig(config)
  ready.value = true
})

watch(() => props.initialConfig, value => {
  if (!ready.value || isDirty.value) return
  applyConfig(value)
  savedSnapshot.value = serializeConfig(config)
}, { deep: true })
</script>

<style scoped>
.cloudstrm-config,
.config-dialog-card {
  --v-theme-primary: 45, 96, 115;
  --v-theme-on-primary: 255, 255, 255;
  --v-theme-success: 47, 132, 90;
  --v-theme-warning: 185, 112, 56;
  --v-theme-error: 174, 77, 46;
  --v-theme-surface: 255, 255, 255;
  --v-theme-surface-variant: 237, 242, 246;
  --v-theme-on-surface: 34, 48, 69;
  --v-theme-on-surface-variant: 100, 117, 140;
  color: #223045;
}

.cloudstrm-config {
  overflow: hidden;
  background: #fbfcfe !important;
  border: 1px solid #d9e2eb !important;
  border-radius: 10px !important;
  box-shadow: 0 12px 28px rgba(27, 45, 67, .08) !important;
}

.cloudstrm-config :deep(.v-card-item),
.cloudstrm-config :deep(.v-card-text),
.cloudstrm-config :deep(.v-card-actions),
.config-dialog-card :deep(.v-card-item),
.config-dialog-card :deep(.v-card-text),
.config-dialog-card :deep(.v-card-actions) { background: #fbfcfe; }
.cloudstrm-config :deep(.v-card-title), .config-dialog-card :deep(.v-card-title) { color: #1f2d42 !important; }.cloudstrm-config :deep(.v-card-subtitle), .cloudstrm-config :deep(.text-medium-emphasis), .config-dialog-card :deep(.v-card-subtitle), .config-dialog-card :deep(.text-medium-emphasis) { color: #66758c !important; opacity: 1 !important; }.cloudstrm-config :deep(.v-divider), .config-dialog-card :deep(.v-divider) { border-color: #dfe6ee !important; opacity: 1 !important; }.cloudstrm-config :deep(.v-btn--variant-text) { color: #2d6073 !important; }

.config-header :deep(.v-card-title) { font-size: 23px; letter-spacing: 0; }.config-body { max-height: min(74vh, 920px); overflow-y: auto; }.setting-section + .setting-section { margin-top: 32px; }.section-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; margin-bottom: 12px; }.section-heading h2, .dialog-section-heading h2 { margin: 0; color: #26354b; font-size: 17px; line-height: 1.4; letter-spacing: 0; }.section-heading p, .dialog-section-heading p { margin: 4px 0 0; color: #66758c; font-size: 13px; }.settings-surface { padding: 18px; border-color: #d6e0e9 !important; border-radius: 8px !important; background: #fff !important; }.settings-surface :deep(.v-switch), .settings-surface :deep(.v-input), .config-dialog-card :deep(.v-input) { color: #26354b !important; }.settings-surface :deep(.v-label), .config-dialog-card :deep(.v-label) { color: #5d6f86 !important; opacity: 1 !important; }.settings-surface :deep(.v-field), .config-dialog-card :deep(.v-field) { background: #fff !important; color: #26354b !important; }.settings-surface :deep(.v-field__outline), .config-dialog-card :deep(.v-field__outline) { --v-field-border-opacity: 1; color: #b9c7d5 !important; }.settings-surface :deep(.v-messages), .config-dialog-card :deep(.v-messages) { color: #718096 !important; opacity: 1 !important; }.settings-surface :deep(.v-selection-control--dirty .v-selection-control__input), .config-dialog-card :deep(.v-selection-control--dirty .v-selection-control__input) { color: #2d6073 !important; }
.rule-list { overflow: hidden; border-color: #d6e0e9 !important; border-radius: 8px !important; background: #fff !important; }.rule-row { padding: 18px; display: flex; align-items: center; gap: 20px; color: #26354b; }.rule-row + .rule-row { border-top: 1px solid #e3e9ef; }.rule-flow { min-width: 0; flex: 1; display: grid; grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr); align-items: center; gap: 16px; }.rule-path { min-width: 0; display: flex; flex-direction: column; gap: 5px; }.rule-path > span, .rule-path > small { color: #6a7b91; font-size: 12px; }.rule-path strong { color: #26354b; font-size: 14px; }.rule-tags { display: flex; flex-wrap: wrap; gap: 4px; align-items: center; }.rule-tags small { color: #6a7b91; font-size: 12px; }.flow-arrow { color: #718096; }.rule-actions { display: flex; align-items: center; gap: 4px; }.config-actions { min-height: 68px; }.unsaved-hint, .saved-hint { display: flex; align-items: center; font-size: 13px; }.unsaved-hint { color: #a45c3a; }.unsaved-hint :deep(.v-icon) { color: #c87445; }.saved-hint { color: #66758c; }.advanced-intro { margin: 0 0 20px; color: #66758c; font-size: 13px; }.cloudstrm-config :deep(.v-expansion-panel), .cloudstrm-config :deep(.v-expansion-panel-title), .cloudstrm-config :deep(.v-expansion-panel-text__wrapper) { background: #fff !important; color: #26354b !important; }.rule-stepper { box-shadow: none !important; border: 1px solid #d5e0e9; border-radius: 8px; background: #fff !important; }.config-dialog-card { background: #fbfcfe !important; color: #26354b; }.config-dialog-card :deep(.v-stepper-header) { box-shadow: none !important; }.mapping-preview { padding: 16px; border-color: #d5e0ea !important; background: #f4f8fb; color: #26354b; }.preview-line { display: flex; align-items: center; gap: 10px; font-size: 13px; }.preview-link { padding: 10px; border-radius: 4px; background: #fff; overflow-wrap: anywhere; word-break: break-word; color: #50677d; font-family: Consolas, monospace; font-size: 12px; }.path { overflow-wrap: anywhere; word-break: break-word; } code { padding: 1px 4px; border-radius: 3px; background: #eaf0f5; color: #304b60; font-family: Consolas, monospace; font-size: .9em; }
@media (max-width: 760px) { .config-body { max-height: 72vh; }.settings-surface { padding: 14px; }.rule-row { align-items: flex-start; padding: 16px; }.rule-flow { grid-template-columns: 1fr; gap: 12px; }.flow-arrow { display: none; }.rule-actions { flex-wrap: wrap; justify-content: flex-end; }.config-actions { flex-wrap: wrap; }.config-actions :deep(.v-spacer) { display: none; }.saved-hint, .unsaved-hint { width: 100%; }.preview-line { align-items: flex-start; flex-direction: column; }.preview-line :deep(.v-icon) { transform: rotate(90deg); } }
</style>
