<template>
  <div>
    <h2 class="mb-4 flex items-center gap-2 text-base font-medium">
      <Icon name="lucide:settings" class="h-5 w-5 text-amber-400" />
      设置
    </h2>

    <div class="mb-6 rounded-lg border border-neutral-800 bg-neutral-900 p-4">
      <div class="mb-2 flex items-center gap-2 text-sm text-neutral-400">
        <Icon name="lucide:link" class="h-4 w-4" /> 后端接口基址
      </div>
      <p class="font-mono text-sm">{{ apiBase }}</p>
    </div>

    <h3 class="mb-2 text-sm text-neutral-400">可用模型</h3>
    <ul class="divide-y divide-neutral-800 rounded-lg border border-neutral-800">
      <li v-for="m in models" :key="String(m)" class="flex items-center gap-2 p-3 text-sm">
        <Icon name="lucide:box" class="h-4 w-4 text-neutral-500" />
        <span class="truncate font-mono">{{ String(m) }}</span>
      </li>
      <li v-if="!models.length" class="p-3 text-sm text-neutral-500">未能获取模型列表（后端未启动？）</li>
    </ul>

    <h3 class="mb-2 mt-6 text-sm text-neutral-400">ComfyUI 模型</h3>
    <ul class="divide-y divide-neutral-800 rounded-lg border border-neutral-800">
      <li v-for="m in comfyModels" :key="String(m)" class="flex items-center gap-2 p-3 text-sm">
        <Icon name="lucide:boxes" class="h-4 w-4 text-neutral-500" />
        <span class="truncate font-mono">{{ String(m) }}</span>
      </li>
      <li v-if="!comfyModels.length" class="p-3 text-sm text-neutral-500">暂无</li>
    </ul>
  </div>
</template>

<script setup lang="ts">
const api = useApi()
const { apiBase } = useRuntimeConfig().public
const models = ref<unknown[]>([])
const comfyModels = ref<unknown[]>([])

onMounted(async () => {
  try {
    const r = (await api.getModels()) as unknown
    models.value = Array.isArray(r) ? r : []
  } catch {
    models.value = []
  }
  try {
    const r = (await api.getComfyuiModels()) as unknown
    comfyModels.value = Array.isArray(r) ? r : Object.values(r ?? {})
  } catch {
    comfyModels.value = []
  }
})
</script>
