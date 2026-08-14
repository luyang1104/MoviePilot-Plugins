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
