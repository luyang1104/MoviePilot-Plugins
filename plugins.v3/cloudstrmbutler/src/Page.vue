<template>
  <div class="cloudstrm-shell v-theme--dark" style="color-scheme: dark">
    <header class="shell-header">
      <div class="brand-lockup">
        <div class="brand-mark" aria-hidden="true">
          <v-icon size="21">mdi-cloud-sync-outline</v-icon>
        </div>
        <div class="brand-copy">
          <div class="brand-title">
            云盘 Strm 小管家
            <span class="brand-version">v{{ version }}</span>
          </div>
          <div class="brand-subtitle">STRM 同步与目录管理</div>
        </div>
      </div>

      <div class="header-actions">
        <div class="runtime-indicator" :class="{ 'is-active': runtimeActive }">
          <span class="runtime-dot" aria-hidden="true"></span>
          <span>{{ runtimeLabel }}</span>
        </div>
        <v-btn
          icon="mdi-refresh"
          variant="text"
          size="small"
          :loading="loading"
          title="刷新状态"
          aria-label="刷新状态"
          @click="load"
        />
      </div>

      <nav class="tab-bar" aria-label="插件视图">
        <button
          class="tab-button"
          :class="{ 'is-active': activeTab === 'dashboard' }"
          type="button"
          role="tab"
          :aria-selected="activeTab === 'dashboard'"
          @click="activeTab = 'dashboard'"
        >
          <v-icon size="18">mdi-chart-box-outline</v-icon>
          <span>运行状态</span>
        </button>
        <button
          class="tab-button"
          :class="{ 'is-active': activeTab === 'config' }"
          type="button"
          role="tab"
          :aria-selected="activeTab === 'config'"
          @click="activeTab = 'config'"
        >
          <v-icon size="18">mdi-tune-variant</v-icon>
          <span>插件配置</span>
        </button>
      </nav>
    </header>

    <div class="shell-divider" aria-hidden="true"></div>

    <main class="shell-content">
      <v-alert v-if="error" type="error" variant="tonal" class="shell-alert" closable @click:close="error = ''">
        {{ error }}
      </v-alert>

      <section v-show="activeTab === 'dashboard'" class="dashboard-view" aria-labelledby="dashboard-title">
        <div class="page-intro">
          <div>
            <span class="eyebrow">OPERATIONS</span>
            <h1 id="dashboard-title">运行状态</h1>
            <p>查看同步队列、处理进度与需要人工确认的任务。</p>
          </div>
          <div class="intro-meta">
            <span class="meta-label">最后刷新</span>
            <strong>{{ lastUpdatedLabel }}</strong>
          </div>
        </div>

        <section class="runtime-banner" :class="{ 'is-active': runtimeActive }" aria-label="同步引擎状态">
          <div class="banner-icon" aria-hidden="true">
            <v-icon>{{ runtimeActive ? 'mdi-pulse' : 'mdi-pause-circle-outline' }}</v-icon>
          </div>
          <div class="banner-copy">
            <strong>{{ runtimeTitle }}</strong>
            <span>{{ runtimeDescription }}</span>
          </div>
          <v-chip size="small" :color="runtimeActive ? 'success' : 'secondary'" variant="tonal">
            {{ runtimeActive ? '处理中' : (status.service_state === 'pending_recovery' ? '待恢复' : '待机') }}
          </v-chip>
        </section>

        <section class="content-section engine-metrics-section" aria-labelledby="engine-metrics-title">
          <div class="section-heading section-heading--compact">
            <div>
              <h2 id="engine-metrics-title">可靠同步引擎指标</h2>
              <p>以下四项只统计可靠同步引擎；手动 /strm 扫描会在下方单独显示。</p>
            </div>
            <span class="scope-note">手动 /strm：独立统计</span>
          </div>

          <div class="metric-grid" aria-label="可靠同步引擎指标">
          <article class="metric-tile">
            <div class="metric-heading">
              <span>持久化队列</span>
              <v-icon size="18">mdi-database-outline</v-icon>
            </div>
            <strong>{{ status.queued }}</strong>
            <span class="metric-caption">{{ status.queue_active ? '等待可靠引擎处理的任务' : (status.pending_jobs ? '引擎未运行，任务会保留待恢复' : '可靠任务队列当前为空') }}</span>
          </article>
          <article class="metric-tile">
            <div class="metric-heading">
              <span>内存队列</span>
              <v-icon size="18">mdi-memory</v-icon>
            </div>
            <strong>{{ status.engine.memory_queued }}</strong>
            <span class="metric-caption">已载入可靠引擎、等待执行的内容</span>
          </article>
          <article class="metric-tile metric-tile--accent">
            <div class="metric-heading">
              <span>处理中（可靠引擎）</span>
              <v-icon size="18">mdi-sync</v-icon>
            </div>
            <strong>{{ status.engine.inflight }}</strong>
            <span class="metric-caption">可靠引擎当前正在处理的内容</span>
          </article>
          <article class="metric-tile">
            <div class="metric-heading">
              <span>工作线程（可靠引擎）</span>
              <v-icon size="18">mdi-lan-connect</v-icon>
            </div>
            <strong>{{ status.engine.workers }}</strong>
            <span class="metric-caption">可靠引擎已启动的并发线程</span>
          </article>
          </div>
        </section>

        <section v-if="commandProgressHasData" class="content-section command-progress-section" aria-labelledby="command-progress-title">
          <div class="section-heading section-heading--compact">
            <div>
              <h2 id="command-progress-title">手动 /strm 扫描</h2>
              <p>{{ commandProgress.running ? '手动扫描正在独立执行，进度不会计入可靠同步引擎的四项指标。' : '最近一次手动扫描的处理结果。' }}</p>
            </div>
            <span class="status-chip" :class="commandProgress.running ? 'status-chip--active' : 'status-chip--success'">{{ commandProgressPhaseLabel }}</span>
          </div>

          <div class="command-progress-frame">
            <div class="command-progress-top">
              <div class="command-progress-copy">
                <span class="metric-caption">{{ commandProgress.label || '手动 /strm' }}</span>
                <strong>{{ commandProgressCompleted }} / {{ commandProgress.total }}</strong>
                <span>{{ commandProgress.running ? '已完成文件 / 已发现文件' : '本次扫描已处理文件 / 总文件数' }}</span>
              </div>
              <v-icon size="25" :color="commandProgress.stalled ? 'warning' : commandProgress.running ? 'success' : 'secondary'">{{ commandProgress.stalled ? 'mdi-timer-alert-outline' : commandProgress.running ? 'mdi-progress-clock' : 'mdi-check-circle-outline' }}</v-icon>
            </div>
            <v-progress-linear
              :model-value="commandProgressPercent"
              :indeterminate="commandProgress.running && commandProgress.total === 0"
              color="primary"
              bg-color="secondary"
              height="7"
              rounded
            />

            <div class="command-detail-grid">
              <div class="command-detail">
                <span>阶段</span>
                <strong>{{ commandProgressPhaseLabel }}</strong>
              </div>
              <div class="command-detail command-detail--path">
                <span>当前文件</span>
                <strong :title="commandProgress.current_path">{{ commandProgress.current_path || '暂无' }}</strong>
              </div>
              <div class="command-detail">
                <span>最后进度</span>
                <strong>{{ formatTime(commandProgress.last_progress_at) }}</strong>
              </div>
            </div>

            <div v-if="commandProgress.stalled" class="stalled-warning">
              <v-icon size="18">mdi-alert-outline</v-icon>
              <span>超过 {{ formatDuration(commandProgress.stalled_seconds) }} 没有新的完成记录，可能正在等待 NAS 文件 I/O；当前文件仍是上面显示的路径。</span>
            </div>

            <div class="result-summary-heading">
              <strong>处理结果</strong>
              <span v-if="commandProgress.errors.length" class="danger-number">失败示例 {{ commandProgress.errors.length }} 条</span>
            </div>
            <div class="result-category-grid">
              <article v-for="category in resultCategories" :key="category.key" class="result-category" :class="`result-category--${category.tone}`">
                <span>{{ category.label }}</span>
                <strong>{{ commandProgress.result_counts[category.key] || 0 }}</strong>
              </article>
            </div>

            <ul v-if="commandProgress.errors.length" class="command-errors">
              <li v-for="item in commandProgress.errors" :key="item">{{ item }}</li>
            </ul>
          </div>
        </section>

        <section class="content-section" aria-labelledby="recent-runs-title">
          <div class="section-heading">
            <div>
              <h2 id="recent-runs-title">最近任务</h2>
              <p>最近一次全量扫描与实时同步的处理摘要。</p>
            </div>
            <v-btn
              icon="mdi-refresh"
              variant="tonal"
              size="small"
              :loading="loading"
              title="刷新最近任务"
              aria-label="刷新最近任务"
              @click="load"
            />
          </div>

          <div class="table-frame">
            <v-table density="comfortable" class="status-table">
              <thead>
                <tr>
                  <th>开始时间</th>
                  <th>状态</th>
                  <th>排队</th>
                  <th>已处理</th>
                  <th>未变化</th>
                  <th>跳过</th>
                  <th>失败</th>
                  <th>处理结果</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="run in status.recent_runs" :key="run.run_id">
                  <td class="time-cell">{{ formatTime(run.started_at) }}</td>
                  <td><span class="status-chip" :class="statusTone(run.status)">{{ displayStatus(run.status) }}</span></td>
                  <td>{{ run.queued ?? 0 }}</td>
                  <td>{{ run.processed ?? 0 }}</td>
                  <td>{{ run.unchanged ?? 0 }}</td>
                  <td>{{ run.skipped ?? 0 }}</td>
                  <td :class="{ 'danger-number': Number(run.failed) > 0 }">{{ run.failed ?? 0 }}</td>
                  <td class="result-cell">
                    <template v-if="resultItems(run).length">
                      <span v-for="item in resultItems(run)" :key="item.key" class="result-inline" :class="`result-inline--${item.tone}`">{{ item.label }} {{ item.count }}</span>
                    </template>
                    <span v-else class="muted-value">-</span>
                  </td>
                </tr>
                <tr v-if="!status.recent_runs.length">
                  <td colspan="8" class="empty-row">暂无任务记录</td>
                </tr>
              </tbody>
            </v-table>
          </div>
        </section>

        <div class="dashboard-columns">
          <section class="content-section" aria-labelledby="failures-title">
            <div class="section-heading section-heading--compact">
              <div>
                <h2 id="failures-title">同步失败记录</h2>
                <p>需要重新加入队列的任务。</p>
              </div>
              <span class="section-count" :class="{ 'has-items': failures.length }">{{ failures.length }}</span>
            </div>

            <div v-if="failures.length" class="table-frame">
              <v-table density="comfortable" class="status-table">
                <thead>
                  <tr><th>路径</th><th>次数</th><th>更新时间</th><th></th></tr>
                </thead>
                <tbody>
                  <tr v-for="item in failures" :key="item.id">
                    <td class="path-cell" :title="item.path">{{ item.path }}</td>
                    <td>{{ item.attempts }}</td>
                    <td class="time-cell">{{ formatTime(item.updated_at) }}</td>
                    <td class="action-cell">
                      <v-btn
                        icon="mdi-replay"
                        size="small"
                        variant="text"
                        color="primary"
                        title="重试此任务"
                        aria-label="重试此任务"
                        :loading="pending === item.id"
                        @click="retry(item.id)"
                      />
                    </td>
                  </tr>
                </tbody>
              </v-table>
            </div>
            <div v-else class="empty-state">
              <div class="empty-icon empty-icon--success" aria-hidden="true"><v-icon size="19">mdi-check</v-icon></div>
              <strong>系统运行良好</strong>
              <span>暂无未解决的同步失败任务。</span>
            </div>
          </section>

          <section class="content-section" aria-labelledby="cleanup-title">
            <div class="section-heading section-heading--compact">
              <div>
                <h2 id="cleanup-title">待确认清理</h2>
                <p>扫描发现的缺失 STRM 文件。</p>
              </div>
              <span class="section-count" :class="{ 'has-items': status.cleanup_batches.length }">{{ status.cleanup_batches.length }}</span>
            </div>

            <div v-if="status.cleanup_batches.length" class="table-frame">
              <v-table density="comfortable" class="status-table">
                <thead>
                  <tr><th>监控目录</th><th>文件数</th><th>创建时间</th><th></th></tr>
                </thead>
                <tbody>
                  <tr v-for="batch in status.cleanup_batches" :key="batch.batch_id">
                    <td class="path-cell" :title="batch.monitor_root">{{ batch.monitor_root }}</td>
                    <td>{{ batch.path_count }}</td>
                    <td class="time-cell">{{ formatTime(batch.created_at) }}</td>
                    <td class="action-cell">
                      <v-btn
                        icon="mdi-check-circle-outline"
                        size="small"
                        variant="text"
                        color="warning"
                        title="确认清理"
                        aria-label="确认清理"
                        :loading="pending === batch.batch_id"
                        @click="confirmCleanup(batch.batch_id)"
                      />
                    </td>
                  </tr>
                </tbody>
              </v-table>
            </div>
            <div v-else class="empty-state">
              <div class="empty-icon" aria-hidden="true"><v-icon size="19">mdi-shield-check-outline</v-icon></div>
              <strong>没有待确认批次</strong>
              <span>缺失文件会在扫描后显示在这里。</span>
            </div>
          </section>
        </div>
      </section>

      <section v-show="activeTab === 'config'" class="config-view-host" aria-labelledby="config-title">
        <Config
          embedded
          :initial-config="initialConfig"
          :api="props.api"
          @save="handleConfigSave"
          @close="activeTab = 'dashboard'"
        />
      </section>
    </main>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import Config from './Config.vue'
import { unwrapApiResponse } from './api_response.js'
import { readPluginConfig } from './config_persistence.js'

const props = defineProps({
  api: { type: Object, default: () => ({}) },
  initialConfig: { type: Object, default: () => ({}) },
  config: { type: Object, default: () => ({}) },
  version: { type: String, default: '2.1.9' },
  defaultTab: { type: String, default: 'dashboard' },
})

const emit = defineEmits(['save'])

const activeTab = ref(props.defaultTab === 'config' ? 'config' : 'dashboard')
const loading = ref(false)
const pending = ref(null)
const error = ref('')
const lastUpdated = ref(null)
const failures = ref([])
const savedConfig = ref(null)
const status = reactive({
  enabled: false,
  reliable_engine: false,
  scan_running: false,
  command_running: false,
  monitor_active: false,
  queue_active: false,
  service_running: false,
  service_busy: false,
  service_state: 'disabled',
  queued: 0,
  active_queued: 0,
  pending_jobs: 0,
  orphaned_queued: 0,
  engine: { memory_queued: 0, inflight: 0, scheduled: 0, workers: 0 },
  command_progress: {
    running: false,
    run_id: '',
    label: '',
    monitor_root: '',
    phase: 'idle',
    total: 0,
    processed: 0,
    unchanged: 0,
    skipped: 0,
    failed: 0,
    current_path: '',
    last_progress_at: null,
    started_at: null,
    finished_at: null,
    stalled: false,
    stalled_seconds: 0,
    result_counts: { existing_skipped: 0, copied_non_media: 0, copied_subtitle: 0, generated_strm: 0, failed: 0 },
    errors: [],
  },
  recent_runs: [],
  cleanup_batches: [],
})

const version = computed(() => props.version || '2.1.9')
const initialConfig = computed(() => {
  if (savedConfig.value && Object.keys(savedConfig.value).length) return savedConfig.value
  if (props.initialConfig && Object.keys(props.initialConfig).length) return props.initialConfig
  return props.config || {}
})
const runtimeActive = computed(() => Boolean(status.service_busy))
const runtimeLabel = computed(() => {
  if (status.service_state === 'pending_recovery') return '有待恢复任务'
  if (runtimeActive.value) return '同步任务处理中'
  return status.service_running ? '同步服务待机' : (status.enabled ? '同步服务未运行' : '同步服务已停用')
})
const runtimeTitle = computed(() => {
  if (status.command_running) return '手动 /strm 正在执行'
  if (status.scan_running) return '全量扫描正在进行'
  if (status.engine.inflight > 0) return '同步引擎正在处理任务'
  if (status.service_state === 'pending_recovery') return '发现待恢复的持久化任务'
  if (status.service_state === 'monitoring_idle') return '目录监控已启用，当前空闲'
  if (status.service_state === 'engine_idle') return '可靠同步引擎已启用，当前空闲'
  if (status.service_state === 'queue_running') return '可靠同步引擎正在处理队列'
  if (status.service_state === 'enabled_idle') return '同步服务已启用，当前空闲'
  if (!status.enabled) return '同步服务未启用'
  return status.reliable_engine ? '可靠同步引擎已就绪' : '基础同步逻辑已就绪'
})
const runtimeDescription = computed(() => {
  if (status.command_running) return '手动命令完成后会显示成功、未变化、跳过和失败数量。'
  if (status.scan_running) return '新发现的媒体文件会按目录规则生成 STRM。'
  if (status.engine.inflight > 0) return '队列中的任务正在按工作线程逐项处理。'
  if (status.service_state === 'pending_recovery') return `持久化队列中有 ${status.orphaned_queued} 个任务等待可靠同步引擎恢复。`
  if (status.service_state === 'monitoring_idle') return '目录变化会按配置规则触发 STRM 生成。'
  if (status.service_state === 'engine_idle') return '任务队列当前没有正在处理的文件。'
  if (status.service_state === 'queue_running') return '队列中的任务正在等待或按工作线程处理。'
  if (status.service_state === 'enabled_idle') return '监控与任务队列当前没有正在处理的文件。'
  if (!status.enabled) return '启用插件后才会启动监控、扫描或可靠同步服务。'
  return status.reliable_engine ? '队列、失败记录与清理确认均已纳入状态追踪。' : '开启可靠同步后可获得完整的任务追踪能力。'
})
const lastUpdatedLabel = computed(() => lastUpdated.value ? formatTime(lastUpdated.value) : '尚未刷新')
const commandProgress = computed(() => status.command_progress)
const commandProgressCompleted = computed(() => (
  Number(commandProgress.value.processed || 0)
  + Number(commandProgress.value.unchanged || 0)
  + Number(commandProgress.value.skipped || 0)
  + Number(commandProgress.value.failed || 0)
))
const commandProgressPercent = computed(() => {
  const total = Number(commandProgress.value.total || 0)
  return total > 0 ? Math.min(100, (commandProgressCompleted.value / total) * 100) : 0
})
const commandProgressHasData = computed(() => Boolean(
  commandProgress.value.running
  || commandProgress.value.run_id
  || commandProgress.value.total
  || commandProgress.value.current_path
))
const commandProgressPhaseLabel = computed(() => ({
  idle: '未开始',
  discovering: '发现文件',
  processing: '处理中',
  completed: '已完成',
}[commandProgress.value.phase] || commandProgress.value.phase || '未知'))
const resultCategories = [
  { key: 'existing_skipped', label: '已有内容跳过', tone: 'muted' },
  { key: 'copied_non_media', label: '复制非媒体', tone: 'neutral' },
  { key: 'copied_subtitle', label: '复制字幕', tone: 'info' },
  { key: 'generated_strm', label: '生成 STRM', tone: 'success' },
  { key: 'failed', label: '失败', tone: 'danger' },
]

function formatTime(value) {
  if (value === null || value === undefined || value === '') return '-'
  const numeric = Number(value)
  const date = Number.isFinite(numeric) && numeric > 0
    ? new Date(numeric < 100000000000 ? numeric * 1000 : numeric)
    : new Date(value)
  if (Number.isNaN(date.getTime())) return '-'
  return date.toLocaleString('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
  })
}

function formatDuration(value) {
  const seconds = Math.max(0, Number(value) || 0)
  if (seconds < 60) return `${seconds} 秒`
  const minutes = Math.floor(seconds / 60)
  const remainder = seconds % 60
  return remainder ? `${minutes} 分 ${remainder} 秒` : `${minutes} 分钟`
}

function statusTone(value) {
  const normalized = String(value || '').toLowerCase()
  if (['done', 'success', 'completed', 'completed_empty', '完成', '成功'].includes(normalized)) return 'status-chip--success'
  if (['completed_with_errors', 'partial', '部分完成'].includes(normalized)) return 'status-chip--danger'
  if (['failed', 'error', '失败'].includes(normalized)) return 'status-chip--danger'
  if (['pending', 'queued', '排队'].includes(normalized)) return 'status-chip--muted'
  return 'status-chip--active'
}

function displayStatus(value) {
  const labels = { running: '处理中', processing: '处理中', pending: '排队中', queued: '排队中', success: '已完成', completed: '已完成', completed_empty: '无文件', completed_with_errors: '部分完成', done: '已完成', failed: '失败', error: '失败' }
  return labels[String(value || '').toLowerCase()] || value || '未知'
}

function resultItems(run = {}) {
  const counts = run.result_counts || {}
  return resultCategories
    .map(category => ({ ...category, count: Number(counts[category.key] || 0) }))
    .filter(item => item.count > 0)
}

function applyStatus(data = {}) {
  Object.assign(status, data)
  status.engine = { memory_queued: 0, inflight: 0, scheduled: 0, workers: 0, ...(data.engine || {}) }
  status.command_progress = {
    ...status.command_progress,
    ...(data.command_progress || {}),
    result_counts: {
      ...status.command_progress.result_counts,
      ...(data.command_progress?.result_counts || {}),
    },
    errors: Array.isArray(data.command_progress?.errors) ? data.command_progress.errors : [],
  }
  status.recent_runs = Array.isArray(data.recent_runs) ? data.recent_runs : []
  status.cleanup_batches = Array.isArray(data.cleanup_batches) ? data.cleanup_batches : []
}

async function load() {
  if (!props.api?.get || loading.value) return
  loading.value = true
  error.value = ''
  try {
    const [statusResponse, failureResponse] = await Promise.all([
      props.api.get('plugin/CloudStrmButler/sync_status'),
      props.api.get('plugin/CloudStrmButler/sync_failures'),
    ])
    const statusResult = unwrapApiResponse(statusResponse)
    const failureResult = unwrapApiResponse(failureResponse)
    if (statusResult?.code !== 0) throw new Error(statusResult?.msg || '读取状态失败')
    if (failureResult?.code !== 0) throw new Error(failureResult?.msg || '读取失败任务失败')
    applyStatus(statusResult.data || {})
    failures.value = Array.isArray(failureResult?.data?.items) ? failureResult.data.items : []
    lastUpdated.value = Date.now()
  } catch (err) {
    error.value = err.message || '读取状态失败'
  } finally {
    loading.value = false
  }
}

async function loadConfig() {
  if (!props.api?.get) return
  try {
    const persisted = await readPluginConfig(props.api)
    savedConfig.value = { ...persisted }
  } catch (err) {
    error.value = err.message || '读取插件配置失败'
  }
}

async function retry(failureId) {
  pending.value = failureId
  error.value = ''
  try {
    const response = await props.api.post('plugin/CloudStrmButler/sync_retry_failure', { failure_id: failureId })
    const result = unwrapApiResponse(response)
    if (result?.code !== 0) throw new Error(result?.msg || '重试失败')
    await load()
  } catch (err) {
    error.value = err.message || '重试失败'
  } finally {
    pending.value = null
  }
}

async function confirmCleanup(batchId) {
  pending.value = batchId
  error.value = ''
  try {
    const response = await props.api.post('plugin/CloudStrmButler/sync_confirm_cleanup', { batch_id: batchId })
    const result = unwrapApiResponse(response)
    if (result?.code !== 0) throw new Error(result?.msg || '清理失败')
    await load()
  } catch (err) {
    error.value = err.message || '清理失败'
  } finally {
    pending.value = null
  }
}

async function handleConfigSave(payload) {
  savedConfig.value = payload && typeof payload === 'object' ? { ...payload } : null
  emit('save', payload)
  await load()
}

let refreshTimer = null
let pageDisposed = false

onMounted(async () => {
  pageDisposed = false
  await loadConfig()
  await load()
  if (!pageDisposed) refreshTimer = window.setInterval(load, 5000)
})

onUnmounted(() => {
  pageDisposed = true
  if (refreshTimer !== null) {
    window.clearInterval(refreshTimer)
    refreshTimer = null
  }
})
</script>

<style scoped>
.cloudstrm-shell {
  --cs-bg: #121218;
  --cs-surface: #181820;
  --cs-surface-raised: #1c1c24;
  --cs-surface-inset: #101016;
  --cs-line: #2a2a35;
  --cs-line-strong: #3d3d4c;
  --cs-text: #f5f3fb;
  --cs-muted: #a5a2b1;
  --cs-dim: #72707e;
  --cs-primary: #7c4dff;
  --cs-primary-soft: #b59cff;
  --cs-success: #59d39b;
  --cs-warning: #e7b764;
  --cs-danger: #ff7f92;
  background: var(--cs-bg);
  color: var(--cs-text);
  min-height: 100%;
  font-family: "SF Pro Display", "PingFang SC", "Microsoft YaHei", sans-serif;
  letter-spacing: 0;
  line-height: 1.45;
}

.shell-header {
  align-items: center;
  background: var(--cs-surface);
  display: grid;
  grid-template-columns: minmax(260px, 1fr) auto auto;
  min-height: 72px;
  padding: 0 24px;
  position: relative;
}

.brand-lockup,
.header-actions,
.runtime-indicator,
.section-heading,
.metric-heading,
.page-intro,
.runtime-banner,
.banner-copy,
.empty-state {
  align-items: center;
  display: flex;
}

.brand-lockup { gap: 12px; min-width: 0; }
.brand-mark {
  align-items: center;
  background: rgba(124, 77, 255, .16);
  border: 1px solid rgba(181, 156, 255, .34);
  border-radius: 8px;
  color: var(--cs-primary-soft);
  display: flex;
  flex: 0 0 38px;
  height: 38px;
  justify-content: center;
  width: 38px;
}
.brand-copy { min-width: 0; }
.brand-title { font-size: 16px; font-weight: 700; line-height: 1.2; white-space: nowrap; }
.brand-version { color: var(--cs-dim); font-size: 12px; font-weight: 500; margin-left: 7px; }
.brand-subtitle { color: var(--cs-dim); font-size: 11px; margin-top: 4px; }

.header-actions { gap: 14px; justify-content: flex-end; }
.runtime-indicator { color: var(--cs-muted); font-size: 12px; gap: 7px; white-space: nowrap; }
.runtime-dot { background: var(--cs-dim); border-radius: 50%; height: 7px; width: 7px; }
.runtime-indicator.is-active { color: var(--cs-success); }
.runtime-indicator.is-active .runtime-dot { background: var(--cs-success); box-shadow: 0 0 0 4px rgba(89, 211, 155, .12); }

.tab-bar { align-self: stretch; display: flex; gap: 3px; margin-left: 28px; }
.tab-button {
  align-items: center;
  background: transparent;
  border: 0;
  border-bottom: 3px solid transparent;
  color: var(--cs-muted);
  cursor: pointer;
  display: inline-flex;
  font: inherit;
  font-size: 13px;
  font-weight: 600;
  gap: 8px;
  min-height: 72px;
  padding: 0 17px;
  transition: background-color .18s ease, border-color .18s ease, color .18s ease;
}
.tab-button:hover { background: rgba(255, 255, 255, .025); color: var(--cs-text); }
.tab-button:focus-visible { outline: 2px solid var(--cs-primary-soft); outline-offset: -3px; }
.tab-button.is-active { background: rgba(255, 255, 255, .025); border-bottom-color: var(--cs-primary); color: var(--cs-primary-soft); }

.shell-divider { background: var(--cs-line); height: 1px; }
.shell-content { margin: 0 auto; max-width: 1280px; padding: 30px 32px 48px; }
.shell-alert { margin-bottom: 22px; }

.page-intro { align-items: flex-end; justify-content: space-between; margin-bottom: 24px; }
.eyebrow { color: var(--cs-primary-soft); display: block; font-size: 10px; font-weight: 800; letter-spacing: 1.1px; margin-bottom: 8px; }
h1, h2, p { margin: 0; }
h1 { font-size: 25px; font-weight: 700; line-height: 1.2; }
.page-intro p { color: var(--cs-muted); font-size: 13px; margin-top: 8px; }
.intro-meta { border-left: 1px solid var(--cs-line); padding-left: 16px; }
.meta-label { color: var(--cs-dim); display: block; font-size: 11px; margin-bottom: 4px; }
.intro-meta strong { color: var(--cs-muted); font-size: 12px; font-weight: 500; }

.runtime-banner {
  background: var(--cs-surface);
  border: 1px solid var(--cs-line);
  border-radius: 8px;
  gap: 12px;
  margin-bottom: 18px;
  min-height: 64px;
  padding: 12px 15px;
}
.runtime-banner.is-active { border-color: rgba(89, 211, 155, .28); }
.banner-icon {
  align-items: center;
  background: rgba(124, 77, 255, .14);
  border-radius: 7px;
  color: var(--cs-primary-soft);
  display: flex;
  flex: 0 0 34px;
  height: 34px;
  justify-content: center;
  width: 34px;
}
.runtime-banner.is-active .banner-icon { background: rgba(89, 211, 155, .12); color: var(--cs-success); }
.banner-copy { align-items: flex-start; flex: 1; flex-direction: column; gap: 2px; min-width: 0; }
.banner-copy strong { font-size: 13px; font-weight: 650; }
.banner-copy span { color: var(--cs-muted); font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.metric-grid { display: grid; gap: 12px; grid-template-columns: repeat(4, minmax(0, 1fr)); margin-bottom: 34px; }
.engine-metrics-section { margin-bottom: 24px; }
.scope-note { color: var(--cs-dim); font-size: 11px; white-space: nowrap; }
.metric-tile {
  background: var(--cs-surface);
  border: 1px solid var(--cs-line);
  border-radius: 8px;
  min-height: 126px;
  padding: 15px 16px 13px;
}
.metric-tile--accent { border-color: rgba(124, 77, 255, .48); }
.metric-heading { color: var(--cs-muted); font-size: 12px; justify-content: space-between; }
.metric-heading .v-icon { color: var(--cs-dim); }
.metric-tile--accent .metric-heading .v-icon { color: var(--cs-primary-soft); }
.metric-tile strong { display: block; font-size: 28px; font-weight: 700; line-height: 1; margin-top: 22px; }
.metric-tile--accent strong { color: var(--cs-primary-soft); }
.metric-caption { color: var(--cs-dim); display: block; font-size: 11px; margin-top: 8px; }

.command-progress-frame {
  background: var(--cs-surface);
  border: 1px solid var(--cs-line);
  border-radius: 8px;
  padding: 18px;
}
.command-progress-top { align-items: flex-start; display: flex; justify-content: space-between; margin-bottom: 13px; }
.command-progress-copy strong { display: block; font-size: 24px; line-height: 1.1; margin-top: 3px; }
.command-progress-copy > span:last-child { color: var(--cs-dim); display: block; font-size: 11px; margin-top: 6px; }
.command-detail-grid { display: grid; gap: 12px; grid-template-columns: minmax(130px, .65fr) minmax(0, 2fr) minmax(150px, .8fr); margin-top: 18px; }
.command-detail { background: var(--cs-surface-inset); border: 1px solid var(--cs-line); border-radius: 6px; min-width: 0; padding: 10px 11px; }
.command-detail span { color: var(--cs-dim); display: block; font-size: 11px; }
.command-detail strong { color: var(--cs-muted); display: block; font-size: 12px; margin-top: 5px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.command-detail--path strong { color: var(--cs-text); }
.stalled-warning { align-items: flex-start; background: rgba(231, 183, 100, .1); border: 1px solid rgba(231, 183, 100, .28); border-radius: 6px; color: var(--cs-warning); display: flex; font-size: 12px; gap: 8px; line-height: 1.45; margin-top: 14px; padding: 10px 11px; }
.result-summary-heading { align-items: center; display: flex; justify-content: space-between; margin-top: 20px; }
.result-summary-heading strong { font-size: 13px; }
.result-summary-heading span { font-size: 11px; }
.result-category-grid { display: grid; gap: 9px; grid-template-columns: repeat(5, minmax(0, 1fr)); margin-top: 10px; }
.result-category { background: var(--cs-surface-inset); border: 1px solid var(--cs-line); border-radius: 6px; min-width: 0; padding: 10px 11px; }
.result-category span { color: var(--cs-muted); display: block; font-size: 11px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.result-category strong { display: block; font-size: 20px; line-height: 1; margin-top: 8px; }
.result-category--muted strong { color: var(--cs-muted); }
.result-category--neutral strong { color: var(--cs-text); }
.result-category--info strong { color: #79c8ff; }
.result-category--success strong { color: var(--cs-success); }
.result-category--danger strong { color: var(--cs-danger); }
.command-errors { color: var(--cs-danger); font-size: 11px; line-height: 1.5; margin: 13px 0 0; padding-left: 19px; }

.content-section { margin-bottom: 32px; min-width: 0; }
.section-heading { align-items: flex-start; justify-content: space-between; margin-bottom: 12px; }
.section-heading--compact { align-items: center; }
h2 { font-size: 15px; font-weight: 700; line-height: 1.3; }
.section-heading p { color: var(--cs-dim); font-size: 12px; margin-top: 5px; }
.section-count {
  align-items: center;
  background: var(--cs-surface);
  border: 1px solid var(--cs-line);
  border-radius: 5px;
  color: var(--cs-dim);
  display: inline-flex;
  font-size: 11px;
  height: 25px;
  justify-content: center;
  min-width: 25px;
  padding: 0 7px;
}
.section-count.has-items { border-color: rgba(255, 127, 146, .35); color: var(--cs-danger); }

.table-frame {
  background: var(--cs-surface);
  border: 1px solid var(--cs-line);
  border-radius: 8px;
  overflow-x: auto;
}
.status-table { background: transparent; color: var(--cs-text); min-width: 600px; }
.status-table :deep(table) { width: 100%; }
.status-table :deep(th) {
  background: rgba(255, 255, 255, .018);
  border-bottom: 1px solid var(--cs-line) !important;
  color: var(--cs-dim) !important;
  font-size: 11px;
  font-weight: 600;
  height: 39px;
  white-space: nowrap;
}
.status-table :deep(td) { border-bottom: 1px solid rgba(42, 42, 53, .72) !important; color: var(--cs-muted); font-size: 12px; height: 49px; }
.status-table :deep(tr:last-child td) { border-bottom: 0 !important; }
.status-table :deep(tbody tr:hover) { background: rgba(255, 255, 255, .025); }
.time-cell { color: var(--cs-muted) !important; font-variant-numeric: tabular-nums; white-space: nowrap; }
.path-cell { max-width: 300px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.result-cell { max-width: 360px; min-width: 230px; }
.result-inline { border-radius: 3px; display: inline-block; font-size: 10px; line-height: 1.2; margin: 2px 5px 2px 0; padding: 4px 5px; white-space: nowrap; }
.result-inline--muted { background: rgba(165, 162, 177, .1); color: var(--cs-muted); }
.result-inline--neutral { background: rgba(245, 243, 251, .08); color: var(--cs-text); }
.result-inline--info { background: rgba(121, 200, 255, .1); color: #79c8ff; }
.result-inline--success { background: rgba(89, 211, 155, .12); color: var(--cs-success); }
.result-inline--danger { background: rgba(255, 127, 146, .12); color: var(--cs-danger); }
.muted-value { color: var(--cs-dim); }
.action-cell { text-align: right; width: 54px; }
.danger-number { color: var(--cs-danger) !important; }
.empty-row { color: var(--cs-dim) !important; height: 90px !important; text-align: center; }
.status-chip {
  border: 1px solid transparent;
  border-radius: 4px;
  display: inline-flex;
  font-size: 11px;
  font-weight: 600;
  line-height: 1;
  padding: 5px 7px;
}
.status-chip--active { background: rgba(124, 77, 255, .14); border-color: rgba(181, 156, 255, .2); color: var(--cs-primary-soft); }
.status-chip--success { background: rgba(89, 211, 155, .12); border-color: rgba(89, 211, 155, .2); color: var(--cs-success); }
.status-chip--danger { background: rgba(255, 127, 146, .12); border-color: rgba(255, 127, 146, .2); color: var(--cs-danger); }
.status-chip--muted { background: rgba(165, 162, 177, .1); border-color: rgba(165, 162, 177, .18); color: var(--cs-muted); }

.dashboard-columns { display: grid; gap: 28px; grid-template-columns: repeat(2, minmax(0, 1fr)); }
.dashboard-columns .content-section { margin-bottom: 0; }
.empty-state {
  background: var(--cs-surface);
  border: 1px solid var(--cs-line);
  border-radius: 8px;
  flex-direction: column;
  justify-content: center;
  min-height: 150px;
  padding: 24px;
  text-align: center;
}
.empty-icon {
  align-items: center;
  background: rgba(165, 162, 177, .1);
  border: 1px solid rgba(165, 162, 177, .18);
  border-radius: 50%;
  color: var(--cs-muted);
  display: flex;
  height: 34px;
  justify-content: center;
  margin-bottom: 11px;
  width: 34px;
}
.empty-icon--success { background: rgba(89, 211, 155, .11); border-color: rgba(89, 211, 155, .24); color: var(--cs-success); }
.empty-state strong { font-size: 13px; font-weight: 650; }
.empty-state span { color: var(--cs-dim); font-size: 12px; margin-top: 5px; }

.config-view-host { min-width: 0; }

@media (max-width: 900px) {
  .shell-header { grid-template-columns: 1fr auto; padding: 0 18px; }
  .tab-bar { grid-column: 1 / -1; grid-row: 2; margin-left: 0; min-height: 50px; }
  .tab-button { min-height: 50px; padding: 0 14px; }
  .metric-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .result-category-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .command-detail-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .command-detail--path { grid-column: 1 / -1; }
  .dashboard-columns { grid-template-columns: 1fr; }
  .shell-content { padding: 26px 22px 40px; }
}

@media (max-width: 560px) {
  .shell-header { min-height: 66px; }
  .brand-subtitle, .runtime-indicator { display: none; }
  .brand-title { font-size: 14px; }
  .brand-mark { flex-basis: 34px; height: 34px; width: 34px; }
  .shell-content { padding: 22px 14px 32px; }
  .page-intro { align-items: flex-start; flex-direction: column; gap: 16px; }
  .intro-meta { border-left: 0; border-top: 1px solid var(--cs-line); padding-left: 0; padding-top: 10px; width: 100%; }
  .runtime-banner { align-items: flex-start; }
  .banner-copy span { white-space: normal; }
  .scope-note { text-align: right; white-space: normal; }
  .metric-grid { gap: 9px; }
  .result-category-grid, .command-detail-grid { grid-template-columns: 1fr 1fr; }
  .result-category:last-child { grid-column: 1 / -1; }
  .metric-tile { min-height: 116px; padding: 13px; }
  .metric-tile strong { font-size: 25px; margin-top: 18px; }
  .dashboard-columns { gap: 24px; }
}
</style>
