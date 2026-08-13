<template>
  <v-card class="rules-page">
    <v-card-item class="rules-header">
      <div>
        <v-card-title class="pa-0">路径规则</v-card-title>
        <v-card-subtitle class="pa-0 mt-1">管理来源目录、STRM 输出位置与云盘路径映射。</v-card-subtitle>
      </div>
    </v-card-item>

    <v-card-text class="rules-body">
      <v-alert v-if="error" type="error" variant="tonal" closable class="rules-error" @click:close="error = null">{{ error }}</v-alert>
      <section class="rule-summary-bar">
        <div><strong>{{ config.rules.length }} 条规则</strong><span>{{ activeRuleCount }} 条正在监控，{{ inactiveRuleCount }} 条停用</span></div>
        <v-btn class="add-rule-button" color="primary" variant="flat" prepend-icon="mdi-plus" @click="openRuleEditor()">新增路径规则</v-btn>
      </section>

      <section class="rules-table-card">
        <div class="rules-table-head"><span>来源目录</span><span>输出目录</span><span>状态</span><span>操作</span></div>
        <div v-if="config.rules.length" class="rules-table-body">
          <article v-for="(rule, index) in config.rules" :key="rule._key" class="rule-row" :class="{ 'rule-row--selected': editingRuleIndex === index }">
            <div class="rule-source"><strong class="path">{{ rule.local || '尚未设置来源目录' }}</strong><span>{{ ruleMeta(rule) }}</span></div>
            <div class="rule-output"><v-icon icon="mdi-arrow-right" size="21" /><div><strong class="path">{{ rule.strm || '尚未设置输出目录' }}</strong><span class="path">OpenList：{{ rule.cloud || '尚未设置' }}</span></div></div>
            <div><span class="rule-status" :class="rule.monitor ? 'rule-status--active' : 'rule-status--inactive'"><i />{{ rule.monitor ? '监控' : '停用' }}</span></div>
            <div><v-btn class="rule-edit-button" size="small" variant="outlined" @click="openRuleEditor(index)">编辑</v-btn></div>
          </article>
        </div>
        <div v-else class="rules-empty"><v-icon icon="mdi-folder-plus-outline" size="24" />还没有路径规则。新增一条规则后，目录映射会显示在这里。</div>
      </section>

      <section v-if="isDirty" class="unsaved-bar"><v-icon icon="mdi-circle" size="10" /><strong>有未保存的更改</strong><span>修改规则后需保存才会应用。</span></section>
      <section class="runtime-settings">
        <v-expansion-panels variant="accordion">
          <v-expansion-panel>
            <v-expansion-panel-title>运行设置与高级兼容选项</v-expansion-panel-title>
            <v-expansion-panel-text>
              <div class="settings-grid">
                <v-switch v-model="config.enabled" label="启用插件" color="primary" hide-details />
                <v-switch v-model="config.monitor" label="实时监控" color="primary" hide-details />
                <v-switch v-model="config.reliable_engine" label="启用可靠同步引擎" color="primary" hide-details />
                <v-select v-model="config.cleanup_mode" label="缺失文件清理策略" :items="cleanupModes" variant="outlined" density="compact" hide-details />
                <v-text-field v-model.number="config.interval" label="消息延迟（秒）" type="number" min="0" variant="outlined" density="compact" hide-details />
                <v-text-field v-model.number="config.scan_interval" label="全量扫描周期（分钟）" type="number" min="0" variant="outlined" density="compact" hide-details />
                <v-switch v-model="config.copy_files" label="复制旁车文件" color="primary" hide-details />
                <v-switch v-model="config.copy_subtitles" label="复制字幕" color="primary" hide-details />
              </div>
              <v-divider class="my-5" />
              <div class="settings-grid settings-grid--wide">
                <v-textarea v-model="config.rmt_mediaext" label="视频格式扩展名" rows="2" auto-grow variant="outlined" density="compact" />
                <v-textarea v-model="config.other_mediaext" label="旁车文件格式" rows="2" auto-grow variant="outlined" density="compact" />
                <v-textarea v-model="config.emby_path" label="媒体库路径映射" rows="2" auto-grow variant="outlined" density="compact" />
                <v-textarea v-model="config.path_replacements" label="路径替换规则" rows="2" auto-grow variant="outlined" density="compact" />
              </div>
            </v-expansion-panel-text>
          </v-expansion-panel>
        </v-expansion-panels>
      </section>
    </v-card-text>

    <v-card-actions class="rules-actions">
      <div class="save-state"><v-icon :icon="isDirty ? 'mdi-circle' : 'mdi-check-circle-outline'" :size="isDirty ? 9 : 18" />{{ isDirty ? '有未保存的更改' : '所有更改已保存' }}</div>
      <v-spacer />
      <v-btn variant="outlined" :disabled="!isDirty || saving" @click="resetForm">放弃更改</v-btn>
      <v-btn class="save-button" color="primary" variant="flat" :disabled="!isDirty" :loading="saving" @click="saveConfig">保存更改</v-btn>
    </v-card-actions>
  </v-card>

  <v-dialog v-model="ruleDialog" class="rule-drawer-dialog" persistent fullscreen transition="dialog-bottom-transition">
    <aside class="rule-drawer">
      <header class="drawer-header">
        <div><h1>{{ editingRuleIndex === null ? '新增路径规则' : '编辑路径规则' }}</h1><p>{{ ruleName }}</p></div>
        <v-btn icon="mdi-close" variant="text" title="关闭规则编辑" @click="closeRuleEditor" />
      </header>
      <div class="drawer-stepper">
        <div class="step-track" />
        <button v-for="(label, index) in ruleStepLabels" :key="label" class="step" :class="stepClass(index + 1)" type="button" @click="goToStep(index + 1)"><i>{{ stepSymbol(index + 1) }}</i><span>{{ label }}</span></button>
      </div>

      <main class="drawer-body">
        <v-alert v-if="ruleError" type="error" variant="tonal" class="mb-4">{{ ruleError }}</v-alert>
        <template v-if="ruleStep === 1">
          <h2>基本信息</h2><p class="drawer-intro">给这条规则一个容易识别的标签，并确定是否实时监控目录变更。</p>
          <v-combobox v-model="ruleDraft.category" label="分类标签" multiple chips closable-chips variant="outlined" hint="输入标签后按回车，例如 国产剧、电影" persistent-hint class="mb-6" />
          <v-switch v-model="ruleDraft.monitor" label="实时监控此目录" color="primary" inset hide-details />
        </template>
        <template v-else-if="ruleStep === 2">
          <h2>定义路径映射</h2><p class="drawer-intro">文件将从来源目录映射为云盘链接，并写入 STRM 目录。</p>
          <div class="path-field"><label>来源目录</label><v-text-field v-model.trim="ruleDraft.local" prepend-inner-icon="mdi-folder-outline" variant="outlined" hide-details /></div>
          <div class="mapping-arrow"><v-icon icon="mdi-arrow-down" size="32" /></div>
          <div class="path-field"><label>STRM 输出目录</label><v-text-field v-model.trim="ruleDraft.strm" prepend-inner-icon="mdi-folder-outline" variant="outlined" hide-details /></div>
          <div class="path-field path-field--spaced"><label>OpenList 云盘目录</label><v-text-field v-model.trim="ruleDraft.cloud" prepend-inner-icon="mdi-folder-outline" variant="outlined" hide-details /></div>
          <div class="drawer-preview"><strong>映射预览</strong><div><span class="path">{{ previewSource }}</span><v-icon icon="mdi-arrow-right" size="19" /><b class="path">{{ previewOutput }}</b></div></div>
        </template>
        <template v-else>
          <h2>输出方式</h2><p class="drawer-intro">模板必须包含 <code>{local_file}</code> 或 <code>{cloud_file}</code>，才能写入正确的 STRM 链接。</p>
          <v-text-field v-model.trim="ruleDraft.format" label="STRM 格式模板" variant="outlined" hint="例如 http://127.0.0.1:5244/d{cloud_file}" persistent-hint />
          <div class="drawer-preview drawer-preview--template"><strong>生成链接预览</strong><code>{{ previewTemplate }}</code></div>
        </template>
      </main>

      <footer class="drawer-actions">
        <v-btn v-if="ruleStep > 1" variant="text" @click="ruleStep -= 1">上一步</v-btn>
        <v-spacer />
        <v-btn variant="outlined" @click="closeRuleEditor">取消</v-btn>
        <v-btn class="drawer-save-button" variant="flat" @click="advanceOrSave">{{ ruleStep < 3 ? '下一步' : '保存更改' }}</v-btn>
        <p>保存后才会应用到下一次同步。</p>
      </footer>
    </aside>
  </v-dialog>

  <v-dialog v-model="removeRuleDialog" max-width="460">
    <v-card class="remove-dialog-card"><v-card-title>删除路径规则？</v-card-title><v-card-text>这只会从尚未保存的配置中移除规则。点击“保存更改”后，新的规则列表才会生效。</v-card-text><v-card-actions><v-spacer /><v-btn variant="outlined" @click="removeRuleDialog = false">取消</v-btn><v-btn color="error" variant="flat" @click="removeRule">删除规则</v-btn></v-card-actions></v-card>
  </v-dialog>
  <v-snackbar v-model="notice.visible" :color="notice.color" timeout="3500">{{ notice.text }}</v-snackbar>
</template>

<script setup>
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'

const props = defineProps({ initialConfig: { type: Object, default: () => ({}) }, api: { type: Object, default: () => ({}) } })
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

const defaultConfig = { enabled: false, monitor: false, cover: false, notify: false, copy_files: false, copy_subtitles: false, refresh_emby: false, uriencode: false, onlyonce: false, interval: 10, scan_interval: 0, url: '', rmt_mediaext: '.mp4, .mkv, .ts, .iso, .rmvb, .avi, .mov, .mpeg, .mpg, .wmv, .3gp, .asf, .m4v, .flv, .m2ts, .strm, .tp, .f4v', other_mediaext: '.nfo, .jpg, .png, .json', emby_path: '', path_replacements: '', mediaservers: [], reliable_engine: false, cleanup_mode: 'off', cleanup_probe: '', rules: [] }
const cleanupModes = [{ title: '关闭自动清理', value: 'off' }, { title: '仅处理实时删除事件', value: 'event' }, { title: '扫描后创建待确认批次', value: 'confirm' }]
const ruleStepLabels = ['基本信息', '路径映射', '输出方式']
const config = reactive(structuredClone(defaultConfig))
let ruleCounter = 0

const isDirty = computed(() => ready.value && serializeConfig(config) !== savedSnapshot.value)
const activeRuleCount = computed(() => config.rules.filter(rule => rule.monitor).length)
const inactiveRuleCount = computed(() => config.rules.length - activeRuleCount.value)
const ruleName = computed(() => (ruleDraft.category || []).join('、') || '未命名规则')
const previewSource = computed(() => joinPath(ruleDraft.local, '示例/第 01 集.mkv') || '来源目录/示例/第 01 集.mkv')
const previewOutput = computed(() => joinPath(ruleDraft.strm, '示例/第 01 集.strm') || 'STRM 输出目录/示例/第 01 集.strm')
const previewTemplate = computed(() => String(ruleDraft.format || '尚未设置 STRM 模板').replaceAll('{local_file}', previewSource.value).replaceAll('{cloud_file}', joinPath(ruleDraft.cloud, '示例/第 01 集.mkv') || '{cloud_file}'))

function makeRule(data = {}) { return { _key: 'rule_' + Date.now() + '_' + ++ruleCounter, category: Array.isArray(data.category) ? [...data.category] : parseCategory(data.category), local: String(data.local || ''), strm: String(data.strm || ''), cloud: String(data.cloud || ''), format: String(data.format || ''), monitor: data.monitor !== undefined ? Boolean(data.monitor) : true } }
function parseCategory(value) { if (!value) return []; if (Array.isArray(value)) return value.map(item => String(item).trim()).filter(Boolean); return String(value).split(/[,，]+/).map(item => item.trim()).filter(Boolean) }
function joinPath(root, leaf) { const base = String(root || '').replace(/[\\/]+$/, ''); return base ? base + '/' + leaf : '' }
function serializeConfig(value) { const snapshot = structuredClone(value); snapshot.rules = (snapshot.rules || []).map(({ _key, ...rule }) => rule); return JSON.stringify(snapshot) }
function ruleMeta(rule) { const tags = (rule.category || []).join(' · '); return '标签：' + (tags || '未设置分类') + (rule.monitor ? ' · 监控变更' : ' · 不监控') }
function showNotice(text, color = 'success') { notice.text = text; notice.color = color; notice.visible = true }

function applyConfig(source) {
  const incoming = source || {}
  savedRuleSlotCount.value = ruleSlotCount(incoming)
  Object.assign(config, structuredClone(defaultConfig), { enabled: Boolean(incoming.enabled), monitor: Boolean(incoming.monitor), cover: Boolean(incoming.cover), notify: Boolean(incoming.notify), copy_files: Boolean(incoming.copy_files), copy_subtitles: Boolean(incoming.copy_subtitles), refresh_emby: Boolean(incoming.refresh_emby), uriencode: Boolean(incoming.uriencode), onlyonce: Boolean(incoming.onlyonce), interval: incoming.interval != null ? Number(incoming.interval) : 10, scan_interval: incoming.scan_interval != null ? Number(incoming.scan_interval) : 0, url: String(incoming.url || ''), rmt_mediaext: String(incoming.rmt_mediaext || defaultConfig.rmt_mediaext), other_mediaext: String(incoming.other_mediaext || defaultConfig.other_mediaext), emby_path: String(incoming.emby_path || ''), path_replacements: String(incoming.path_replacements || ''), mediaservers: Array.isArray(incoming.mediaservers) ? [...incoming.mediaservers] : [], reliable_engine: Boolean(incoming.reliable_engine), cleanup_mode: cleanupModes.some(mode => mode.value === incoming.cleanup_mode) ? incoming.cleanup_mode : 'off', cleanup_probe: String(incoming.cleanup_probe || ''), rules: parseRules(incoming) })
}
function ruleSlotCount(incoming) { let highestIndex = -1; Object.keys(incoming || {}).forEach(key => { const match = /^rule_(\d+)_/.exec(key); if (match) highestIndex = Math.max(highestIndex, Number(match[1])) }); return highestIndex + 1 }
function parseRules(incoming) {
  const rules = []; let highestIndex = -1
  Object.keys(incoming).forEach(key => { const match = /^rule_(\d+)_(?:local|strm)$/.exec(key); if (match) highestIndex = Math.max(highestIndex, Number(match[1])) })
  for (let index = 0; index <= highestIndex; index += 1) { const local = String(incoming['rule_' + index + '_local'] || '').trim(); const strm = String(incoming['rule_' + index + '_strm'] || '').trim(); const deleted = ['1', 'true', 'yes', 'on'].includes(String(incoming['rule_' + index + '_delete'] || '').trim().toLowerCase()); if (!deleted && (local || strm)) rules.push(makeRule({ category: incoming['rule_' + index + '_category'], local, strm, cloud: incoming['rule_' + index + '_cloud'], format: incoming['rule_' + index + '_format'], monitor: incoming['rule_' + index + '_monitor'] !== undefined ? incoming['rule_' + index + '_monitor'] : true })) }
  if (rules.length || !incoming.monitor_confs) return rules
  for (const rawLine of String(incoming.monitor_confs).split('\n')) { let line = rawLine.trim(); if (!line || line.startsWith('#')) continue; let monitor = true; if (line.includes('$')) { const split = line.split('$', 2); line = split[0]; monitor = !['0', 'nomonitor', 'false', 'off'].includes(String(split[1]).trim().toLowerCase()) } let category = ''; if (line.includes('@')) { const split = line.split('@', 2); line = split[0]; category = split[1] } const parts = line.split('#'); if (parts.length < 4) continue; rules.push(makeRule({ local: parts[0].trim(), strm: parts[1].trim(), cloud: parts[2].trim(), format: parts.slice(3).join('#').trim(), category, monitor })) }
  return rules
}

function openRuleEditor(index = null) { editingRuleIndex.value = index; Object.assign(ruleDraft, makeRule(index === null ? { format: '{cloud_file}' } : config.rules[index])); ruleStep.value = index === null ? 1 : 2; ruleError.value = ''; ruleDialog.value = true }
function closeRuleEditor() { ruleDialog.value = false; ruleError.value = ''; Object.keys(ruleDraft).forEach(key => delete ruleDraft[key]) }
function stepClass(step) { return step < ruleStep.value ? 'step--done' : step === ruleStep.value ? 'step--active' : '' }
function stepSymbol(step) { return step < ruleStep.value ? '✓' : String(step) }
function goToStep(step) { if (step <= ruleStep.value) { ruleStep.value = step; ruleError.value = '' } }
function validateRule(step) { if (step >= 2 && !String(ruleDraft.local || '').trim()) return '请填写来源目录。'; if (step >= 2 && !String(ruleDraft.strm || '').trim()) return '请填写 STRM 输出目录。'; if (step >= 3 && !String(ruleDraft.format || '').trim()) return '请填写 STRM 格式模板。'; if (step >= 3 && !['{local_file}', '{cloud_file}'].some(token => String(ruleDraft.format).includes(token))) return 'STRM 格式模板必须包含 {local_file} 或 {cloud_file}。'; if (step >= 3 && String(ruleDraft.format).includes('{cloud_file}') && !String(ruleDraft.cloud || '').trim()) return '使用 {cloud_file} 模板时，请填写 OpenList 云盘目录。'; return '' }
function advanceOrSave() { if (ruleStep.value < 3) { ruleError.value = validateRule(ruleStep.value); if (!ruleError.value) ruleStep.value += 1; return }; commitRule() }
function commitRule() { ruleError.value = validateRule(3); if (ruleError.value) return; const rule = makeRule(ruleDraft); if (editingRuleIndex.value === null) config.rules.push(rule); else config.rules.splice(editingRuleIndex.value, 1, rule); closeRuleEditor(); showNotice('路径规则已更新，记得保存更改') }
function requestRemoveRule(index) { removeRuleIndex.value = index; removeRuleDialog.value = true }
function removeRule() { if (removeRuleIndex.value !== null) config.rules.splice(removeRuleIndex.value, 1); removeRuleIndex.value = null; removeRuleDialog.value = false; showNotice('路径规则已移除，记得保存更改') }
function resetForm() { if (!savedSnapshot.value) return; const restored = JSON.parse(savedSnapshot.value); Object.assign(config, restored, { rules: (restored.rules || []).map(makeRule) }); error.value = null; showNotice('已放弃未保存的更改', 'info') }
function buildPayload() { const payload = { enabled: config.enabled, monitor: config.monitor, cover: config.cover, notify: config.notify, copy_files: config.copy_files, copy_subtitles: config.copy_subtitles, refresh_emby: config.refresh_emby, uriencode: config.uriencode, onlyonce: config.onlyonce, interval: Math.max(0, Number(config.interval) || 0), scan_interval: Math.max(0, Number(config.scan_interval) || 0), url: config.url, rmt_mediaext: config.rmt_mediaext, other_mediaext: config.other_mediaext, emby_path: config.emby_path, path_replacements: config.path_replacements, mediaservers: config.mediaservers, reliable_engine: config.reliable_engine, cleanup_mode: config.cleanup_mode, cleanup_probe: config.cleanup_probe, config_version: 2 }; config.rules.forEach((rule, index) => { payload['rule_' + index + '_category'] = (rule.category || []).join(','); payload['rule_' + index + '_local'] = rule.local; payload['rule_' + index + '_strm'] = rule.strm; payload['rule_' + index + '_cloud'] = rule.cloud; payload['rule_' + index + '_format'] = rule.format; payload['rule_' + index + '_monitor'] = rule.monitor; payload['rule_' + index + '_delete'] = false }); for (let index = config.rules.length; index < savedRuleSlotCount.value; index += 1) payload['rule_' + index + '_delete'] = true; return payload }
async function saveConfig() { saving.value = true; error.value = null; try { const invalidRule = config.rules.find(rule => validateRuleForSave(rule)); if (invalidRule) throw new Error(validateRuleForSave(invalidRule)); emit('save', buildPayload()); savedRuleSlotCount.value = config.rules.length; savedSnapshot.value = serializeConfig(config); showNotice('配置已提交，新的同步设置将按宿主保存流程应用。') } catch (err) { error.value = err.message || '保存配置失败' } finally { saving.value = false } }
function validateRuleForSave(rule) { if (!String(rule.local || '').trim() || !String(rule.strm || '').trim()) return '每条路径规则都需要来源目录和 STRM 输出目录。'; if (!String(rule.format || '').trim() || !['{local_file}', '{cloud_file}'].some(token => String(rule.format).includes(token))) return '每条路径规则的 STRM 模板都必须包含 {local_file} 或 {cloud_file}。'; if (String(rule.format).includes('{cloud_file}') && !String(rule.cloud || '').trim()) return '使用 {cloud_file} 模板的路径规则需要填写 OpenList 云盘目录。'; return '' }
onMounted(async () => { applyConfig(props.initialConfig); await nextTick(); savedSnapshot.value = serializeConfig(config); ready.value = true })
watch(() => props.initialConfig, value => { if (!ready.value || isDirty.value) return; applyConfig(value); savedSnapshot.value = serializeConfig(config) }, { deep: true })
</script>

<style scoped>
.rules-page, .rule-drawer, .remove-dialog-card { --v-theme-primary: 45, 96, 115; --v-theme-on-primary: 255, 255, 255; --v-theme-surface: 255, 255, 255; --v-theme-on-surface: 36, 49, 74; --v-theme-on-surface-variant: 102, 117, 140; color: #24314a; font-family: "Microsoft YaHei UI", "Microsoft YaHei", sans-serif; }
.rules-page { min-height: min(80vh, 900px); overflow: hidden; border: 1px solid #d9e2eb !important; border-radius: 8px !important; background: #fbfcfe !important; box-shadow: 0 12px 28px rgba(27, 45, 67, .08) !important; }.rules-page :deep(.v-card-item), .rules-page :deep(.v-card-text), .rules-page :deep(.v-card-actions) { background: #fbfcfe; }.rules-page :deep(.v-card-title) { color: #1e2d43 !important; font-size: 24px; font-weight: 700; letter-spacing: 0; }.rules-page :deep(.v-card-subtitle) { color: #66758c !important; font-size: 14px; opacity: 1 !important; }.rules-header { min-height: 122px; padding: 29px 28px !important; }.rules-body { padding: 0 28px 28px !important; }.rules-error { margin-bottom: 16px; }.rule-summary-bar { min-height: 78px; display: flex; align-items: center; justify-content: space-between; gap: 18px; padding: 16px 24px; border: 1px solid #dbe3eb; border-radius: 8px; background: #fff; }.rule-summary-bar div { display: grid; gap: 5px; }.rule-summary-bar strong { color: #26354b; font-size: 17px; }.rule-summary-bar span { color: #66758c; font-size: 12px; }.add-rule-button { min-width: 184px; min-height: 40px; background: #2d6073 !important; font-weight: 700; }
.rules-table-card { min-height: 430px; margin-top: 26px; overflow: hidden; border: 1px solid #dbe3eb; border-radius: 8px; background: #fff; }.rules-table-head, .rule-row { display: grid; grid-template-columns: 1.12fr 1.15fr 0.55fr 0.46fr; column-gap: 24px; align-items: center; }.rules-table-head { padding: 22px 24px 13px; color: #8d99aa; font-size: 12px; font-weight: 700; }.rule-row { min-height: 120px; margin: 0 12px; padding: 20px 12px; border-top: 1px solid #edf1f5; }.rule-row--selected { margin: 0 12px; border-top-color: transparent; border-radius: 6px; background: #f4f8fb; }.rule-source, .rule-output > div { min-width: 0; display: grid; gap: 8px; }.rule-source strong, .rule-output strong { color: #24314a; font-size: 14px; }.rule-source span, .rule-output span { color: #66758c; font-size: 12px; }.rule-output { min-width: 0; display: grid; grid-template-columns: 30px minmax(0, 1fr); align-items: center; gap: 10px; }.rule-output :deep(.v-icon) { color: #8a98a9; }.rule-status { display: inline-flex; align-items: center; gap: 7px; padding: 6px 12px; border-radius: 14px; font-size: 12px; font-weight: 700; }.rule-status i { width: 6px; height: 6px; border-radius: 50%; }.rule-status--active { background: #e6f5ed; color: #2d7052; }.rule-status--active i { background: #48a476; }.rule-status--inactive { background: #eff2f5; color: #6e7d90; }.rule-status--inactive i { display: none; }.rule-edit-button { width: 88px; min-height: 34px; color: #38546b !important; border-color: #b7c6d4 !important; font-weight: 700; }.rules-empty { min-height: 320px; display: flex; align-items: center; justify-content: center; gap: 10px; color: #66758c; font-size: 13px; }.rules-empty :deep(.v-icon) { color: #53758a; }.unsaved-bar { min-height: 48px; display: flex; align-items: center; gap: 12px; margin-top: 26px; padding: 0 20px; border: 1px solid #f0d2b3; border-radius: 7px; background: #fff7ed; color: #935237; }.unsaved-bar :deep(.v-icon) { color: #d87348; }.unsaved-bar strong { font-size: 14px; }.unsaved-bar span { color: #9c6b56; font-size: 12px; }.runtime-settings { margin-top: 26px; }.rules-page :deep(.v-expansion-panel), .rules-page :deep(.v-expansion-panel-title), .rules-page :deep(.v-expansion-panel-text__wrapper) { background: #fff !important; color: #26354b !important; }.settings-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 18px; padding: 8px 0; }.settings-grid--wide { grid-template-columns: repeat(2, minmax(0, 1fr)); }.rules-page :deep(.v-field) { background: #fff !important; color: #26354b !important; }.rules-page :deep(.v-field__outline) { --v-field-border-opacity: 1; color: #b9c7d5 !important; }.rules-page :deep(.v-label), .rules-page :deep(.v-messages) { color: #66758c !important; opacity: 1 !important; }.rules-actions { min-height: 72px; padding: 14px 28px !important; border-top: 1px solid #e0e6ed; }.save-state { display: inline-flex; align-items: center; gap: 8px; color: #66758c; font-size: 12px; }.save-state :deep(.v-icon) { color: #48a476; }.save-state :deep(.mdi-circle) { color: #d87348; }.rules-actions :deep(.v-btn) { min-width: 100px; border-color: #bdc9d5; color: #4c6076; font-weight: 700; }.save-button { min-width: 132px !important; margin-left: 4px; background: #2d6073 !important; color: #fff !important; }
.rule-drawer-dialog { display: flex; justify-content: flex-end; }.rule-drawer-dialog :deep(.v-overlay__content) { width: min(408px, 100vw); height: 100%; margin: 0 0 0 auto; }.rule-drawer { width: 100%; height: 100%; display: flex; flex-direction: column; background: #fff; box-shadow: -12px 0 26px rgba(24, 38, 64, .14); }.drawer-header { min-height: 130px; display: flex; align-items: flex-start; justify-content: space-between; padding: 26px 32px 19px; border-bottom: 1px solid #e2e8ef; }.drawer-header h1 { margin: 0; color: #24314a; font-size: 17px; font-weight: 700; }.drawer-header p { margin: 6px 0 0; color: #66758c; font-size: 12px; }.drawer-header :deep(.v-btn) { color: #52657b; background: #f3f6f8; }.drawer-stepper { position: relative; display: flex; justify-content: space-between; padding: 24px 32px 0; }.step-track { position: absolute; top: 38px; right: 67px; left: 67px; height: 2px; background: #d9e1e9; }.step { z-index: 1; display: grid; gap: 10px; place-items: center; border: 0; background: transparent; color: #748397; cursor: pointer; font-family: inherit; font-size: 12px; font-weight: 700; }.step i { width: 28px; height: 28px; display: grid; place-items: center; border: 1px solid #cbd6df; border-radius: 50%; background: #eff3f6; color: #6f7d90; font-size: 12px; font-style: normal; }.step--done { color: #456176; }.step--done i { border-color: #2d6073; background: #2d6073; color: #fff; }.step--active { color: #a95f36; }.step--active i { border-color: #e79851; background: #e79851; color: #fff; }.drawer-body { flex: 1; overflow-y: auto; padding: 32px; }.drawer-body h2 { margin: 0; color: #24314a; font-size: 17px; }.drawer-intro { margin: 8px 0 30px; color: #66758c; font-size: 14px; line-height: 1.55; }.path-field { display: grid; gap: 9px; }.path-field + .path-field { margin-top: 24px; }.path-field--spaced { margin-top: 30px !important; }.path-field label { color: #24314a; font-size: 13px; font-weight: 700; }.rule-drawer :deep(.v-field) { background: #fff !important; color: #26354b !important; }.rule-drawer :deep(.v-field__outline) { --v-field-border-opacity: 1; color: #b9c8d6 !important; }.rule-drawer :deep(.v-label), .rule-drawer :deep(.v-messages) { color: #66758c !important; opacity: 1 !important; }.mapping-arrow { height: 53px; display: grid; place-items: center; color: #8190a0; }.drawer-preview { display: grid; gap: 12px; margin-top: 31px; padding: 17px; border: 1px solid #d7e2eb; border-radius: 7px; background: #f4f8fb; }.drawer-preview strong { color: #24314a; font-size: 13px; }.drawer-preview div { display: grid; grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr); align-items: center; gap: 10px; color: #66758c; font-size: 12px; }.drawer-preview b { color: #365a70; font-weight: 700; }.drawer-preview--template code { display: block; overflow-wrap: anywhere; padding: 10px; border-radius: 4px; background: #fff; color: #304b60; font-family: Consolas, monospace; font-size: 12px; }.drawer-body code { padding: 1px 4px; border-radius: 3px; background: #eaf0f5; color: #304b60; font-family: Consolas, monospace; }.drawer-actions { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; min-height: 132px; padding: 24px 32px 22px; border-top: 1px solid #e2e8ef; }.drawer-actions :deep(.v-btn) { min-width: 92px; border-color: #bdc9d5; color: #4c6076; font-weight: 700; }.drawer-save-button { min-width: 170px !important; background: #2d6073 !important; color: #fff !important; }.drawer-actions p { width: 100%; margin: 4px 0 0; color: #66758c; font-size: 12px; }.remove-dialog-card { color: #24314a; }.remove-dialog-card :deep(.v-card-title), .remove-dialog-card :deep(.v-card-text) { color: #24314a !important; }
.path { overflow-wrap: anywhere; word-break: break-word; } @media (max-width: 960px) { .settings-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }.rules-table-head, .rule-row { grid-template-columns: 1fr 1fr .55fr; }.rules-table-head span:last-child, .rule-row > div:last-child { display: none; }.rule-row > div:nth-last-child(2) { justify-self: end; } } @media (max-width: 600px) { .rules-header, .rules-body, .rules-actions { padding-inline: 18px !important; }.rules-header { min-height: 100px; }.rule-summary-bar { align-items: stretch; flex-direction: column; }.add-rule-button { width: 100%; }.rules-table-card { min-height: auto; }.rules-table-head { display: none; }.rule-row { grid-template-columns: 1fr; gap: 14px; margin: 0; padding: 18px; }.rule-row--selected { margin: 0; border-radius: 0; }.rule-row > div:nth-last-child(2) { justify-self: start; }.rules-actions { gap: 10px; }.save-state { width: 100%; }.rules-actions :deep(.v-spacer) { display: none; }.rules-actions :deep(.v-btn) { flex: 1; }.settings-grid, .settings-grid--wide { grid-template-columns: 1fr; }.drawer-body, .drawer-header, .drawer-actions { padding-inline: 24px; } }
</style>
