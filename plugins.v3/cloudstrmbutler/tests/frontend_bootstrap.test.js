import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

test('frontend bootstrap registers Vuetify components and directives', async () => {
  const source = await readFile(new URL('../src/main.js', import.meta.url), 'utf8')

  assert.equal(source.includes("import * as components from 'vuetify/components'"), true)
  assert.equal(source.includes("import * as directives from 'vuetify/directives'"), true)
  assert.equal(source.includes('components,'), true)
  assert.equal(source.includes('directives,'), true)
})

test('dashboard exposes manual command progress and result categories', async () => {
  const source = await readFile(new URL('../src/Page.vue', import.meta.url), 'utf8')

  assert.equal(source.includes('command_progress'), true)
  assert.equal(source.includes('当前文件'), true)
  assert.equal(source.includes('生成 STRM'), true)
  assert.equal(source.includes('复制字幕'), true)
  assert.equal(source.includes('已有内容跳过'), true)
})

test('dashboard exposes the additive overview and one-shot full scan action', async () => {
  const source = await readFile(new URL('../src/Page.vue', import.meta.url), 'utf8')

  assert.equal(source.includes('processing_overview'), true)
  assert.equal(source.includes('sync_full_scan'), true)
  assert.equal(source.includes('full-scan'), true)
  assert.equal(source.includes('media_total'), true)
  assert.equal(source.includes('non_media_completed'), true)
  assert.equal(source.includes('subtitle_completed'), true)
  assert.equal(source.includes('recent-task-table'), true)
})

test('recent task table has only the four requested columns', async () => {
  const source = await readFile(new URL('../src/Page.vue', import.meta.url), 'utf8')

  assert.equal(source.includes('recent-task-table'), true)
  assert.equal(source.includes('task-started-at'), false)
  assert.equal(source.includes('task-unchanged'), false)
  assert.equal(source.includes('task-skipped'), false)
  assert.equal(source.includes('task-failed'), false)
})

test('dashboard keeps intervention UI compact and diagnostics collapsed by default', async () => {
  const source = await readFile(new URL('../src/Page.vue', import.meta.url), 'utf8')

  assert.equal(source.includes('需要处理的失败'), true)
  assert.equal(source.includes('近期任务'), true)
  assert.equal(source.includes('高级诊断'), true)
  assert.equal(source.includes('<details class="diagnostics-section">'), true)
  assert.equal(source.includes('同步任务中心'), false)
})

test('config keeps the durable queue enabled for new settings', async () => {
  const source = await readFile(new URL('../src/Config.vue', import.meta.url), 'utf8')

  assert.equal(source.includes('reliable_engine: true'), true)
  assert.equal(source.includes('normalizeBoolean(ic.reliable_engine, true)'), true)
})
