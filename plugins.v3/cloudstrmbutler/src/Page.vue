<template>
  <v-card>
    <v-card-item>
      <v-card-title>云盘Strm小管家 - 任务状态</v-card-title>
      <template #append>
        <v-btn icon variant="text" @click="emit('close')">
          <v-icon>mdi-close</v-icon>
        </v-btn>
      </template>
    </v-card-item>
    <v-divider />
    <v-card-text>
      <v-alert type="info" variant="tonal">
        插件已{{ enabled ? '启用' : '未启用' }}。配置完成后可在"目录配置"中查看和管理映射规则。
      </v-alert>
    </v-card-text>
    <v-card-actions>
      <v-spacer />
      <v-btn color="primary" variant="tonal" prepend-icon="mdi-cog" @click="emit('switch')">
        前往配置
      </v-btn>
    </v-card-actions>
  </v-card>
</template>

<script setup>
defineProps({
  initialConfig: { type: Object, default: () => ({}) },
  api: { type: Object, default: () => {} },
})

const emit = defineEmits(['close', 'switch'])
</script>
