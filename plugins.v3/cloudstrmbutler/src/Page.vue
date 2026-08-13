<template>
  <v-card class="workspace-page">
    <v-card-item class="workspace-header">
      <div>
        <v-card-title class="pa-0">同步工作台</v-card-title>
        <v-card-subtitle class="pa-0 mt-1">查看同步健康度，并优先处理需要你确认的事项。</v-card-subtitle>
      </div>
      <template #append>
        <v-btn class="refresh-button" variant="outlined" prepend-icon="mdi-refresh" :loading="loading" @click="load">刷新状态</v-btn>
      </template>
    </v-card-item>

    <v-divider />

    <v-card-text class="workspace-body">
      <v-alert v-if="error" type="error" variant="tonal" closable class="workspace-error" @click:close="error = ''">{{ error }}</v-alert>

      <section class="summary-grid">
        <article class="health-card" :class="healthTone">
          <div class="health-mark"><v-icon :icon="healthIcon" size="30" /></div>
          <div class="health-copy">
            <h2>{{ healthTitle }}</h2>
            <p>{{ healthDescription }}</p>
            <div class="monitor-chip"><v-icon icon="mdi-circle" size="8" />{{ status.enabled ? '监控中' : '未启用' }}</div>
          </div>
          <div class="health-meta">
            <div><span>最近完成</span><strong>{{ latestRun ? formatShortTime(latestRun.started_at) : '-' }}</strong></div>
            <div><span>本次处理</span><strong>{{ latestRun ? latestRun.processed + ' 个文件' : '-' }}</strong></div>
            <div><span>运行耗时</span><strong>{{ latestRun ? formatDuration(latestRun) : '-' }}</strong></div>
          </div>
        </article>

        <article class="action-queue">
          <div class="action-queue__head">
            <h2>需要处理</h2>
            <span>{{ actionCount }} 项</span>
          </div>
          <button v-if="failures.length" class="queue-action" type="button" @click="showFailures = true">
            <i class="queue-dot queue-dot--failure" />
            <span><strong>{{ failures.length }} 个同步失败</strong><small>最近发生于 {{ formatShortTime(failures[0].updated_at) }}，可查看原因后重试</small></span>
            <v-icon icon="mdi-arrow-right" size="20" />
          </button>
          <button v-if="primaryCleanupBatch" class="queue-action" type="button" @click="openCleanupPreview(primaryCleanupBatch.batch_id)">
            <i class="queue-dot queue-dot--cleanup" />
            <span><strong>{{ status.cleanup_batches.length }} 个清理批次待确认</strong><small>{{ primaryCleanupBatch.path_count }} 个生成文件 {{ expirationLabel(primaryCleanupBatch.expires_at) }}</small></span>
            <v-icon icon="mdi-arrow-right" size="20" />
          </button>
          <div v-if="!hasActionNeeded" class="queue-empty"><v-icon icon="mdi-check-circle-outline" size="19" />当前没有待处理事项</div>
        </article>
      </section>

      <section class="overview-section">
        <div class="section-title"><h2>运行概览</h2><p>当前同步引擎的即时状态</p></div>
        <div class="metrics-grid">
          <article class="metric-card"><span>持久化队列</span><strong>{{ status.queued }}</strong><small :class="{ 'metric-good': !status.queued }">{{ status.queued ? '等待处理任务' : '无待处理任务' }}</small></article>
          <article class="metric-card"><span>正在处理</span><strong>{{ status.engine.inflight }}</strong><small>个文件</small></article>
          <article class="metric-card"><span>工作线程</span><strong>{{ status.engine.workers }}</strong><small>个运行中</small></article>
          <article class="metric-card metric-card--attention"><span>未解决失败</span><strong>{{ failures.length }}</strong><small>{{ failures.length ? '需要检查' : '状态正常' }}</small></article>
        </div>
      </section>

      <section class="lower-grid">
        <article class="recent-card">
          <div class="panel-heading">
            <div><h2>最近运行</h2><p>保留最近 20 次同步结果</p></div>
            <v-btn variant="text" size="small" class="panel-link" @click="showAllRuns = !showAllRuns">{{ showAllRuns ? '收起' : '查看全部' }}</v-btn>
          </div>
          <div class="history-table-wrap">
            <table class="history-table">
              <thead><tr><th>开始时间</th><th>结果</th><th>已处理</th><th>未变化</th><th>失败</th></tr></thead>
              <tbody>
                <tr v-for="run in displayedRuns" :key="run.run_id">
                  <td>{{ formatShortTime(run.started_at) }}</td>
                  <td><span class="run-result" :class="'run-result--' + run.status">{{ runStatus(run.status) }}</span></td>
                  <td>{{ run.processed }}</td><td>{{ run.unchanged }}</td><td :class="{ 'failed-number': run.failed }">{{ run.failed }}</td>
                </tr>
                <tr v-if="!status.recent_runs.length"><td colspan="5" class="history-empty">还没有同步记录。启用同步后，运行结果会出现在这里。</td></tr>
              </tbody>
            </table>
          </div>
          <p class="panel-footnote">运行历史可用于判断异常是否重复出现。</p>
        </article>

        <article class="failure-panel">
          <div class="failure-panel__topline" />
          <div class="panel-heading">
            <div><h2>同步失败 <em>{{ failures.length }} 个待处理</em></h2></div>
          </div>
          <div v-if="failures.length" class="failure-list">
            <div v-for="item in displayedFailures" :key="item.id" class="failure-entry">
              <div class="failure-entry__copy">
                <span class="failure-path">{{ item.path }}</span>
                <strong>{{ item.error }}</strong>
                <small>已尝试 {{ item.attempts }} 次 · {{ formatShortTime(item.updated_at) }}</small>
              </div>
              <v-btn class="inspect-button" size="small" variant="outlined" :loading="pending === failurePendingKey(item.id)" @click="retry(item.id)">重试</v-btn>
            </div>
          </div>
          <div v-else class="failure-empty"><v-icon icon="mdi-check-circle-outline" size="22" />没有需要重试的同步失败</div>
          <v-btn v-if="failures.length" class="retry-all-button" variant="flat" :loading="pending === 'retry-all'" @click="retryAll">处理全部失败</v-btn>
        </article>
      </section>
    </v-card-text>
  </v-card>

  <v-dialog v-model="cleanupDialog" max-width="820" persistent>
    <v-card class="cleanup-dialog-card">
      <v-card-item class="cleanup-dialog__header">
        <div>
          <v-card-title class="pa-0">确认清理</v-card-title>
          <v-card-subtitle class="pa-0 mt-1">请先核对范围。确认后将删除以下已生成文件。</v-card-subtitle>
        </div>
        <template #append><v-btn icon="mdi-close" variant="text" title="关闭预览" :disabled="cleanupPending" @click="closeCleanupPreview" /></template>
      </v-card-item>
      <v-divider />
      <v-card-text v-if="cleanupPreview" class="cleanup-dialog__body">
        <v-alert class="cleanup-warning" type="warning" variant="tonal">
          <strong>这项操作会删除 {{ cleanupPreview.path_count }} 个 STRM 或旁车生成文件</strong>
          <span>不会删除云盘来源文件，也不会修改来源目录。</span>
        </v-alert>

        <h2 class="dialog-section-title">清理范围</h2>
        <div class="cleanup-summary-grid">
          <div class="cleanup-summary"><span>监控目录</span><strong class="path">{{ cleanupPreview.monitor_root }}</strong><small>扫描发现来源文件已缺失</small></div>
          <div class="cleanup-summary"><span>批次状态</span><strong>{{ cleanupPreview.path_count }} 个文件 · {{ expirationLabel(cleanupPreview.expires_at) }}</strong><small>创建于 {{ formatShortTime(cleanupPreview.created_at) }}</small></div>
        </div>

        <div class="cleanup-files-heading">
          <div><h2 class="dialog-section-title">将要删除的文件</h2><p>显示前 5 项，可用路径筛选抽查</p></div>
          <v-text-field v-model="cleanupSearch" prepend-inner-icon="mdi-magnify" label="筛选路径" variant="outlined" density="compact" hide-details />
        </div>
        <div class="cleanup-path-table">
          <div class="cleanup-path-table__label">输出文件路径</div>
          <div v-for="path in displayedCleanupPaths" :key="path" class="cleanup-path-row">{{ path }}</div>
          <div v-if="!displayedCleanupPaths.length" class="cleanup-path-row cleanup-path-row--empty">没有匹配的文件路径</div>
          <div v-if="filteredCleanupPaths.length > displayedCleanupPaths.length" class="cleanup-path-more">以及另外 {{ filteredCleanupPaths.length - displayedCleanupPaths.length }} 个生成文件</div>
        </div>
      </v-card-text>
      <v-divider />
      <v-card-actions class="cleanup-dialog__actions">
        <span>确认前请核对目录与路径；此批次确认后不可撤回。</span>
        <v-spacer />
        <v-btn variant="outlined" :disabled="cleanupPending" @click="closeCleanupPreview">取消</v-btn>
        <v-btn class="cleanup-confirm-button" variant="flat" :loading="cleanupPending" @click="confirmCleanup">确认清理</v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>

  <v-snackbar v-model="notice.visible" :color="notice.color" timeout="3500">{{ notice.text }}</v-snackbar>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'

const props = defineProps({ api: { type: Object, default: () => ({}) } })
const loading = ref(false)
const pending = ref(null)
const error = ref('')
const failures = ref([])
const showFailures = ref(false)
const showAllRuns = ref(false)
const previewLoading = ref(null)
const cleanupDialog = ref(false)
const cleanupPreview = ref(null)
const cleanupSearch = ref('')
const notice = reactive({ visible: false, text: '', color: 'success' })
const status = reactive({ queued: 0, enabled: false, reliable_engine: false, engine: { memory_queued: 0, inflight: 0, workers: 0 }, recent_runs: [], cleanup_batches: [] })

const latestRun = computed(() => status.recent_runs[0] || null)
const actionCount = computed(() => failures.value.length + status.cleanup_batches.length)
const hasActionNeeded = computed(() => actionCount.value > 0)
const primaryCleanupBatch = computed(() => status.cleanup_batches[0] || null)
const displayedRuns = computed(() => showAllRuns.value ? status.recent_runs : status.recent_runs.slice(0, 3))
const displayedFailures = computed(() => showFailures.value ? failures.value : failures.value.slice(0, 2))
const cleanupPending = computed(() => pending.value === 'cleanup-' + cleanupPreview.value?.batch_id)
const filteredCleanupPaths = computed(() => {
  const paths = cleanupPreview.value?.paths || []
  const term = cleanupSearch.value.trim().toLowerCase()
  return term ? paths.filter(path => path.toLowerCase().includes(term)) : paths
})
const displayedCleanupPaths = computed(() => filteredCleanupPaths.value.slice(0, 5))
const healthTitle = computed(() => {
  if (!status.enabled) return '同步尚未启用'
  if (hasActionNeeded.value) return actionCount.value + ' 项需要处理'
  return '同步运行正常'
})
const healthDescription = computed(() => {
  if (!status.enabled) return '启用插件后，目录变化和同步结果会显示在这里。'
  if (failures.value.length) return '发现同步失败任务。请先查看原因，再重新加入同步队列。'
  if (status.cleanup_batches.length) return '有批次等待你核对后确认清理。'
  return status.reliable_engine ? '可靠同步引擎正在处理目录变更，没有任务积压。' : '同步服务正在运行；启用可靠同步引擎可获得队列与失败记录。'
})
const healthIcon = computed(() => (status.enabled && !hasActionNeeded.value ? 'mdi-check' : hasActionNeeded.value ? 'mdi-alert' : 'mdi-information-outline'))
const healthTone = computed(() => (status.enabled && !hasActionNeeded.value ? 'is-healthy' : hasActionNeeded.value ? 'needs-attention' : 'is-neutral'))

function formatTime(value) {
  return value ? new Date(Number(value) * 1000).toLocaleString() : '-'
}

function formatShortTime(value) {
  if (!value) return '-'
  const date = new Date(Number(value) * 1000)
  const today = new Date()
  const sameDay = date.toDateString() === today.toDateString()
  const label = sameDay ? '今天' : date.toLocaleDateString(undefined, { month: '2-digit', day: '2-digit' })
  return label + ' ' + date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

function formatDuration(run) {
  if (!run?.finished_at || !run?.started_at) return '运行中'
  const seconds = Math.max(0, Number(run.finished_at) - Number(run.started_at))
  const minutes = Math.floor(seconds / 60)
  const remain = Math.floor(seconds % 60)
  return String(minutes).padStart(2, '0') + ':' + String(remain).padStart(2, '0')
}

function expirationLabel(value) {
  if (!value) return '无失效时间'
  const seconds = Math.max(0, Math.ceil((Number(value) * 1000 - Date.now()) / 1000))
  if (seconds < 3600) return Math.ceil(seconds / 60) + ' 分钟后失效'
  if (seconds < 86400) return Math.ceil(seconds / 3600) + ' 小时后失效'
  return Math.ceil(seconds / 86400) + ' 天后失效'
}

function runStatus(value) {
  return { completed: '完成', running: '运行中', failed: '异常' }[value] || value || '未知'
}

function failurePendingKey(id) {
  return 'failure-' + id
}

function showNotice(text, color = 'success') {
  notice.text = text
  notice.color = color
  notice.visible = true
}

async function load() {
  if (!props.api?.get) return
  loading.value = true
  error.value = ''
  try {
    const responses = await Promise.all([
      props.api.get('plugin/CloudStrmButler/sync_status'),
      props.api.get('plugin/CloudStrmButler/sync_failures'),
    ])
    const statusResponse = responses[0]
    const failureResponse = responses[1]
    if (statusResponse?.code !== 0) throw new Error(statusResponse?.msg || '读取同步状态失败')
    if (failureResponse?.code !== 0) throw new Error(failureResponse?.msg || '读取失败任务失败')
    Object.assign(status, statusResponse.data || {})
    status.engine = { memory_queued: 0, inflight: 0, workers: 0, ...(status.engine || {}) }
    status.recent_runs = Array.isArray(status.recent_runs) ? status.recent_runs : []
    status.cleanup_batches = Array.isArray(status.cleanup_batches) ? status.cleanup_batches : []
    failures.value = failureResponse?.data?.items || []
  } catch (err) {
    error.value = err.message || '读取同步状态失败'
  } finally {
    loading.value = false
  }
}

async function retry(failureId) {
  pending.value = failurePendingKey(failureId)
  try {
    const response = await props.api.post('plugin/CloudStrmButler/sync_retry_failure', { failure_id: failureId })
    if (response?.code !== 0) throw new Error(response?.msg || '重试失败')
    showNotice(response?.msg || '已重新加入同步队列')
    await load()
  } catch (err) {
    error.value = err.message || '重试失败'
  } finally {
    pending.value = null
  }
}

async function retryAll() {
  const items = [...failures.value]
  if (!items.length) return
  pending.value = 'retry-all'
  try {
    for (const item of items) {
      const response = await props.api.post('plugin/CloudStrmButler/sync_retry_failure', { failure_id: item.id })
      if (response?.code !== 0) throw new Error(response?.msg || '重试失败')
    }
    showNotice('已将 ' + items.length + ' 个失败任务重新加入同步队列')
    await load()
  } catch (err) {
    error.value = err.message || '批量重试失败'
  } finally {
    pending.value = null
  }
}

async function openCleanupPreview(batchId) {
  if (!props.api?.get) return
  previewLoading.value = batchId
  error.value = ''
  try {
    const response = await props.api.get('plugin/CloudStrmButler/sync_cleanup_preview?batch_id=' + encodeURIComponent(batchId))
    if (response?.code !== 0) throw new Error(response?.msg || '读取清理预览失败')
    cleanupPreview.value = response.data
    cleanupSearch.value = ''
    cleanupDialog.value = true
  } catch (err) {
    error.value = err.message || '读取清理预览失败'
  } finally {
    previewLoading.value = null
  }
}

function closeCleanupPreview() {
  cleanupDialog.value = false
  cleanupPreview.value = null
  cleanupSearch.value = ''
}

async function confirmCleanup() {
  const batchId = cleanupPreview.value?.batch_id
  if (!batchId) return
  pending.value = 'cleanup-' + batchId
  try {
    const response = await props.api.post('plugin/CloudStrmButler/sync_confirm_cleanup', { batch_id: batchId })
    if (response?.code !== 0) throw new Error(response?.msg || '清理失败')
    closeCleanupPreview()
    showNotice(response?.msg || '已清理生成文件')
    await load()
  } catch (err) {
    error.value = err.message || '清理失败'
  } finally {
    pending.value = null
  }
}

onMounted(load)
</script>

<style scoped>
.workspace-page,
.cleanup-dialog-card {
  --v-theme-primary: 45, 96, 115;
  --v-theme-on-primary: 255, 255, 255;
  --v-theme-success: 47, 132, 90;
  --v-theme-warning: 185, 112, 56;
  --v-theme-error: 174, 77, 46;
  --v-theme-surface: 255, 255, 255;
  --v-theme-surface-variant: 237, 242, 246;
  --v-theme-on-surface: 34, 48, 69;
  --v-theme-on-surface-variant: 100, 117, 140;
  color: #24314a;
  font-family: "Microsoft YaHei UI", "Microsoft YaHei", sans-serif;
}

.workspace-page { overflow: hidden; border: 1px solid #d9e2eb !important; border-radius: 8px !important; background: #fbfcfe !important; box-shadow: 0 12px 28px rgba(27, 45, 67, .08) !important; }
.workspace-page :deep(.v-card-item), .workspace-page :deep(.v-card-text), .cleanup-dialog-card :deep(.v-card-item), .cleanup-dialog-card :deep(.v-card-text), .cleanup-dialog-card :deep(.v-card-actions) { background: #fbfcfe; }
.workspace-page :deep(.v-card-title), .cleanup-dialog-card :deep(.v-card-title) { color: #1e2d43 !important; font-weight: 700; }
.workspace-page :deep(.v-card-subtitle), .cleanup-dialog-card :deep(.v-card-subtitle) { color: #66758c !important; opacity: 1 !important; }
.workspace-page :deep(.v-divider), .cleanup-dialog-card :deep(.v-divider) { border-color: #e0e6ed !important; opacity: 1 !important; }

.workspace-header { min-height: 106px; padding: 25px 28px 21px !important; }.workspace-header :deep(.v-card-title) { font-size: 24px; letter-spacing: 0; }.workspace-header :deep(.v-card-subtitle) { font-size: 14px; }.refresh-button { min-width: 142px; color: #31475f !important; border-color: #ccd6e2 !important; font-weight: 700; }.workspace-body { padding: 28px !important; }.workspace-error { margin-bottom: 18px; }.workspace-error :deep(.v-alert__content) { color: #8b3f2f !important; }

.summary-grid { display: grid; grid-template-columns: minmax(0, 1.68fr) minmax(330px, 1fr); gap: 18px; }.health-card, .action-queue, .recent-card, .failure-panel { border: 1px solid #dbe3eb; border-radius: 8px; background: #fff; }.health-card { position: relative; min-height: 184px; display: grid; grid-template-columns: 62px minmax(0, 1fr); gap: 18px; padding: 30px 30px 15px 40px; overflow: hidden; }.health-card::before { position: absolute; inset: 0 auto 0 0; width: 8px; border-radius: 4px; background: #4ea47b; content: ""; }.health-card.needs-attention::before { background: #d87348; }.health-card.is-neutral::before { background: #4f7890; }.health-mark { width: 56px; height: 56px; display: grid; place-items: center; border-radius: 50%; background: #e6f5ed; color: #34825e; }.needs-attention .health-mark { background: #fff0e5; color: #be633d; }.is-neutral .health-mark { background: #e8f1f6; color: #3f6c86; }.health-copy h2, .action-queue h2, .section-title h2, .panel-heading h2, .dialog-section-title { margin: 0; color: #202d43; font-size: 17px; font-weight: 700; letter-spacing: 0; }.health-copy p { margin: 7px 0 14px; color: #66758c; font-size: 14px; line-height: 1.55; }.monitor-chip { width: fit-content; display: inline-flex; align-items: center; gap: 7px; padding: 6px 12px; border-radius: 14px; background: #e7f5ec; color: #2d7052; font-size: 12px; font-weight: 700; }.monitor-chip :deep(.v-icon) { color: #48a476; }.needs-attention .monitor-chip { background: #fff0e5; color: #9d5735; }.health-meta { grid-column: 1 / -1; display: grid; grid-template-columns: repeat(3, 1fr); margin-top: 6px; padding: 10px 0 0; border-top: 1px solid #e8edf2; }.health-meta div { display: flex; align-items: center; gap: 14px; }.health-meta span { color: #66758c; font-size: 12px; }.health-meta strong { color: #26354b; font-size: 12px; font-weight: 700; }

.action-queue { min-height: 184px; padding: 20px 25px; }.action-queue__head { display: flex; align-items: center; justify-content: space-between; padding-bottom: 12px; border-bottom: 1px solid #e9edf2; }.action-queue__head span { padding: 5px 12px; border-radius: 14px; background: #fff0e5; color: #bc6239; font-size: 12px; font-weight: 700; }.queue-action { width: 100%; display: grid; grid-template-columns: 10px minmax(0, 1fr) 20px; gap: 10px; align-items: center; padding: 13px 0 0; border: 0; background: transparent; color: inherit; cursor: pointer; text-align: left; }.queue-action + .queue-action { padding-top: 12px; }.queue-action:hover strong { color: #2d6073; }.queue-action span { display: grid; gap: 4px; min-width: 0; }.queue-action strong { color: #26354b; font-size: 14px; }.queue-action small { overflow: hidden; color: #66758c; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }.queue-action :deep(.v-icon) { color: #496079; }.queue-dot { width: 10px; height: 10px; border-radius: 50%; }.queue-dot--failure { background: #d87348; }.queue-dot--cleanup { background: #d79a3f; }.queue-empty { display: flex; align-items: center; gap: 8px; padding-top: 27px; color: #527764; font-size: 13px; }.queue-empty :deep(.v-icon) { color: #48a476; }

.overview-section { margin-top: 30px; }.section-title { display: flex; align-items: baseline; gap: 22px; margin-bottom: 15px; }.section-title p, .panel-heading p { margin: 0; color: #66758c; font-size: 12px; }.metrics-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 16px; }.metric-card { min-height: 110px; padding: 18px 22px; border: 1px solid #dbe3eb; border-radius: 8px; background: #fff; }.metric-card > span { display: block; color: #66758c; font-size: 12px; }.metric-card strong { display: inline-block; margin-top: 10px; color: #161f2d; font-size: 29px; line-height: 1; }.metric-card small { margin-left: 14px; color: #66758c; font-size: 12px; }.metric-card .metric-good { color: #478264; }.metric-card--attention { border-color: #f1d4b5; background: #fff9f2; }.metric-card--attention > span, .metric-card--attention small { color: #9c6339; }.metric-card--attention strong { color: #ae5935; }

.lower-grid { display: grid; grid-template-columns: minmax(0, 1.9fr) minmax(300px, 1fr); gap: 18px; margin-top: 28px; }.recent-card { min-height: 336px; padding: 22px 24px; }.panel-heading { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding-bottom: 16px; border-bottom: 1px solid #e2e8ef; }.panel-heading > div { display: flex; align-items: baseline; gap: 22px; }.panel-link { color: #2d6073 !important; font-size: 12px; font-weight: 700; }.history-table-wrap { overflow-x: auto; }.history-table { width: 100%; border-collapse: collapse; text-align: left; }.history-table th { padding: 15px 0 13px; color: #8d99aa; font-size: 12px; font-weight: 700; }.history-table td { padding: 11px 0; border-top: 1px solid #eef2f6; color: #202d43; font-size: 14px; }.history-table th:nth-child(n+3), .history-table td:nth-child(n+3) { text-align: center; }.run-result { display: inline-flex; padding: 5px 14px; border-radius: 14px; font-size: 12px; font-weight: 700; }.run-result--completed { background: #e6f5ed; color: #2d7052; }.run-result--failed { background: #fff0e5; color: #ad5a36; }.run-result--running { background: #e7f0f7; color: #3e6680; }.failed-number { color: #ae5935 !important; font-weight: 700; }.history-empty { padding: 40px 0 !important; color: #66758c !important; text-align: center !important; }.panel-footnote { margin: 18px 0 0; color: #66758c; font-size: 12px; }

.failure-panel { position: relative; min-height: 336px; display: flex; flex-direction: column; padding: 22px 24px 28px; border-color: #e8c6ae; overflow: hidden; }.failure-panel__topline { position: absolute; inset: 0 0 auto; height: 5px; border-radius: 2px; background: #d87348; }.failure-panel .panel-heading { padding-top: 1px; }.failure-panel em { margin-left: 10px; color: #af5e38; font-size: 12px; font-style: normal; font-weight: 700; }.failure-list { display: grid; }.failure-entry { display: flex; align-items: center; justify-content: space-between; gap: 14px; padding: 15px 0; border-bottom: 1px solid #f2e8e2; }.failure-entry__copy { min-width: 0; display: grid; gap: 5px; }.failure-path { overflow: hidden; color: #66758c; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }.failure-entry strong { color: #ad5a36; font-size: 12px; }.failure-entry small { color: #8d99aa; font-size: 12px; }.inspect-button { min-width: 72px; color: #9e5232 !important; border-color: #d6a78c !important; font-size: 12px; font-weight: 700; }.retry-all-button { width: 100%; min-height: 40px; margin-top: auto; background: #2d6073 !important; color: #fff !important; font-size: 13px; font-weight: 700; }.failure-empty { display: flex; align-items: center; gap: 8px; flex: 1; color: #577b67; font-size: 13px; }.failure-empty :deep(.v-icon) { color: #48a476; }

.cleanup-dialog-card { border-radius: 10px !important; background: #fff !important; box-shadow: 0 18px 28px rgba(16, 29, 48, .24) !important; }.cleanup-dialog-card :deep(.v-card-item), .cleanup-dialog-card :deep(.v-card-text), .cleanup-dialog-card :deep(.v-card-actions) { background: #fff; }.cleanup-dialog__header { min-height: 105px; padding: 25px 40px 20px !important; }.cleanup-dialog__header :deep(.v-card-title) { font-size: 24px; }.cleanup-dialog__body { padding: 24px 40px 26px !important; }.cleanup-warning { margin-bottom: 29px; border: 1px solid #f0cfad !important; background: #fff7ed !important; color: #874a32 !important; }.cleanup-warning :deep(.v-alert__content) { display: grid; gap: 6px; color: #874a32 !important; }.cleanup-warning span { color: #985b42; font-size: 12px; }.cleanup-warning :deep(.v-icon) { color: #d87348 !important; }.dialog-section-title { font-size: 17px; }.cleanup-summary-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 26px; margin: 12px 0 27px; }.cleanup-summary { min-height: 87px; display: flex; flex-direction: column; gap: 8px; padding: 16px 19px; border: 1px solid #d8e2eb; border-radius: 7px; background: #f4f8fb; }.cleanup-summary span, .cleanup-summary small { color: #66758c; font-size: 12px; }.cleanup-summary strong { color: #24314a; font-size: 14px; }.cleanup-files-heading { display: flex; align-items: end; justify-content: space-between; gap: 20px; margin-bottom: 16px; }.cleanup-files-heading > div { display: flex; align-items: baseline; gap: 18px; }.cleanup-files-heading p { margin: 0; color: #66758c; font-size: 12px; }.cleanup-files-heading :deep(.v-input) { width: 237px; }.cleanup-files-heading :deep(.v-field) { color: #26354b !important; background: #fff !important; }.cleanup-files-heading :deep(.v-field__outline) { --v-field-border-opacity: 1; color: #bdc9d5 !important; }.cleanup-files-heading :deep(.v-label) { color: #8d99aa !important; opacity: 1 !important; }.cleanup-path-table { overflow: hidden; border: 1px solid #dce4ec; border-radius: 7px; background: #fff; }.cleanup-path-table__label { padding: 14px 20px 11px; color: #8d99aa; font-size: 12px; font-weight: 700; }.cleanup-path-row { margin: 0 20px; padding: 11px 0; border-top: 1px solid #eef2f5; overflow-wrap: anywhere; color: #24314a; font-size: 12px; }.cleanup-path-row--empty { color: #66758c; }.cleanup-path-more { padding: 0 20px 13px; color: #66758c; font-size: 12px; }.cleanup-dialog__actions { min-height: 99px; padding: 20px 40px !important; }.cleanup-dialog__actions > span { color: #66758c; font-size: 12px; }.cleanup-dialog__actions :deep(.v-btn) { min-width: 92px; border-color: #bdc9d5; color: #4c6076; font-weight: 700; }.cleanup-confirm-button { min-width: 118px !important; margin-left: 2px; border-color: #b9633e !important; background: #b9633e !important; color: #fff !important; }

.path { overflow-wrap: anywhere; word-break: break-word; }
@media (max-width: 960px) { .summary-grid, .lower-grid { grid-template-columns: 1fr; }.metrics-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }.failure-panel { min-height: 300px; }.workspace-body { padding: 20px !important; } }
@media (max-width: 600px) { .workspace-header { min-height: auto; padding: 20px !important; }.workspace-header :deep(.v-card-item__append) { margin-left: 12px; }.refresh-button { min-width: 42px; padding-inline: 10px !important; font-size: 0; }.refresh-button :deep(.v-btn__prepend) { margin: 0; }.summary-grid { gap: 14px; }.health-card { grid-template-columns: 48px minmax(0, 1fr); padding: 22px 18px 14px 26px; }.health-mark { width: 44px; height: 44px; }.health-meta { grid-template-columns: 1fr; gap: 7px; }.metrics-grid { gap: 10px; }.metric-card { min-height: 102px; padding: 14px; }.metric-card strong { font-size: 25px; }.metric-card small { display: block; margin: 8px 0 0; }.panel-heading > div, .cleanup-files-heading > div { display: grid; gap: 4px; }.history-table th:nth-child(4), .history-table td:nth-child(4) { display: none; }.cleanup-dialog__header, .cleanup-dialog__body, .cleanup-dialog__actions { padding-inline: 20px !important; }.cleanup-summary-grid { grid-template-columns: 1fr; gap: 10px; }.cleanup-files-heading { align-items: stretch; flex-direction: column; }.cleanup-files-heading :deep(.v-input) { width: 100%; }.cleanup-dialog__actions { align-items: flex-end; flex-wrap: wrap; }.cleanup-dialog__actions > span { width: 100%; }.cleanup-dialog__actions :deep(.v-spacer) { display: none; } }
</style>
