<template>
  <div class="cloudstrm-shell v-theme--dark" style="color-scheme: dark">
    <header class="shell-header">
      <div class="header-row">
        <div class="brand-lockup">
          <div class="brand-mark" aria-hidden="true"><v-icon size="21">mdi-cloud-sync-outline</v-icon></div>
          <div>
            <div class="brand-title">云盘 STRM 小管家</div>
            <div class="brand-subtitle">STRM 同步与目录管理 · v{{ version }}</div>
          </div>
        </div>
        <div class="header-actions">
          <span class="runtime-indicator" :class="{ 'is-active': runtimeActive }"><span class="runtime-dot" aria-hidden="true"></span>{{ runtimeLabel }}</span>
          <v-btn icon="mdi-refresh" variant="text" size="small" :loading="loading" title="刷新状态" aria-label="刷新状态" @click="load" />
        </div>
      </div>
      <nav class="tab-bar" role="tablist" aria-label="插件视图">
        <button class="tab-button" :class="{ 'is-active': activeTab === 'dashboard' }" type="button" role="tab" :aria-selected="activeTab === 'dashboard'" @click="activeTab = 'dashboard'"><v-icon size="17">mdi-chart-box-outline</v-icon><span>运行状态</span></button>
        <button class="tab-button" :class="{ 'is-active': activeTab === 'config' }" type="button" role="tab" :aria-selected="activeTab === 'config'" @click="activeTab = 'config'"><v-icon size="17">mdi-tune-variant</v-icon><span>插件配置</span></button>
      </nav>
    </header>

    <main class="shell-main">
      <div class="shell-content">
        <v-alert v-if="error" type="error" variant="tonal" class="shell-alert" closable @click:close="error = ''">{{ error }}</v-alert>

        <section v-if="activeTab === 'dashboard'" class="dashboard-view" aria-labelledby="dashboard-title">
          <div class="page-intro">
            <div><span class="eyebrow">运行概览</span><h1 id="dashboard-title">运行状态</h1><p>快速查看媒体处理进度，以及需要处理的失败任务。</p></div>
            <div class="intro-actions">
              <v-btn v-if="!busy" color="primary" variant="flat" prepend-icon="mdi-play-circle-outline" :loading="fullScanPending" @click="fullScanDialog = true">全量生成</v-btn>
              <v-btn v-else color="error" variant="tonal" prepend-icon="mdi-stop-circle-outline" :loading="cancelPending" @click="cancelCurrentTask">取消当前任务</v-btn>
            </div>
          </div>

          <section class="runtime-banner" :class="{ 'is-active': runtimeActive }" aria-label="目录监控状态">
            <div class="banner-icon" aria-hidden="true"><v-icon>{{ runtimeActive ? 'mdi-sync' : (status.monitor_active ? 'mdi-eye-outline' : 'mdi-pause-circle-outline') }}</v-icon></div>
            <div class="banner-copy"><strong>{{ runtimeTitle }}</strong><span>{{ runtimeDescription }}</span></div>
            <span class="status-chip" :class="runtimeActive ? 'status-chip--active' : status.monitor_active ? 'status-chip--success' : 'status-chip--muted'">{{ runtimeActive ? '处理中' : status.monitor_active ? '监控中' : status.enabled ? '空闲' : '已停用' }}</span>
          </section>

          <section class="content-section" aria-labelledby="core-data-title">
            <div class="section-heading"><div><h2 id="core-data-title">核心数据</h2><p>总量和已完成数量来自目录核对，后台会在需要时刷新。</p></div><span class="section-note" :class="{ 'is-ready': processingOverview.record_ready }">{{ overviewStateLabel }}</span></div>
            <div class="metric-grid metric-grid--four">
              <article class="metric-tile metric-tile--media"><div class="metric-heading"><span>媒体总数</span><v-icon size="18">mdi-movie-open-outline</v-icon></div><strong>{{ processingOverview.media_total }}</strong><span class="metric-detail">已纳入目录核对</span></article>
              <article class="metric-tile metric-tile--strm"><div class="metric-heading"><span>已生成 STRM</span><v-icon size="18">mdi-file-link-outline</v-icon></div><strong>{{ processingOverview.strm_total }}</strong><span class="metric-detail">待生成 {{ pendingCount(processingOverview.media_total, processingOverview.strm_total) }}</span></article>
              <article class="metric-tile metric-tile--subtitle"><div class="metric-heading"><span>字幕文件</span><v-icon size="18">mdi-subtitles-outline</v-icon></div><strong>{{ processingOverview.subtitle_total }}</strong><span class="metric-detail">已完成 {{ processingOverview.subtitle_completed }} · 待处理 {{ pendingCount(processingOverview.subtitle_total, processingOverview.subtitle_completed) }}</span></article>
              <article class="metric-tile metric-tile--sidecar"><div class="metric-heading"><span>非媒体文件</span><v-icon size="18">mdi-file-document-outline</v-icon></div><strong>{{ processingOverview.non_media_total }}</strong><span class="metric-detail">已完成 {{ processingOverview.non_media_completed }} · 待处理 {{ pendingCount(processingOverview.non_media_total, processingOverview.non_media_completed) }}</span></article>
            </div>
          </section>

          <section class="content-section" aria-labelledby="task-summary-title">
            <div class="section-heading section-heading--compact"><div><h2 id="task-summary-title">任务摘要</h2><p>监控、定向和全量处理共享同一组任务状态。</p></div></div>
            <div class="summary-grid"><article v-for="item in taskSummaryItems" :key="item.key" class="summary-item" :class="'summary-item--' + item.tone"><span class="summary-label"><v-icon size="16">{{ item.icon }}</v-icon>{{ item.label }}</span><strong>{{ taskSummary[item.key] || 0 }}</strong></article></div>
          </section>

          <section v-if="busy || progressHasData" class="content-section task-progress-section" aria-labelledby="task-progress-title">
            <div class="section-heading section-heading--compact"><div><h2 id="task-progress-title">当前任务</h2><p>{{ activeProgress.label || (activeProgress.kind === 'manual_full' ? '全量生成' : '定向生成') }}</p></div><span class="status-chip" :class="progressTone">{{ progressPhaseLabel }}</span></div>
            <div class="task-progress-frame">
              <div class="progress-topline"><strong>{{ progressCompleted }} / {{ activeProgress.total || 0 }}</strong><span>{{ progressPercent }}%</span></div>
              <v-progress-linear :model-value="progressPercent" :indeterminate="busy && !activeProgress.total" color="primary" bg-color="secondary" height="7" rounded />
              <div class="progress-meta"><span><b>当前文件</b><code :title="activeProgress.current_path">{{ activeProgress.current_path || '正在准备文件列表' }}</code></span><span><b>已处理</b>{{ progressCompleted }} 个</span><span><b>失败</b>{{ activeProgress.failed || 0 }} 个</span></div>
              <div v-if="activeProgress.stalled" class="stalled-warning"><v-icon size="17">mdi-alert-outline</v-icon>超过 {{ formatDuration(activeProgress.stalled_seconds) }} 没有新的完成记录，可能正在等待 NAS 文件 I/O。</div>
            </div>
          </section>

          <section v-if="failures.length" class="content-section failure-section" aria-labelledby="failure-title">
            <div class="section-heading section-heading--compact"><div><h2 id="failure-title">需要处理的失败</h2><p>修复源文件、目标目录或权限后，可以单独重试。</p></div><v-btn size="small" variant="tonal" color="error" prepend-icon="mdi-replay" :loading="pending === 'failure-batch'" @click="retryAllFailures">重试全部</v-btn></div>
            <div class="failure-list"><article v-for="item in visibleFailures" :key="item.id" class="failure-row"><div class="failure-main"><div class="failure-title-line"><strong :title="item.path">{{ fileName(item.path) }}</strong><span class="status-chip status-chip--danger">失败</span></div><span class="failure-meta">{{ actionLabel(item.action) }} · 尝试 {{ item.attempts || 0 }} 次 · {{ item.reason_label || '未分类错误' }}</span><code class="failure-path" :title="item.path">{{ item.path }}</code></div><div class="failure-actions"><v-btn size="small" variant="text" @click="openFailure(item)">查看详情</v-btn><v-btn size="small" variant="tonal" color="error" :loading="pending === item.id" @click="retry(item.id)">重试</v-btn></div></article></div>
            <button v-if="failures.length > visibleFailures.length" class="text-button" type="button" @click="showAllFailures = true">查看全部 {{ failures.length }} 条失败</button>
          </section>

          <section v-if="status.cleanup_batches.length" class="content-section cleanup-section" aria-labelledby="cleanup-title">
            <div class="section-heading section-heading--compact"><div><h2 id="cleanup-title">待确认清理</h2><p>只有确认源文件确实删除后，才会清理对应的 STRM。</p></div></div>
            <div v-for="batch in status.cleanup_batches" :key="batch.batch_id" class="cleanup-row"><div><strong>{{ batch.path_count || 0 }} 个生成文件</strong><span>等待人工确认</span></div><v-btn size="small" color="warning" variant="tonal" prepend-icon="mdi-delete-check-outline" :loading="pending === batch.batch_id" @click="openCleanup(batch)">查看并确认</v-btn></div>
          </section>

          <section class="content-section recent-section" aria-labelledby="recent-title">
            <div class="section-heading section-heading--compact"><div><h2 id="recent-title">近期任务</h2><p>保留最近 20 次运行摘要，失败明细按需展开。</p></div><span class="section-note">{{ status.recent_runs.length }} / 20</span></div>
            <div class="recent-task-table table-frame"><v-table density="comfortable" class="status-table"><thead><tr><th>任务</th><th>状态</th><th>结果</th><th>开始时间</th><th class="text-right">操作</th></tr></thead><tbody>
              <tr v-for="run in recentRuns" :key="run.run_id"><td><strong>{{ runLabel(run) }}</strong><span class="table-subline">{{ run.message || runMonitorLabel(run) }}</span></td><td><span class="status-chip" :class="statusTone(run.status)">{{ displayStatus(run.status) }}</span></td><td><div class="result-list"><span v-for="item in resultItems(run)" :key="item.key" class="result-inline" :class="'result-inline--' + item.tone">{{ item.label }} {{ item.count }}</span><span v-if="!resultItems(run).length" class="muted-value">-</span></div></td><td class="table-time">{{ formatTime(run.started_at) }}</td><td class="text-right"><v-btn size="small" variant="text" @click="openRun(run)">查看</v-btn></td></tr>
              <tr v-if="!recentRuns.length"><td colspan="5" class="empty-row">暂无任务记录</td></tr>
            </tbody></v-table></div>
          </section>

          <details class="diagnostics-section"><summary><span><v-icon size="17">mdi-tune-variant</v-icon>高级诊断</span><small>只在排查问题时展开</small></summary><div class="diagnostics-grid"><div><span>等待中</span><strong>{{ status.engine.scheduled || status.queued || 0 }}</strong></div><div><span>处理中</span><strong>{{ status.engine.inflight || 0 }}</strong></div><div><span>工作线程</span><strong>{{ status.engine.workers || 0 }}</strong></div><div><span>未解决失败</span><strong>{{ taskSummary.failed || 0 }}</strong></div></div></details>
        </section>

        <section v-else class="config-view-host" aria-labelledby="config-title"><Config embedded :initial-config="initialConfig" :api="props.api" @save="handleConfigSave" @close="activeTab = 'dashboard'" /></section>
      </div>
    </main>

    <v-dialog v-model="fullScanDialog" max-width="480"><v-card class="modal-card full-scan-dialog"><v-card-title>全量生成</v-card-title><v-card-text><p class="modal-copy">扫描所有已启用目录规则。STRM 始终生成，已存在内容会自动跳过。</p><div class="scan-options"><v-checkbox :model-value="true" label="生成 STRM" color="primary" hide-details disabled /><v-checkbox v-model="fullScanOptions.copy_subtitles" label="本次复制字幕" color="primary" hide-details /><v-checkbox v-model="fullScanOptions.copy_files" label="本次复制非媒体文件" color="primary" hide-details /></div></v-card-text><v-card-actions><v-spacer /><v-btn variant="text" @click="fullScanDialog = false">取消</v-btn><v-btn color="primary" variant="flat" prepend-icon="mdi-play" :loading="fullScanPending" @click="submitFullScan">开始生成</v-btn></v-card-actions></v-card></v-dialog>

    <v-dialog v-model="failureDialog" max-width="660"><v-card v-if="selectedFailure" class="modal-card"><v-card-title class="modal-title-row"><span>失败详情</span><v-btn icon="mdi-close" variant="text" size="small" title="关闭" aria-label="关闭" @click="failureDialog = false" /></v-card-title><v-card-text class="detail-stack"><div class="detail-status"><span class="status-chip status-chip--danger">失败</span><strong>{{ actionLabel(selectedFailure.action) }}</strong><span>尝试 {{ selectedFailure.attempts || 0 }} 次</span></div><dl class="detail-list"><div><dt>源文件</dt><dd><code>{{ selectedFailure.path || '-' }}</code></dd></div><div><dt>目标文件</dt><dd><code>{{ selectedFailure.actual_target || '-' }}</code></dd></div><div><dt>错误原因</dt><dd>{{ selectedFailure.reason_label || selectedFailure.error || '未分类错误' }}</dd></div><div><dt>原始错误</dt><dd><code>{{ selectedFailure.error || '-' }}</code></dd></div><div><dt>修复建议</dt><dd>{{ selectedFailure.repair_hint || '检查源文件、目标挂载和规则配置后再试。' }}</dd></div></dl></v-card-text><v-card-actions><v-spacer /><v-btn variant="text" @click="failureDialog = false">关闭</v-btn><v-btn color="error" variant="tonal" prepend-icon="mdi-replay" :loading="pending === selectedFailure.id" @click="retry(selectedFailure.id)">重试</v-btn></v-card-actions></v-card></v-dialog>

    <v-dialog v-model="showAllFailures" max-width="760"><v-card class="modal-card"><v-card-title class="modal-title-row"><span>全部失败任务</span><v-btn icon="mdi-close" variant="text" size="small" title="关闭" aria-label="关闭" @click="showAllFailures = false" /></v-card-title><v-card-text class="all-failures-list"><button v-for="item in failures" :key="item.id" class="failure-picker" type="button" @click="openFailure(item)"><span><strong>{{ fileName(item.path) }}</strong><small>{{ actionLabel(item.action) }} · {{ item.reason_label || '未分类错误' }}</small></span><v-icon size="18">mdi-chevron-right</v-icon></button></v-card-text></v-card></v-dialog>

    <v-dialog v-model="cleanupDialog" max-width="480"><v-card v-if="selectedCleanup" class="modal-card"><v-card-title>确认清理</v-card-title><v-card-text><p class="modal-copy">将检查并删除 {{ selectedCleanup.path_count || 0 }} 个已确认缺失源文件对应的 STRM。</p><div class="warning-box"><v-icon size="18">mdi-alert-outline</v-icon><span>此操作不可撤销，请确认源文件确实已经删除。</span></div></v-card-text><v-card-actions><v-spacer /><v-btn variant="text" @click="cleanupDialog = false">取消</v-btn><v-btn color="warning" variant="flat" prepend-icon="mdi-delete-check-outline" :loading="pending === selectedCleanup.batch_id" @click="confirmCleanup">确认清理</v-btn></v-card-actions></v-card></v-dialog>

    <v-dialog v-model="runDialog" max-width="660"><v-card v-if="selectedRun" class="modal-card"><v-card-title class="modal-title-row"><span>{{ runLabel(selectedRun) }}</span><v-btn icon="mdi-close" variant="text" size="small" title="关闭" aria-label="关闭" @click="runDialog = false" /></v-card-title><v-card-text class="detail-stack"><div class="detail-status"><span class="status-chip" :class="statusTone(selectedRun.status)">{{ displayStatus(selectedRun.status) }}</span><span>{{ formatTime(selectedRun.started_at) }}</span></div><div class="run-result-grid"><div v-for="item in resultItems(selectedRun)" :key="item.key"><span>{{ item.label }}</span><strong>{{ item.count }}</strong></div></div><p class="run-message">{{ selectedRun.message || runMonitorLabel(selectedRun) || '无运行备注' }}</p></v-card-text><v-card-actions><v-spacer /><v-btn variant="text" @click="runDialog = false">关闭</v-btn></v-card-actions></v-card></v-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import Config from './Config.vue'
import { unwrapApiResponse } from './api_response.js'
import { readPluginConfig } from './config_persistence.js'

const props = defineProps({ api: { type: Object, default: () => ({}) }, initialConfig: { type: Object, default: () => ({}) }, config: { type: Object, default: () => ({}) }, version: { type: String, default: '2.1.21' }, defaultTab: { type: String, default: 'dashboard' } })
const emit = defineEmits(['save'])
const activeTab = ref(props.defaultTab === 'config' ? 'config' : 'dashboard')
const loading = ref(false); const error = ref(''); const pending = ref(null); const lastUpdated = ref(null); const failures = ref([]); const savedConfig = ref(null)
const fullScanPending = ref(false); const cancelPending = ref(false); const fullScanDialog = ref(false); const failureDialog = ref(false); const showAllFailures = ref(false); const cleanupDialog = ref(false); const runDialog = ref(false)
const selectedFailure = ref(null); const selectedCleanup = ref(null); const selectedRun = ref(null); const fullScanOptions = reactive({ copy_subtitles: false, copy_files: false })

const status = reactive({
  enabled: false, monitor_active: false, service_busy: false, service_running: false, service_state: 'disabled', scan_running: false, command_running: false, queued: 0, pending_jobs: 0,
  engine: { memory_queued: 0, inflight: 0, scheduled: 0, workers: 0 }, task_summary: { waiting: 0, in_progress: 0, processed: 0, skipped: 0, retrying: 0, failed: 0 },
  processing_overview: { media_total: 0, strm_total: 0, non_media_total: 0, non_media_completed: 0, subtitle_total: 0, subtitle_completed: 0, record_ready: false, ready: false, refreshing: false, last_checked_at: null },
  scan_progress: { running: false, run_id: '', kind: '', phase: 'idle', current_path: '', total: 0, processed: 0, failed: 0, stalled: false, stalled_seconds: 0, last_progress_at: null },
  command_progress: { running: false, run_id: '', label: '', phase: 'idle', current_path: '', total: 0, processed: 0, unchanged: 0, skipped: 0, failed: 0, stalled: false, stalled_seconds: 0, last_progress_at: null }, recent_runs: [], cleanup_batches: [],
})

const version = computed(() => props.version || '2.1.21')
const initialConfig = computed(() => savedConfig.value && Object.keys(savedConfig.value).length ? savedConfig.value : (Object.keys(props.initialConfig || {}).length ? props.initialConfig : props.config || {}))
const runtimeActive = computed(() => Boolean(status.service_busy || status.scan_running || status.command_running))
const busy = computed(() => Boolean(status.scan_running || status.command_running || status.scan_progress?.running || status.command_progress?.running))
const runtimeLabel = computed(() => runtimeActive.value ? '任务处理中' : status.monitor_active ? '目录监控正常' : status.enabled ? '服务空闲' : '服务已停用')
const runtimeTitle = computed(() => status.command_running ? '定向生成正在进行' : status.scan_running ? '全量生成正在进行' : status.monitor_active ? '目录监控已启用，当前空闲' : !status.enabled ? '插件未启用' : '同步服务已启用，当前空闲')
const runtimeDescription = computed(() => status.command_running ? '定向任务完成后会显示本次 STRM、复制和失败结果。' : status.scan_running ? '正在扫描已启用目录规则，STRM 固定生成。' : status.monitor_active ? '目录变化会自动进入处理队列。' : !status.enabled ? '启用插件后，目录监控和生成任务才会运行。' : '当前没有正在处理的文件。')
const taskSummary = computed(() => status.task_summary || { waiting: status.queued || 0, in_progress: 0, processed: 0, skipped: 0, retrying: 0, failed: failures.value.length })
const processingOverview = computed(() => status.processing_overview || {})
const activeProgress = computed(() => status.command_running || status.command_progress?.running ? { ...status.command_progress, kind: 'command' } : { ...status.scan_progress, label: '全量生成' })
const progressHasData = computed(() => Boolean(activeProgress.value.run_id || activeProgress.value.total || activeProgress.value.current_path || activeProgress.value.finished_at))
const progressCompleted = computed(() => status.command_running || status.command_progress?.running ? Number(activeProgress.value.processed || 0) + Number(activeProgress.value.unchanged || 0) + Number(activeProgress.value.skipped || 0) + Number(activeProgress.value.failed || 0) : Number(activeProgress.value.processed || 0))
const progressPercent = computed(() => { const total = Number(activeProgress.value.total || 0); return total > 0 ? Math.min(100, Math.round((progressCompleted.value / total) * 100)) : 0 })
const progressPhaseLabel = computed(() => ({ idle: '未开始', discovering: '准备中', scanning: '扫描中', processing: '处理中', completed: '已完成', completed_with_errors: '部分完成', cancelled: '已取消', failed: '失败' }[activeProgress.value.phase] || activeProgress.value.phase || '处理中'))
const progressTone = computed(() => activeProgress.value.phase === 'failed' || activeProgress.value.phase === 'completed_with_errors' ? 'status-chip--danger' : activeProgress.value.phase === 'cancelled' ? 'status-chip--warning' : activeProgress.value.running ? 'status-chip--active' : 'status-chip--success')
const overviewStateLabel = computed(() => processingOverview.value.refreshing ? '目录核对中' : processingOverview.value.record_ready ? '已核对 ' + formatTime(processingOverview.value.last_checked_at) : '等待核对')
const recentRuns = computed(() => (status.recent_runs || []).slice(0, 5)); const visibleFailures = computed(() => failures.value.slice(0, 3))
const taskSummaryItems = [{ key: 'waiting', label: '等待中', icon: 'mdi-clock-outline', tone: 'waiting' }, { key: 'in_progress', label: '进行中', icon: 'mdi-progress-clock', tone: 'active' }, { key: 'processed', label: '已处理', icon: 'mdi-check-circle-outline', tone: 'success' }, { key: 'skipped', label: '已跳过', icon: 'mdi-skip-next-circle-outline', tone: 'muted' }, { key: 'retrying', label: '重试中', icon: 'mdi-replay', tone: 'warning' }, { key: 'failed', label: '失败', icon: 'mdi-alert-circle-outline', tone: 'danger' }]
const resultCategories = [{ key: 'generated_strm', label: 'STRM', tone: 'success' }, { key: 'copied_subtitle', label: '字幕', tone: 'info' }, { key: 'copied_non_media', label: '非媒体', tone: 'neutral' }, { key: 'existing_skipped', label: '已有内容跳过', tone: 'muted' }, { key: 'failed', label: '失败', tone: 'danger' }]

function formatTime(value) { if (value === null || value === undefined || value === '') return '-'; const number = Number(value); const date = Number.isFinite(number) && number > 0 ? new Date(number < 100000000000 ? number * 1000 : number) : new Date(value); if (Number.isNaN(date.getTime())) return '-'; return date.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) }
function formatDuration(value) { const seconds = Math.max(0, Number(value) || 0); if (seconds < 60) return seconds + ' 秒'; return Math.floor(seconds / 60) + ' 分 ' + (seconds % 60) + ' 秒' }
function pendingCount(total, completed) { return Math.max(0, Number(total || 0) - Number(completed || 0)) }
function fileName(path) { const text = String(path || ''); return text.split(/[\\/]/).pop() || text || '未知文件' }
function actionLabel(action) { return { sync: '同步处理', delete: '删除生成文件', copy_subtitle: '复制字幕', copy_non_media: '复制非媒体文件' }[String(action || '')] || action || '文件处理' }
function runLabel(run = {}) { return run.kind === 'manual_full' ? '全量生成' : run.kind === 'command' ? '定向生成' : run.kind === 'monitor' ? '目录监控' : run.kind || '同步任务' }
function runMonitorLabel(run = {}) { return run.monitor_root ? '目录：' + run.monitor_root : '' }
function displayStatus(value) { return { running: '进行中', completed: '已完成', completed_empty: '无文件', completed_with_errors: '部分完成', cancelled: '已取消', failed: '失败' }[String(value || '').toLowerCase()] || value || '未知' }
function statusTone(value) { const normalized = String(value || '').toLowerCase(); if (normalized === 'completed' || normalized === 'completed_empty') return 'status-chip--success'; if (normalized === 'cancelled') return 'status-chip--warning'; if (normalized === 'failed' || normalized === 'completed_with_errors') return 'status-chip--danger'; return 'status-chip--active' }
function resultItems(run = {}) { const counts = run.result_counts || {}; const skipped = Number(counts.existing_skipped || 0) || Number(run.skipped || 0) + Number(run.unchanged || 0); return resultCategories.map(category => ({ ...category, count: category.key === 'existing_skipped' ? skipped : Number(counts[category.key] || 0) })).filter(item => item.count > 0) }
function applyStatus(data = {}) { Object.assign(status, data); status.engine = { memory_queued: 0, inflight: 0, scheduled: 0, workers: 0, ...(data.engine || {}) }; status.task_summary = { waiting: 0, in_progress: 0, processed: 0, skipped: 0, retrying: 0, failed: 0, ...(data.task_summary || {}) }; status.processing_overview = { ...status.processing_overview, ...(data.processing_overview || {}) }; status.scan_progress = { ...status.scan_progress, ...(data.scan_progress || {}) }; status.command_progress = { ...status.command_progress, ...(data.command_progress || {}) }; status.recent_runs = Array.isArray(data.recent_runs) ? data.recent_runs : []; status.cleanup_batches = Array.isArray(data.cleanup_batches) ? data.cleanup_batches : [] }

async function submitFullScan() { if (!props.api?.post || fullScanPending.value || busy.value) return; fullScanPending.value = true; error.value = ''; try { const response = await props.api.post('plugin/CloudStrmButler/sync_full_scan', { copy_files: fullScanOptions.copy_files, copy_subtitles: fullScanOptions.copy_subtitles }); const result = unwrapApiResponse(response); if (result?.code !== 0) throw new Error(result?.msg || '全量生成启动失败'); fullScanDialog.value = false; await load() } catch (err) { error.value = err.message || '全量生成启动失败' } finally { fullScanPending.value = false } }
async function cancelCurrentTask() { if (!props.api?.post || cancelPending.value) return; cancelPending.value = true; error.value = ''; try { const response = await props.api.post('plugin/CloudStrmButler/sync_cancel', {}); const result = unwrapApiResponse(response); if (result?.code !== 0) throw new Error(result?.msg || '取消任务失败'); await load() } catch (err) { error.value = err.message || '取消任务失败' } finally { cancelPending.value = false } }
async function load() { if (!props.api?.get || loading.value) return; loading.value = true; error.value = ''; try { const responses = await Promise.all([props.api.get('plugin/CloudStrmButler/sync_status'), props.api.get('plugin/CloudStrmButler/sync_failures')]); const statusResult = unwrapApiResponse(responses[0]); const failureResult = unwrapApiResponse(responses[1]); if (statusResult?.code !== 0) throw new Error(statusResult?.msg || '读取状态失败'); if (failureResult?.code !== 0) throw new Error(failureResult?.msg || '读取失败任务失败'); applyStatus(statusResult.data || {}); failures.value = Array.isArray(failureResult?.data?.items) ? failureResult.data.items : []; lastUpdated.value = Date.now() } catch (err) { error.value = err.message || '读取状态失败' } finally { loading.value = false } }
async function loadConfig() { if (!props.api?.get) return; try { savedConfig.value = { ...(await readPluginConfig(props.api)) } } catch (err) { error.value = err.message || '读取插件配置失败' } }
function openFailure(item) { selectedFailure.value = item; failureDialog.value = true; showAllFailures.value = false }
async function retry(failureId) { if (!props.api?.post) return; pending.value = failureId; error.value = ''; try { const result = unwrapApiResponse(await props.api.post('plugin/CloudStrmButler/sync_retry_failure', { failure_id: failureId })); if (result?.code !== 0) throw new Error(result?.msg || '重试失败'); failureDialog.value = false; await load() } catch (err) { error.value = err.message || '重试失败' } finally { pending.value = null } }
async function retryAllFailures() { if (!props.api?.post || !failures.value.length) return; pending.value = 'failure-batch'; try { const result = unwrapApiResponse(await props.api.post('plugin/CloudStrmButler/sync_retry_failures', { failure_ids: failures.value.map(item => item.id) })); if (result?.code !== 0) throw new Error(result?.msg || '批量重试失败'); await load() } catch (err) { error.value = err.message || '批量重试失败' } finally { pending.value = null } }
function openCleanup(batch) { selectedCleanup.value = batch; cleanupDialog.value = true }
async function confirmCleanup() { if (!selectedCleanup.value || !props.api?.post) return; pending.value = selectedCleanup.value.batch_id; try { const result = unwrapApiResponse(await props.api.post('plugin/CloudStrmButler/sync_confirm_cleanup', { batch_id: selectedCleanup.value.batch_id })); if (result?.code !== 0) throw new Error(result?.msg || '清理失败'); cleanupDialog.value = false; await load() } catch (err) { error.value = err.message || '清理失败' } finally { pending.value = null } }
function openRun(run) { selectedRun.value = run; runDialog.value = true }
function handleConfigSave(payload) { savedConfig.value = payload && typeof payload === 'object' ? { ...payload } : null; emit('save', payload); load() }

let refreshTimer = null
onMounted(async () => { await loadConfig(); await load(); refreshTimer = window.setInterval(load, 5000) })
onUnmounted(() => { if (refreshTimer !== null) window.clearInterval(refreshTimer) })
</script>

<style scoped>
.cloudstrm-shell { --cs-bg: #121218; --cs-surface: #19191f; --cs-raised: #202027; --cs-inset: #101016; --cs-line: #2d2d38; --cs-line-strong: #42414e; --cs-text: #f2f1f7; --cs-muted: #aaa7b5; --cs-dim: #777483; --cs-primary: #8c73f5; --cs-primary-soft: #c0b4ff; --cs-success: #68d7a2; --cs-warning: #f0c276; --cs-danger: #ff8a9a; --cs-info: #82c8ff; background: #0d0d12; color: var(--cs-text); font-family: "Segoe UI", "Microsoft YaHei", sans-serif; letter-spacing: 0; line-height: 1.45; min-height: 100vh; }
.shell-header { background: var(--cs-surface); border-bottom: 1px solid var(--cs-line); padding: 0 28px; }
.header-row { align-items: center; display: flex; justify-content: space-between; min-height: 74px; }
.brand-lockup { align-items: center; display: flex; gap: 12px; min-width: 0; }
.brand-mark { align-items: center; background: #2a214b; border: 1px solid #6252b3; border-radius: 8px; color: var(--cs-primary-soft); display: flex; flex: 0 0 38px; height: 38px; justify-content: center; width: 38px; }
.brand-title { color: var(--cs-text); font-size: 16px; font-weight: 600; }
.brand-subtitle { color: var(--cs-dim); font-size: 11px; margin-top: 2px; }
.header-actions { align-items: center; display: flex; gap: 12px; }
.runtime-indicator { align-items: center; color: var(--cs-muted); display: flex; font-size: 12px; gap: 7px; }
.runtime-indicator.is-active { color: var(--cs-success); }
.runtime-dot { background: var(--cs-dim); border-radius: 50%; height: 7px; width: 7px; }
.runtime-indicator.is-active .runtime-dot { background: var(--cs-success); }
.cloudstrm-shell :deep(.v-btn) { border-radius: 6px; letter-spacing: 0; text-transform: none; }
.cloudstrm-shell :deep(.v-btn--variant-flat) { background: var(--cs-primary); color: #17131f; }
.cloudstrm-shell :deep(.v-btn--variant-tonal) { background: #2a2443; color: var(--cs-primary-soft); }
.cloudstrm-shell :deep(.v-btn--variant-text) { color: var(--cs-muted); }
.tab-bar { display: flex; gap: 3px; height: 52px; }
.tab-button { align-items: center; background: transparent; border: 0; border-bottom: 2px solid transparent; color: var(--cs-dim); cursor: pointer; display: flex; font: inherit; gap: 8px; min-height: 52px; padding: 0 18px; }
.tab-button:hover { color: var(--cs-text); }
.tab-button.is-active { background: #211b34; border-bottom-color: var(--cs-primary); color: var(--cs-primary-soft); }
.shell-main { background: var(--cs-bg); min-height: calc(100vh - 127px); }
.shell-content { margin: 0 auto; max-width: 1380px; padding: 34px 40px 54px; }
.shell-alert { margin-bottom: 20px; }
.page-intro { align-items: flex-end; display: flex; justify-content: space-between; margin-bottom: 22px; }
.eyebrow { color: var(--cs-primary-soft); display: block; font-size: 10px; font-weight: 700; letter-spacing: 1px; margin-bottom: 6px; }
h1, h2, p { margin: 0; }
h1 { font-size: 25px; font-weight: 600; line-height: 1.2; }
h2 { font-size: 16px; font-weight: 600; }
.page-intro p, .section-heading p { color: var(--cs-muted); font-size: 12px; margin-top: 7px; }
.intro-actions { display: flex; gap: 8px; }
.runtime-banner { align-items: center; background: var(--cs-surface); border: 1px solid var(--cs-line); border-radius: 7px; display: flex; gap: 13px; margin-bottom: 30px; min-height: 68px; padding: 13px 16px; }
.runtime-banner.is-active { border-color: #4a3e7f; }
.banner-icon { align-items: center; background: #2c2934; border-radius: 7px; color: var(--cs-muted); display: flex; flex: 0 0 38px; height: 38px; justify-content: center; }
.runtime-banner.is-active .banner-icon { background: #2c254b; color: var(--cs-primary-soft); }
.banner-copy { display: flex; flex: 1; flex-direction: column; min-width: 0; }
.banner-copy strong { font-size: 14px; font-weight: 600; }
.banner-copy span { color: var(--cs-muted); font-size: 12px; margin-top: 3px; }
.status-chip { align-items: center; border: 1px solid var(--cs-line); border-radius: 5px; display: inline-flex; font-size: 11px; line-height: 1; padding: 5px 8px; white-space: nowrap; }
.status-chip--active { background: #2c254b; border-color: #554996; color: var(--cs-primary-soft); }
.status-chip--success { background: #203b31; border-color: #356a54; color: var(--cs-success); }
.status-chip--warning { background: #44351e; border-color: #705a2b; color: var(--cs-warning); }
.status-chip--danger { background: #482630; border-color: #703c4b; color: var(--cs-danger); }
.status-chip--muted { background: #292832; border-color: var(--cs-line-strong); color: var(--cs-dim); }
.content-section { border-top: 1px solid var(--cs-line); margin-bottom: 30px; padding-top: 23px; }
.section-heading { align-items: flex-end; display: flex; justify-content: space-between; margin-bottom: 15px; }
.section-heading--compact { margin-bottom: 12px; }
.section-note { color: var(--cs-dim); font-size: 11px; }
.section-note.is-ready { color: var(--cs-primary-soft); }
.metric-grid { display: grid; gap: 12px; }
.metric-grid--four { grid-template-columns: repeat(4, minmax(0, 1fr)); }
.metric-tile { background: var(--cs-surface); border: 1px solid var(--cs-line); border-radius: 7px; min-height: 116px; padding: 17px 18px 14px; }
.metric-tile--strm { border-color: #514593; }
.metric-heading { align-items: center; color: var(--cs-muted); display: flex; font-size: 12px; justify-content: space-between; }
.metric-heading .v-icon { color: var(--cs-dim); }
.metric-tile--strm .metric-heading .v-icon { color: var(--cs-primary-soft); }
.metric-tile--subtitle .metric-heading .v-icon { color: var(--cs-warning); }
.metric-tile--sidecar .metric-heading .v-icon { color: var(--cs-info); }
.metric-tile strong { display: block; font-size: 29px; font-weight: 500; line-height: 1; margin-top: 20px; }
.metric-detail { color: var(--cs-dim); display: block; font-size: 11px; margin-top: 9px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.metric-tile--strm strong { color: var(--cs-primary-soft); }
.metric-tile--subtitle strong { color: var(--cs-warning); }
.metric-tile--sidecar strong { color: var(--cs-info); }
.summary-grid { display: grid; gap: 10px; grid-template-columns: repeat(6, minmax(0, 1fr)); }
.summary-item { background: var(--cs-surface); border: 1px solid var(--cs-line); border-radius: 6px; min-height: 76px; padding: 13px 14px; }
.summary-label { align-items: center; color: var(--cs-muted); display: flex; font-size: 11px; gap: 6px; }
.summary-item strong { display: block; font-size: 22px; font-weight: 500; margin-top: 9px; }
.summary-item--active strong { color: var(--cs-primary-soft); }
.summary-item--success strong { color: var(--cs-success); }
.summary-item--warning strong { color: var(--cs-warning); }
.summary-item--danger strong { color: var(--cs-danger); }
.task-progress-frame { background: var(--cs-surface); border: 1px solid var(--cs-line); border-radius: 7px; padding: 18px 20px 17px; }
.progress-topline { align-items: baseline; display: flex; justify-content: space-between; margin-bottom: 12px; }
.progress-topline strong { font-size: 20px; font-weight: 500; }
.progress-topline span { color: var(--cs-primary-soft); font-size: 13px; }
.cloudstrm-shell :deep(.v-progress-linear) { --v-theme-primary: 140, 115, 245; --v-theme-secondary: 45, 45, 56; --v-theme-success: 104, 215, 162; --v-theme-warning: 240, 194, 118; }
.progress-meta { display: grid; gap: 12px; grid-template-columns: minmax(0, 2fr) 1fr 1fr; margin-top: 15px; }
.progress-meta span { color: var(--cs-muted); font-size: 11px; min-width: 0; }
.progress-meta b { color: var(--cs-dim); display: block; font-size: 10px; font-weight: 400; margin-bottom: 4px; }
.progress-meta code, .failure-path, .detail-list code { color: var(--cs-primary-soft); display: block; font-family: Consolas, monospace; font-size: 11px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.stalled-warning { align-items: center; background: #3b3223; border: 1px solid #66583a; border-radius: 5px; color: var(--cs-warning); display: flex; font-size: 11px; gap: 7px; margin-top: 15px; padding: 9px 11px; }
.failure-section { border-top-color: #4b3039; }
.failure-list { background: var(--cs-surface); border: 1px solid var(--cs-line); border-radius: 7px; overflow: hidden; }
.failure-row { align-items: center; border-bottom: 1px solid var(--cs-line); display: flex; gap: 16px; justify-content: space-between; padding: 14px 16px; }
.failure-row:last-child { border-bottom: 0; }
.failure-main { min-width: 0; }
.failure-title-line { align-items: center; display: flex; gap: 9px; }
.failure-title-line strong { font-size: 13px; max-width: min(460px, 60vw); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.failure-meta { color: var(--cs-muted); display: block; font-size: 11px; margin-top: 5px; }
.failure-path { color: var(--cs-dim); margin-top: 5px; }
.failure-actions { align-items: center; display: flex; flex: 0 0 auto; gap: 4px; }
.text-button { background: transparent; border: 0; color: var(--cs-primary-soft); cursor: pointer; font: inherit; font-size: 12px; margin-top: 10px; padding: 4px 0; }
.cleanup-section { border-top-color: #55442b; }
.cleanup-row { align-items: center; background: var(--cs-surface); border: 1px solid var(--cs-line); border-radius: 7px; display: flex; justify-content: space-between; padding: 13px 16px; }
.cleanup-row div { display: flex; flex-direction: column; }
.cleanup-row strong { font-size: 13px; }
.cleanup-row span { color: var(--cs-muted); font-size: 11px; margin-top: 3px; }
.table-frame { background: var(--cs-surface); border: 1px solid var(--cs-line); border-radius: 7px; overflow-x: auto; }
.status-table { color: var(--cs-text); min-width: 720px; }
.status-table :deep(th) { background: var(--cs-raised); border-bottom-color: var(--cs-line) !important; color: var(--cs-dim) !important; font-size: 11px; font-weight: 500; }
.status-table :deep(td) { border-bottom-color: var(--cs-line) !important; color: var(--cs-muted); font-size: 12px; }
.status-table :deep(tbody tr:hover) { background: #1e1e27; }
.table-subline { color: var(--cs-dim); display: block; font-size: 10px; margin-top: 3px; max-width: 280px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.table-time { white-space: nowrap; }
.result-list { display: flex; flex-wrap: wrap; gap: 4px; max-width: 330px; }
.result-inline { border-radius: 4px; font-size: 10px; padding: 3px 5px; white-space: nowrap; }
.result-inline--success { background: #203b31; color: var(--cs-success); }
.result-inline--info { background: #203747; color: var(--cs-info); }
.result-inline--neutral { background: #2a3035; color: var(--cs-muted); }
.result-inline--muted { background: #292832; color: var(--cs-dim); }
.result-inline--danger { background: #482630; color: var(--cs-danger); }
.muted-value, .empty-row { color: var(--cs-dim) !important; }
.diagnostics-section { background: var(--cs-surface); border: 1px solid var(--cs-line); border-radius: 7px; margin-top: 8px; }
.diagnostics-section summary { align-items: center; color: var(--cs-muted); cursor: pointer; display: flex; justify-content: space-between; list-style: none; padding: 14px 16px; }
.diagnostics-section summary::-webkit-details-marker { display: none; }
.diagnostics-section summary > span { align-items: center; display: flex; gap: 8px; }
.diagnostics-section summary small { color: var(--cs-dim); font-size: 11px; }
.diagnostics-grid { border-top: 1px solid var(--cs-line); display: grid; gap: 1px; grid-template-columns: repeat(4, 1fr); padding: 1px; }
.diagnostics-grid div { background: var(--cs-inset); padding: 13px 15px; }
.diagnostics-grid span { color: var(--cs-dim); display: block; font-size: 10px; }
.diagnostics-grid strong { display: block; font-size: 18px; font-weight: 500; margin-top: 5px; }
.modal-card { background: var(--cs-surface); color: var(--cs-text); }
.modal-card .v-card-title { font-size: 17px; font-weight: 600; padding: 21px 22px 12px; }
.modal-card .v-card-text { color: var(--cs-muted); padding: 0 22px 12px; }
.modal-card .v-card-actions { padding: 10px 22px 18px; }
.modal-copy { font-size: 12px; line-height: 1.6; }
.scan-options { border-top: 1px solid var(--cs-line); margin-top: 16px; padding-top: 9px; }
.modal-title-row { align-items: center; display: flex; justify-content: space-between; }
.detail-stack { display: grid; gap: 15px; }
.detail-status { align-items: center; display: flex; flex-wrap: wrap; gap: 9px; }
.detail-list { border-top: 1px solid var(--cs-line); margin: 0; }
.detail-list > div { border-bottom: 1px solid var(--cs-line); display: grid; gap: 14px; grid-template-columns: 76px minmax(0, 1fr); padding: 11px 0; }
.detail-list dt { color: var(--cs-dim); font-size: 11px; }
.detail-list dd { font-size: 12px; margin: 0; min-width: 0; }
.detail-list dd code { color: var(--cs-muted); white-space: normal; word-break: break-all; }
.all-failures-list { padding-top: 7px !important; }
.failure-picker { align-items: center; background: transparent; border: 0; border-bottom: 1px solid var(--cs-line); color: var(--cs-text); cursor: pointer; display: flex; justify-content: space-between; padding: 13px 0; text-align: left; width: 100%; }
.failure-picker:last-child { border-bottom: 0; }
.failure-picker strong, .failure-picker small { display: block; }
.failure-picker strong { font-size: 12px; }
.failure-picker small { color: var(--cs-muted); font-size: 11px; margin-top: 4px; }
.warning-box { align-items: flex-start; background: #44351e; border: 1px solid #705a2b; border-radius: 5px; color: var(--cs-warning); display: flex; font-size: 11px; gap: 8px; line-height: 1.5; margin-top: 16px; padding: 10px 12px; }
.run-result-grid { display: grid; gap: 8px; grid-template-columns: repeat(5, 1fr); }
.run-result-grid div { background: var(--cs-inset); border: 1px solid var(--cs-line); border-radius: 5px; padding: 10px; }
.run-result-grid span { color: var(--cs-dim); display: block; font-size: 10px; }
.run-result-grid strong { display: block; font-size: 18px; margin-top: 5px; }
.run-message { background: var(--cs-inset); border-radius: 5px; font-size: 11px; line-height: 1.6; padding: 10px 12px; }
@media (max-width: 900px) { .shell-content { padding: 28px 24px 42px; } .metric-grid--four { grid-template-columns: repeat(2, minmax(0, 1fr)); } .summary-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); } }
@media (max-width: 640px) { .shell-header { padding: 0 16px; } .header-row { min-height: 64px; } .brand-subtitle, .runtime-indicator { display: none; } .brand-title { font-size: 15px; } .tab-bar, .tab-button { height: 48px; min-height: 48px; } .tab-button { flex: 1; justify-content: center; padding: 0 10px; } .shell-content { padding: 24px 16px 36px; } .page-intro { align-items: flex-start; flex-direction: column; gap: 15px; } .intro-actions, .intro-actions .v-btn { width: 100%; } .runtime-banner { align-items: flex-start; padding: 14px; } .runtime-banner .status-chip { margin-left: auto; } .banner-copy span { white-space: normal; } .metric-grid--four { gap: 9px; } .metric-tile { min-height: 112px; padding: 14px; } .metric-tile strong { font-size: 25px; } .summary-grid { gap: 8px; grid-template-columns: repeat(2, minmax(0, 1fr)); } .progress-meta { grid-template-columns: 1fr 1fr; } .progress-meta span:first-child { grid-column: 1 / -1; } .failure-row { align-items: flex-start; flex-direction: column; gap: 10px; } .failure-actions { align-self: flex-end; } .cleanup-row { align-items: flex-start; flex-direction: column; gap: 12px; } .run-result-grid { grid-template-columns: repeat(2, 1fr); } .run-result-grid div:last-child { grid-column: 1 / -1; } .diagnostics-grid { grid-template-columns: repeat(2, 1fr); } }
</style>
