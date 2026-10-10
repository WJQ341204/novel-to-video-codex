<template>
  <div>
    <h2 class="mb-4 flex items-center gap-2 text-base font-medium">
      <Icon name="lucide:users" class="h-5 w-5 text-amber-400" />
      角色与配音
    </h2>

    <div class="mb-4 flex flex-wrap items-end gap-2">
      <label class="text-sm">
        <span class="mb-1 block text-neutral-400">任务 ID</span>
        <input
          v-model="jobId"
          placeholder="输入 job_id"
          class="rounded-lg border border-neutral-800 bg-neutral-900 px-3 py-2 text-sm outline-none focus:border-amber-400"
        />
      </label>
      <button
        class="flex items-center gap-2 rounded-lg border border-neutral-700 px-4 py-2 text-sm hover:bg-neutral-800"
        :disabled="!jobId"
        @click="load"
      >
        <Icon name="lucide:search" class="h-4 w-4" /> 查询角色
      </button>
      <button
        class="flex items-center gap-2 rounded-lg border border-neutral-700 px-4 py-2 text-sm hover:bg-neutral-800"
        :disabled="!jobId || analyzing"
        @click="analyze"
      >
        <Icon name="lucide:scan-face" class="h-4 w-4" /> 分析角色
      </button>
    </div>

    <p v-if="error" class="mb-4 text-sm text-red-400">{{ error }}</p>

    <ul class="divide-y divide-neutral-800 rounded-lg border border-neutral-800">
      <li v-for="c in characters" :key="c.name" class="flex items-center gap-3 p-3 text-sm">
        <Icon name="lucide:user" class="h-4 w-4 text-neutral-500" />
        <span>{{ c.name }}</span>
        <span class="text-xs text-neutral-500">{{ c.gender || "—" }}</span>
        <span class="ml-auto flex items-center gap-1 text-xs text-neutral-400">
          <Icon name="lucide:mic" class="h-3.5 w-3.5" /> {{ c.voice_name || c.voice_id || "未配置" }}
        </span>
      </li>
      <li v-if="!characters.length" class="p-3 text-sm text-neutral-500">暂无角色数据</li>
    </ul>
  </div>
</template>

<script setup lang="ts">
import type { Character } from "~/types"

const api = useApi()
const jobId = ref("")
const characters = ref<Character[]>([])
const analyzing = ref(false)
const error = ref("")

const load = async () => {
  error.value = ""
  try {
    characters.value = (await api.getCharacters(jobId.value)) as Character[]
  } catch (e) {
    error.value = String(e)
  }
}

const analyze = async () => {
  analyzing.value = true
  error.value = ""
  try {
    await api.analyzeCharacters(jobId.value)
    await load()
  } catch (e) {
    error.value = String(e)
  } finally {
    analyzing.value = false
  }
}
</script>
