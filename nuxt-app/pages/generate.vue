<template>
  <div>
    <h2 class="mb-4 flex items-center gap-2 text-base font-medium">
      <Icon name="lucide:wand-sparkles" class="h-5 w-5 text-amber-400" />
      生成
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
        class="flex items-center gap-2 rounded-lg bg-amber-400 px-4 py-2 text-sm font-medium text-neutral-900 hover:bg-amber-300 disabled:opacity-50"
        :disabled="!jobId || starting"
        @click="start"
      >
        <Icon name="lucide:play" class="h-4 w-4" /> 开始生成
      </button>
      <button
        v-if="jobId"
        class="flex items-center gap-2 rounded-lg border border-neutral-700 px-4 py-2 text-sm hover:bg-neutral-800"
        @click="loadScenes"
      >
        <Icon name="lucide:refresh-cw" class="h-4 w-4" /> 刷新分镜
      </button>
    </div>

    <JobProgress v-if="jobId" :job-id="jobId" class="mb-4" />

    <p v-if="error" class="mb-4 text-sm text-red-400">{{ error }}</p>

    <ul class="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      <li
        v-for="scene in scenes"
        :key="scene.scene_id"
        class="rounded-lg border border-neutral-800 bg-neutral-900 p-3"
      >
        <div class="mb-1 flex items-center gap-2 text-sm">
          <Icon name="lucide:image" class="h-4 w-4 text-neutral-500" />
          镜 {{ scene.scene_id }}
          <span class="ml-auto text-xs text-neutral-500">{{ scene.status || "—" }}</span>
        </div>
        <p class="line-clamp-3 text-xs text-neutral-400">{{ scene.prompt || "—" }}</p>
      </li>
    </ul>
  </div>
</template>

<script setup lang="ts">
import type { Scene } from "~/types"

const route = useRoute()
const api = useApi()

const jobId = ref<string>((route.query.job as string) || "")
const starting = ref(false)
const scenes = ref<Scene[]>([])
const error = ref("")

const start = async () => {
  starting.value = true
  error.value = ""
  try {
    await api.startGeneration(jobId.value)
  } catch (e) {
    error.value = String(e)
  } finally {
    starting.value = false
  }
}

const loadScenes = async () => {
  error.value = ""
  try {
    scenes.value = (await api.getScenes(jobId.value)) as Scene[]
  } catch (e) {
    error.value = String(e)
  }
}

onMounted(() => {
  if (jobId.value) loadScenes()
})
</script>
