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
            {{ runtimeActive ? '运行中' : '待机' }}
          </v-chip>
        </section>

        <div class="metric-grid" aria-label="同步指标">
          <article class="metric-tile">
            <div class="metric-heading">
              <span>持久化队列</span>
              <v-icon size="18">mdi-database-outline</v-icon>
            </div>
            <strong>{{ status.queued }}</strong>
            <span class="metric-caption">等待进入同步流程</span>
          </article>
          <article class="metric-tile">
            <div class="metric-heading">
              <span>内存队列</span>
              <v-icon size="18">mdi-memory</v-icon>
            </div>
            <strong>{{ status.engine.memory_queued }}</strong>
            <span class="metric-caption">已载入引擎的任务</span>
          </article>
          <article class="metric-tile metric-tile--accent">
            <div class="metric-heading">
              <span>处理中</span>
              <v-icon size="18">mdi-sync</v-icon>
            </div>
            <strong>{{ status.engine.inflight }}</strong>
            <span class="metric-caption">当前正在处理</span>
          </article>
          <article class="metric-tile">
            <div class="metric-heading">
              <span>工作线程</span>
              <v-icon size="18">mdi-lan-connect</v-icon>
            </div>
            <strong>{{ status.engine.workers }}</strong>
            <span class="metric-caption">同步引擎并发数</span>
          </article>
        </div>

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
                  <th>失败</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="run in status.recent_runs" :key="run.run_id">
                  <td class="time-cell">{{ formatTime(run.started_at) }}</td>
                  <td><span class="status-chip" :class="statusTone(run.status)">{{ displayStatus(run.status) }}</span></td>
                  <td>{{ run.queued ?? 0 }}</td>
                  <td>{{ run.processed ?? 0 }}</td>
                  <td>{{ run.unchanged ?? 0 }}</td>
                  <td :class="{ 'danger-number': Number(run.failed) > 0 }">{{ run.failed ?? 0 }}</td>
                </tr>
                <tr v-if="!status.recent_runs.length">
                  <td colspan="6" class="empty-row">暂无任务记录</td>
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
import { computed, onMounted, reactive, ref } from 'vue'
import Config from './Config.vue'
import { unwrapApiResponse } from './api_response.js'

const props = defineProps({
  api: { type: Object, default: () => ({}) },
  initialConfig: { type: Object, default: () => ({}) },
  config: { type: Object, default: () => ({}) },
  version: { type: String, default: '2.1.4' },
  defaultTab: { type: String, default: 'dashboard' },
})

const emit = defineEmits(['save'])

const activeTab = ref(props.defaultTab === 'config' ? 'config' : 'dashboard')
const loading = ref(false)
const pending = ref(null)
const error = ref('')
const lastUpdated = ref(null)
const failures = ref([])
const status = reactive({
  enabled: false,
  reliable_engine: false,
  scan_running: false,
  queued: 0,
  engine: { memory_queued: 0, inflight: 0, scheduled: 0, workers: 0 },
  recent_runs: [],
  cleanup_batches: [],
})

const version = computed(() => props.version || '2.1.4')
const initialConfig = computed(() => {
  if (props.initialConfig && Object.keys(props.initialConfig).length) return props.initialConfig
  return props.config || {}
})
const runtimeActive = computed(() => Boolean(status.enabled || status.scan_running || status.engine.inflight > 0))
const runtimeLabel = computed(() => runtimeActive.value ? '同步服务运行中' : '同步服务待机')
const runtimeTitle = computed(() => {
  if (status.scan_running) return '全量扫描正在进行'
  if (status.engine.inflight > 0) return '同步引擎正在处理任务'
  return status.reliable_engine ? '可靠同步引擎已就绪' : '基础同步逻辑已就绪'
})
const runtimeDescription = computed(() => {
  if (status.scan_running) return '新发现的媒体文件会按目录规则生成 STRM。'
  if (status.engine.inflight > 0) return '队列中的任务正在按工作线程逐项处理。'
  return status.reliable_engine ? '队列、失败记录与清理确认均已纳入状态追踪。' : '开启可靠同步后可获得完整的任务追踪能力。'
})
const lastUpdatedLabel = computed(() => lastUpdated.value ? formatTime(lastUpdated.value) : '尚未刷新')

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

function statusTone(value) {
  const normalized = String(value || '').toLowerCase()
  if (['done', 'success', 'completed', '完成', '成功'].includes(normalized)) return 'status-chip--success'
  if (['failed', 'error', '失败'].includes(normalized)) return 'status-chip--danger'
  if (['pending', 'queued', '排队'].includes(normalized)) return 'status-chip--muted'
  return 'status-chip--active'
}

function displayStatus(value) {
  const labels = { running: '处理中', processing: '处理中', pending: '排队中', queued: '排队中', success: '已完成', completed: '已完成', done: '已完成', failed: '失败', error: '失败' }
  return labels[String(value || '').toLowerCase()] || value || '未知'
}

function applyStatus(data = {}) {
  Object.assign(status, data)
  status.engine = { memory_queued: 0, inflight: 0, scheduled: 0, workers: 0, ...(data.engine || {}) }
  status.recent_runs = Array.isArray(data.recent_runs) ? data.recent_runs : []
  status.cleanup_batches = Array.isArray(data.cleanup_batches) ? data.cleanup_batches : []
}

async function load() {
  if (!props.api?.get) return
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

function handleConfigSave(payload) {
  emit('save', payload)
}

onMounted(load)
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
  .metric-grid { gap: 9px; }
  .metric-tile { min-height: 116px; padding: 13px; }
  .metric-tile strong { font-size: 25px; margin-top: 18px; }
  .dashboard-columns { gap: 24px; }
}
</style>
