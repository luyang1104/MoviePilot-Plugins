<template>
  <div
    class="config-root"
    :class="{ 'config-root--embedded': embedded, 'v-theme--dark': embedded }"
    :style="embedded ? { colorScheme: 'dark' } : undefined"
  >
    <div v-if="!embedded" class="standalone-header">
      <div>
        <strong>云盘 Strm 小管家</strong>
        <span>插件配置</span>
      </div>
      <v-btn icon="mdi-close" variant="text" size="small" title="关闭配置" aria-label="关闭配置" @click="emit('close')" />
    </div>
    <div v-if="!embedded" class="standalone-divider" aria-hidden="true"></div>

    <section class="config-panel" aria-labelledby="config-title">
    <div class="config-intro">
      <div>
        <span class="eyebrow">SETTINGS</span>
        <h1 id="config-title">插件配置</h1>
        <p>配置同步行为、目录映射和媒体库兼容规则。</p>
      </div>
      <div class="config-state" :class="{ 'is-enabled': config.enabled }">
        <span class="config-state-dot" aria-hidden="true"></span>
        <span>{{ config.enabled ? '插件已启用' : '插件未启用' }}</span>
      </div>
    </div>

    <v-alert v-if="error" type="error" variant="tonal" class="config-alert" closable @click:close="error = null">
      {{ error }}
    </v-alert>
    <v-alert v-if="saved" type="success" variant="tonal" class="config-alert" closable @click:close="saved = false">
      配置已提交给宿主保存流程
    </v-alert>

    <div class="config-module-grid">
      <section class="config-module config-module--runtime" aria-labelledby="runtime-settings-title">
        <div class="module-heading">
          <div class="module-title-wrap">
            <div class="module-icon" aria-hidden="true"><v-icon size="18">mdi-power-settings</v-icon></div>
            <div>
              <h2 id="runtime-settings-title">基础运行</h2>
              <p>控制插件工作方式与常用同步动作。</p>
            </div>
          </div>
          <span class="module-status" :class="{ 'is-enabled': config.enabled }">{{ config.enabled ? '已启用' : '未启用' }}</span>
        </div>

        <div class="switch-grid">
          <v-switch v-model="config.enabled" label="启用插件" color="primary" density="compact" hide-details />
          <v-switch v-model="config.monitor" label="实时监控" color="primary" density="compact" hide-details />
          <v-switch v-model="config.notify" label="入库通知" color="primary" density="compact" hide-details />
          <v-switch v-model="config.refresh_emby" label="刷新 Emby" color="primary" density="compact" hide-details />
          <v-switch v-model="config.cover" label="覆盖已有文件" color="primary" density="compact" hide-details />
          <v-switch v-model="config.copy_files" label="复制旁车文件" color="primary" density="compact" hide-details />
          <v-switch v-model="config.copy_subtitles" label="复制字幕" color="primary" density="compact" hide-details />
          <v-switch v-model="config.uriencode" label="URL 编码" color="primary" density="compact" hide-details />
        </div>
      </section>

      <section class="config-module" aria-labelledby="reliable-settings-title">
        <div class="module-heading">
          <div class="module-title-wrap">
            <div class="module-icon" aria-hidden="true"><v-icon size="18">mdi-shield-sync-outline</v-icon></div>
            <div>
              <h2 id="reliable-settings-title">清理与重试</h2>
              <p>失败任务会保留，修复问题后可以重新处理；缺失文件清理需要确认。</p>
            </div>
          </div>
        </div>

        <div class="field-grid field-grid--three">
          <div class="field-block">
            <v-select v-model="config.cleanup_mode" label="缺失文件清理" :items="cleanupModes" variant="outlined" density="compact" hide-details />
            <span class="field-hint">扫描后决定缺失 STRM 的处理方式。</span>
          </div>
          <div class="field-block">
            <v-text-field v-model="config.cleanup_probe" label="清理探针文件（可选）" variant="outlined" density="compact" hide-details />
            <span class="field-hint">探针不存在时跳过清理扫描。</span>
          </div>
          <div class="field-block">
            <v-text-field v-model="config.url" label="任务推送 URL" variant="outlined" density="compact" hide-details />
            <span class="field-hint">可选，用于接收外部任务推送。</span>
          </div>
        </div>
        <div class="field-grid field-grid--two field-grid--bottom">
          <v-text-field v-model="config.interval" label="消息延迟（秒）" type="number" variant="outlined" density="compact" hide-details />
          <v-text-field v-model="config.scan_interval" label="全量扫描周期（分钟）" type="number" variant="outlined" density="compact" hide-details />
        </div>
      </section>
    </div>

    <section class="config-module rules-module" aria-labelledby="rules-title">
      <div class="module-heading section-heading">
        <div class="module-title-wrap">
          <div class="module-icon" aria-hidden="true"><v-icon size="18">mdi-source-branch</v-icon></div>
          <div>
            <h2 id="rules-title">目录规则</h2>
            <p>将来源目录映射到 STRM 输出目录和云盘路径。</p>
          </div>
        </div>
        <v-btn color="primary" variant="tonal" size="small" prepend-icon="mdi-plus" @click="addRule">新增规则</v-btn>
      </div>

      <div v-if="config.rules.length === 0" class="rules-empty">
        <div class="empty-icon" aria-hidden="true"><v-icon size="19">mdi-source-branch-plus</v-icon></div>
        <strong>还没有目录规则</strong>
        <span>新增一条规则后，插件才会知道从哪里读取和输出 STRM。</span>
        <v-btn color="primary" variant="tonal" size="small" prepend-icon="mdi-plus" class="mt-3" @click="addRule">新增第一条规则</v-btn>
      </div>

      <div v-else class="rules-list">
        <article v-for="(rule, index) in config.rules" :key="rule._key" class="rule-card">
          <div class="rule-card-top">
            <div class="rule-number">{{ String(index + 1).padStart(2, '0') }}</div>
            <div class="rule-card-title">
              <strong>映射规则 {{ index + 1 }}</strong>
              <span>{{ rule.local || '尚未填写来源目录' }}</span>
            </div>
            <div class="rule-card-actions">
              <v-switch v-model="rule.monitor" label="监控" color="primary" density="compact" hide-details />
              <v-btn icon="mdi-delete-outline" size="small" variant="text" color="error" title="删除此规则" aria-label="删除此规则" @click="removeRule(index)" />
            </div>
          </div>

          <div class="rule-fields">
            <v-combobox v-model="rule.category" class="rule-field--wide" label="分类标签" multiple chips closable-chips variant="outlined" density="compact" hide-details placeholder="输入标签后回车，如：国产剧、日韩剧" />
            <v-text-field v-model="rule.local" label="CD2 挂载目录（MoviePilot 中路径）" variant="outlined" density="compact" hide-details placeholder="/CloudNAS/CloudDrive/WebDrive/国产剧" />
            <v-text-field v-model="rule.strm" label="STRM 生成目录" variant="outlined" density="compact" hide-details placeholder="/CloudNAS/云盘Strm/media/国产剧" />
            <v-text-field v-model="rule.cloud" label="OpenList 云盘目录" variant="outlined" density="compact" hide-details placeholder="/media/国产剧" />
            <v-text-field v-model="rule.format" class="rule-field--wide" label="STRM 格式化模板" variant="outlined" density="compact" hide-details placeholder="http://192.168.1.10:5244/d{cloud_file}" />
          </div>
        </article>
      </div>
    </section>

    <section class="config-module advanced-module" aria-labelledby="advanced-title">
      <button class="advanced-toggle" type="button" :aria-expanded="advancedOpen" @click="advancedOpen = !advancedOpen">
        <span class="module-title-wrap">
          <span class="module-icon" aria-hidden="true"><v-icon size="18">mdi-tune-variant</v-icon></span>
          <span>
            <strong id="advanced-title">高级兼容设置</strong>
            <small>媒体扩展名、媒体库映射与路径替换</small>
          </span>
        </span>
        <v-icon size="20">{{ advancedOpen ? 'mdi-chevron-up' : 'mdi-chevron-down' }}</v-icon>
      </button>

      <div v-if="advancedOpen" class="advanced-content">
        <div class="field-grid field-grid--two">
          <div class="field-block">
            <v-textarea v-model="config.rmt_mediaext" label="视频格式扩展名" rows="3" variant="outlined" density="compact" hide-details placeholder=".mp4, .mkv, .ts, .iso ..." />
            <span class="field-hint">使用英文逗号分隔，例如 .mp4, .mkv。</span>
          </div>
          <div class="field-block">
            <v-textarea v-model="config.other_mediaext" label="旁车文件格式" rows="3" variant="outlined" density="compact" hide-details placeholder=".nfo, .jpg, .png, .json" />
            <span class="field-hint">会随媒体文件一起处理的附属文件。</span>
          </div>
          <div class="field-block">
            <v-textarea v-model="config.subtitle_formats" label="字幕文字格式" rows="3" variant="outlined" density="compact" hide-details placeholder=".srt, .ass, .ssa, .sub, .vtt" />
            <span class="field-hint">开启复制字幕后，按这里填写的扩展名识别字幕。</span>
          </div>
          <div class="field-block">
            <v-textarea v-model="config.emby_path" label="媒体库路径映射" rows="3" variant="outlined" density="compact" hide-details placeholder="本地路径=>Emby路径，多组用英文逗号分隔" />
            <span class="field-hint">将生成文件路径转换为媒体服务器可见路径。</span>
          </div>
          <div class="field-block">
            <v-textarea v-model="config.path_replacements" label="路径替换规则" rows="3" variant="outlined" density="compact" hide-details placeholder="源路径=>目标路径，每行一条规则" />
            <span class="field-hint">每行一条替换规则，按顺序应用。</span>
          </div>
        </div>
      </div>
    </section>

    <footer class="config-action-footer">
      <div class="save-state" :class="{ 'is-saved': saved }">
        <v-icon size="17">{{ saved ? 'mdi-check-circle-outline' : 'mdi-information-outline' }}</v-icon>
        <span>{{ saved ? (embedded ? '配置已保存并回读确认' : '配置已提交给宿主保存流程') : '修改后记得保存配置' }}</span>
      </div>
      <div class="footer-actions">
        <v-btn v-if="!embedded && hasPage" variant="text" prepend-icon="mdi-chart-box-outline" @click="emit('switch')">查看数据</v-btn>
        <v-btn variant="tonal" color="secondary" @click="resetForm">重置</v-btn>
        <v-btn color="primary" variant="flat" prepend-icon="mdi-content-save-outline" :disabled="!isDirty || saving" :loading="saving" @click="saveConfig">保存配置</v-btn>
      </div>
    </footer>
    </section>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
import { buildConfigPayload, normalizeBoolean, parseConfigRules, serializeConfig } from './config_payload.js'
import { savePluginConfig } from './config_persistence.js'

const props = defineProps({
  initialConfig: { type: Object, default: () => ({}) },
  api: { type: Object, default: () => ({}) },
  embedded: { type: Boolean, default: false },
})

const emit = defineEmits(['save', 'close', 'switch'])
const error = ref(null)
const saved = ref(false)
const saving = ref(false)
const ready = ref(false)
const savedSnapshot = ref('')
const savedRuleSlotCount = ref(0)
const hasPage = ref(false)
const advancedOpen = ref(false)

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
  subtitle_formats: '.srt, .ass, .ssa, .sub, .vtt',
  emby_path: '',
  path_replacements: '',
  mediaservers: [],
  // The durable queue is the default for new configurations; an explicit
  // legacy false value is still preserved when the host returns it.
  reliable_engine: true,
  cleanup_mode: 'off',
  cleanup_probe: '',
  rules: [],
}

const cleanupModes = [
  { title: '关闭自动清理', value: 'off' },
  { title: '仅确认文件事件删除', value: 'event' },
  { title: '扫描后进入待确认批次', value: 'confirm' },
]

const config = reactive(structuredClone(defaultConfig))
let ruleCounter = 0

const isDirty = computed(() => ready.value && serializeConfig(config) !== savedSnapshot.value)

function makeRule(data = {}) {
  return {
    _key: 'rule_' + Date.now() + '_' + (++ruleCounter),
    category: Array.isArray(data.category) ? [...data.category] : parseCategory(data.category),
    local: String(data.local || ''),
    strm: String(data.strm || ''),
    cloud: String(data.cloud || ''),
    format: String(data.format || ''),
    monitor: data.monitor !== undefined ? normalizeBoolean(data.monitor) : true,
  }
}

function hydrate(source) {
  const ic = source || {}
  savedRuleSlotCount.value = ruleSlotCount(ic)
  config.enabled = normalizeBoolean(ic.enabled)
  config.monitor = normalizeBoolean(ic.monitor)
  config.cover = normalizeBoolean(ic.cover)
  config.notify = normalizeBoolean(ic.notify)
  config.copy_files = normalizeBoolean(ic.copy_files)
  config.copy_subtitles = normalizeBoolean(ic.copy_subtitles)
  config.refresh_emby = normalizeBoolean(ic.refresh_emby)
  config.uriencode = normalizeBoolean(ic.uriencode)
  config.onlyonce = normalizeBoolean(ic.onlyonce)
  config.interval = ic.interval != null ? Number(ic.interval) : 10
  config.scan_interval = ic.scan_interval != null ? Number(ic.scan_interval) : 0
  config.url = String(ic.url || '')
  config.rmt_mediaext = String(ic.rmt_mediaext || defaultConfig.rmt_mediaext)
  config.other_mediaext = String(ic.other_mediaext || defaultConfig.other_mediaext)
  config.subtitle_formats = String(ic.subtitle_formats || defaultConfig.subtitle_formats)
  config.emby_path = String(ic.emby_path || '')
  config.path_replacements = String(ic.path_replacements || '')
  config.mediaservers = Array.isArray(ic.mediaservers) ? [...ic.mediaservers] : []
  config.reliable_engine = normalizeBoolean(ic.reliable_engine, true)
  config.cleanup_mode = ['off', 'event', 'confirm'].includes(ic.cleanup_mode) ? ic.cleanup_mode : 'off'
  config.cleanup_probe = String(ic.cleanup_probe || '')
  config.rules = parseConfigRules(ic).map(makeRule)
}

onMounted(async () => {
  hydrate(props.initialConfig)
  await nextTick()
  savedSnapshot.value = serializeConfig(config)
  ready.value = true
})

watch(isDirty, dirty => {
  if (dirty) saved.value = false
})

watch(() => props.initialConfig, value => {
  if (!ready.value || isDirty.value) return
  hydrate(value)
  savedSnapshot.value = serializeConfig(config)
}, { deep: true })

function ruleSlotCount(source) {
  let highestIndex = -1
  Object.keys(source || {}).forEach(key => {
    const match = /^rule_(\d+)_/.exec(key)
    if (match) highestIndex = Math.max(highestIndex, Number(match[1]))
  })
  return highestIndex + 1
}

function parseCategory(value) {
  if (!value) return []
  if (Array.isArray(value)) return value.map(item => String(item).trim()).filter(Boolean)
  return String(value).split(/[,，]+/).map(item => item.trim()).filter(Boolean)
}

function addRule() {
  config.rules.push(makeRule())
}

function removeRule(index) {
  config.rules.splice(index, 1)
}

function resetForm() {
  if (!savedSnapshot.value || saving.value) return
  const restored = JSON.parse(savedSnapshot.value)
  Object.assign(config, restored, { rules: (restored.rules || []).map(makeRule) })
  saved.value = false
  error.value = null
}

async function saveConfig() {
  if (!isDirty.value || saving.value) return
  saving.value = true
  saved.value = false
  error.value = null
  try {
    const payload = buildConfigPayload(config, savedRuleSlotCount.value)
    if (props.embedded) {
      // The data-page host does not listen for the Config save event. Persist
      // through MoviePilot here and hydrate from its canonical response.
      const persisted = await savePluginConfig(props.api, payload)
      hydrate(persisted)
      savedSnapshot.value = serializeConfig(config)
      emit('save', persisted)
    } else {
      // The standard config dialog owns persistence for Vue plugin forms.
      emit('save', payload)
      savedRuleSlotCount.value = Math.max(savedRuleSlotCount.value, config.rules.length)
      savedSnapshot.value = serializeConfig(config)
    }
    saved.value = true
  } catch (err) {
    error.value = err.message || '保存失败'
  } finally {
    saving.value = false
  }
}
</script>

<style scoped>
.config-panel {
  --cs-bg: #fbfcfe;
  --cs-surface: #ffffff;
  --cs-surface-raised: #f4f8fb;
  --cs-surface-inset: #f7f9fb;
  --cs-line: #dbe3eb;
  --cs-line-strong: #bdc9d5;
  --cs-text: #24314a;
  --cs-muted: #66758c;
  --cs-dim: #8d99aa;
  --cs-primary: #2d6073;
  --cs-primary-soft: #4c8390;
  --cs-success: #48a476;
  --cs-danger: #b9633e;
  background: transparent;
  color: var(--cs-text);
  font-family: "SF Pro Display", "PingFang SC", "Microsoft YaHei", sans-serif;
  letter-spacing: 0;
  line-height: 1.45;
}

.standalone-header { align-items: center; display: flex; justify-content: space-between; padding: 16px 20px; }
.standalone-header strong, .standalone-header span { display: block; }
.standalone-header strong { font-size: 16px; font-weight: 700; }
.standalone-header span { color: var(--cs-dim); font-size: 11px; margin-top: 3px; }
.standalone-divider { background: var(--cs-line); height: 1px; }

.config-intro { align-items: flex-end; display: flex; justify-content: space-between; margin-bottom: 24px; }
.eyebrow { color: var(--cs-primary-soft); display: block; font-size: 10px; font-weight: 800; letter-spacing: 1.1px; margin-bottom: 8px; }
h1, h2, p { margin: 0; }
h1 { font-size: 25px; font-weight: 700; line-height: 1.2; }
.config-intro p { color: var(--cs-muted); font-size: 13px; margin-top: 8px; }
.config-state { align-items: center; border-left: 1px solid var(--cs-line); color: var(--cs-dim); display: flex; font-size: 12px; gap: 7px; padding: 9px 0 9px 16px; }
.config-state-dot { background: var(--cs-dim); border-radius: 50%; height: 7px; width: 7px; }
.config-state.is-enabled { color: var(--cs-success); }
.config-state.is-enabled .config-state-dot { background: var(--cs-success); box-shadow: 0 0 0 4px rgba(72, 164, 118, .14); }
.config-alert { margin-bottom: 18px; }

.config-module { background: var(--cs-surface); border: 1px solid var(--cs-line); border-radius: 8px; min-width: 0; padding: 20px; }
.config-module-grid { display: grid; gap: 14px; grid-template-columns: minmax(0, 1fr) minmax(0, 1.35fr); margin-bottom: 14px; }
.module-heading { align-items: flex-start; display: flex; justify-content: space-between; margin-bottom: 19px; }
.module-title-wrap { align-items: flex-start; display: flex; gap: 11px; min-width: 0; }
.module-icon { align-items: center; background: #e6f0f3; border: 1px solid #c9dce2; border-radius: 7px; color: var(--cs-primary); display: flex; flex: 0 0 33px; height: 33px; justify-content: center; width: 33px; }
h2 { font-size: 15px; font-weight: 700; line-height: 1.3; }
.module-heading p { color: var(--cs-dim); font-size: 12px; margin-top: 5px; }
.module-status { border: 1px solid var(--cs-line-strong); border-radius: 4px; color: var(--cs-dim); font-size: 11px; padding: 4px 7px; white-space: nowrap; }
.module-status.is-enabled { background: #e7f5ec; border-color: #c6e6d2; color: #2d7052; }

.switch-grid { display: grid; gap: 5px 12px; grid-template-columns: repeat(2, minmax(0, 1fr)); }
.switch-grid :deep(.v-switch) { min-width: 0; }
.switch-grid :deep(.v-label), .config-panel :deep(.v-label) { color: var(--cs-muted); font-size: 12px; opacity: 1; }
.config-panel :deep(.v-selection-control) { min-height: 34px; }
.config-panel :deep(.v-switch .v-selection-control__wrapper) { transform: scale(.82); transform-origin: left center; width: 35px; }
.config-panel :deep(.v-switch .v-label) { margin-inline-start: 0; }

.field-grid { display: grid; gap: 15px 12px; }
.field-grid--three { grid-template-columns: repeat(3, minmax(0, 1fr)); }
.field-grid--two { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.field-grid--bottom { margin-top: 13px; }
.field-block { min-width: 0; }
.field-hint { color: var(--cs-dim); display: block; font-size: 11px; line-height: 1.35; margin: 7px 2px 0; }
.config-panel :deep(.v-field) { --v-field-border-opacity: 1; background: var(--cs-surface-inset); border-radius: 5px; color: var(--cs-text); }
.config-panel :deep(.v-field__outline) { color: var(--cs-line-strong); }
.config-panel :deep(.v-field--focused .v-field__outline) { color: var(--cs-primary); }
.config-panel :deep(.v-field__input), .config-panel :deep(.v-field__append-inner), .config-panel :deep(.v-field__prepend-inner) { color: var(--cs-text); font-size: 12px; }
.config-panel :deep(.v-field__input input::placeholder), .config-panel :deep(textarea::placeholder) { color: #8d99aa; opacity: 1; }
.config-panel :deep(.v-label) { color: var(--cs-muted); font-size: 11px; }

.rules-module { margin-bottom: 14px; }
.section-heading { align-items: center; }
.section-heading :deep(.v-btn) { flex: 0 0 auto; }
.rules-empty { align-items: center; border: 1px dashed var(--cs-line-strong); border-radius: 6px; color: var(--cs-dim); display: flex; flex-direction: column; justify-content: center; min-height: 164px; padding: 24px; text-align: center; }
.empty-icon { align-items: center; background: #eff3f6; border: 1px solid var(--cs-line); border-radius: 50%; color: var(--cs-muted); display: flex; height: 34px; justify-content: center; margin-bottom: 10px; width: 34px; }
.rules-empty strong { color: var(--cs-text); font-size: 13px; }
.rules-empty span { font-size: 12px; margin-top: 5px; }
.rules-list { display: grid; gap: 10px; }
.rule-card { background: var(--cs-surface-raised); border: 1px solid var(--cs-line); border-radius: 7px; padding: 14px; }
.rule-card-top { align-items: center; display: flex; gap: 11px; margin-bottom: 14px; }
.rule-number { align-items: center; background: #e6f0f3; border: 1px solid #c9dce2; border-radius: 5px; color: var(--cs-primary); display: flex; flex: 0 0 32px; font-size: 11px; font-variant-numeric: tabular-nums; height: 32px; justify-content: center; width: 32px; }
.rule-card-title { display: flex; flex: 1; flex-direction: column; min-width: 0; }
.rule-card-title strong { font-size: 13px; font-weight: 650; }
.rule-card-title span { color: var(--cs-dim); font-size: 11px; margin-top: 3px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.rule-card-actions { align-items: center; display: flex; gap: 8px; }
.rule-card-actions :deep(.v-switch) { margin-right: -5px; }
.rule-fields { display: grid; gap: 12px; grid-template-columns: repeat(2, minmax(0, 1fr)); }
.rule-field--wide { grid-column: 1 / -1; }

.advanced-module { overflow: hidden; padding: 0; }
.advanced-toggle { align-items: center; background: transparent; border: 0; color: var(--cs-text); cursor: pointer; display: flex; font: inherit; justify-content: space-between; padding: 16px 20px; text-align: left; width: 100%; }
.advanced-toggle:hover { background: #f7f9fb; }
.advanced-toggle:focus-visible { outline: 2px solid var(--cs-primary); outline-offset: -3px; }
.advanced-toggle .module-title-wrap { align-items: center; }
.advanced-toggle strong, .advanced-toggle small { display: block; }
.advanced-toggle strong { font-size: 13px; font-weight: 650; }
.advanced-toggle small { color: var(--cs-dim); font-size: 11px; margin-top: 3px; }
.advanced-toggle > .v-icon { color: var(--cs-muted); }
.advanced-content { border-top: 1px solid var(--cs-line); padding: 20px; }

.config-action-footer { align-items: center; border-top: 1px solid var(--cs-line); display: flex; justify-content: space-between; margin-top: 28px; padding-top: 17px; }
.save-state { align-items: center; color: var(--cs-dim); display: flex; font-size: 12px; gap: 7px; }
.save-state .v-icon { color: var(--cs-dim); }
.save-state.is-saved { color: var(--cs-success); }
.save-state.is-saved .v-icon { color: var(--cs-success); }
.footer-actions { align-items: center; display: flex; gap: 8px; }

@media (max-width: 1000px) {
  .config-module-grid { grid-template-columns: 1fr; }
}

@media (max-width: 640px) {
  .config-intro { align-items: flex-start; flex-direction: column; gap: 15px; }
  .config-state { border-left: 0; border-top: 1px solid var(--cs-line); padding: 10px 0 0; width: 100%; }
  .config-module { padding: 15px; }
  .switch-grid, .field-grid--three, .field-grid--two, .rule-fields { grid-template-columns: 1fr; }
  .rule-field--wide { grid-column: auto; }
  .rule-card-top { align-items: flex-start; }
  .rule-card-actions { margin-left: auto; }
  .config-action-footer { align-items: stretch; flex-direction: column; gap: 14px; }
  .footer-actions { justify-content: flex-end; }
}

.config-root--embedded .config-panel {
  --cs-bg: #121218;
  --cs-surface: #19191f;
  --cs-surface-raised: #1f1f27;
  --cs-surface-inset: #101016;
  --cs-line: #2d2d38;
  --cs-line-strong: #393844;
  --cs-text: #f2f1f7;
  --cs-muted: #a3a0af;
  --cs-dim: #747181;
  --cs-primary: #8b6cf6;
  --cs-primary-soft: #bcaeff;
  --cs-success: #68d7a2;
  --cs-danger: #ff8a9a;
}

.config-root--embedded .config-panel :deep(.v-field) {
  background: var(--cs-surface-inset);
}

.config-root--embedded .module-icon,
.config-root--embedded .rule-number {
  background: #2b2347;
  border-color: #594b9e;
  color: var(--cs-primary-soft);
}

.config-root--embedded .module-status.is-enabled {
  background: #203b31;
  border-color: #356a54;
  color: var(--cs-success);
}

.config-root--embedded .empty-icon {
  background: #292632;
  border-color: var(--cs-line);
}

.config-root--embedded .rule-card {
  background: var(--cs-surface-raised);
}

.config-root--embedded .advanced-toggle:hover {
  background: rgba(255, 255, 255, .025);
}

.config-root--embedded :deep(.v-field__outline),
.config-root--embedded :deep(.v-field--focused .v-field__outline) {
  color: var(--cs-line-strong);
}

.config-root--embedded :deep(.v-field--focused .v-field__outline) {
  color: var(--cs-primary);
}

.config-root--embedded :deep(.v-label),
.config-root--embedded :deep(.v-field__input),
.config-root--embedded :deep(.v-field__append-inner),
.config-root--embedded :deep(.v-field__prepend-inner) {
  color: var(--cs-muted);
}

.config-root--embedded :deep(.v-field__input),
.config-root--embedded :deep(.v-field__append-inner),
.config-root--embedded :deep(.v-field__prepend-inner) {
  color: var(--cs-text);
}

.config-root--embedded :deep(.v-switch .v-selection-control__input) {
  color: var(--cs-primary);
}

.config-root--embedded :deep(.v-btn.bg-primary.v-btn--variant-flat) {
  background: #8b6cf6 !important;
  background-color: #8b6cf6 !important;
  color: #17121f !important;
}

.config-root--embedded :deep(.v-btn.bg-primary.v-btn--variant-flat:hover:not(:disabled)) {
  background: #9b7eff !important;
  background-color: #9b7eff !important;
}

.config-root--embedded :deep(.v-btn.bg-primary.v-btn--variant-flat:disabled),
.config-root--embedded :deep(.v-btn.bg-primary.v-btn--variant-flat.v-btn--disabled) {
  background: #594b9e !important;
  background-color: #594b9e !important;
  color: #c7bdf0 !important;
}
</style>
