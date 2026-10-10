<template>
  <div>
    <h2 class="mb-4 flex items-center gap-2 text-base font-medium">
      <Icon name="lucide:layout-dashboard" class="h-5 w-5 text-amber-400" />
      总览
    </h2>

    <div class="mb-6 grid gap-4 sm:grid-cols-3">
      <div class="rounded-lg border border-neutral-800 bg-neutral-900 p-4">
        <div class="flex items-center gap-2 text-sm text-neutral-400">
          <Icon name="lucide:film" class="h-4 w-4" /> 任务总数
        </div>
        <p class="mt-1 text-2xl tabular-nums">{{ jobs.length }}</p>
      </div>
      <div class="rounded-lg border border-neutral-800 bg-neutral-900 p-4">
        <div class="flex items-center gap-2 text-sm text-neutral-400">
          <Icon name="lucide:cpu" class="h-4 w-4" /> 可用模型
        </div>
        <p class="mt-1 text-2xl tabular-nums">{{ modelCount }}</p>
      </div>
      <div class="rounded-lg border border-neutral-800 bg-neutral-900 p-4">
        <div class="flex items-center gap-2 text-sm text-neutral-400">
          <Icon name="lucide:server" class="h-4 w-4" /> 后端
        </div>
        <p class="mt-1 text-sm">{{ apiBase }}</p>
      </div>
    </div>

    <h3 class="mb-2 text-sm text-neutral-400">最近任务</h3>
    <ul class="divide-y divide-neutral-800 rounded-lg border border-neutral-800">
      <li v-for="job in jobs" :key="job.job_id" class="flex items-center gap-3 p-3">
        <Icon name="lucide:file-text" class="h-4 w-4 text-neutral-500" />
        <span class="truncate">{{ job.title || job.job_id }}</span>
        <span class="ml-auto text-xs text-neutral-500">{{ job.status || "—" }}</span>
        <NuxtLink :to="`/generate?job=${job.job_id}`" class="text-xs text-amber-400 hover:underline">
          查看
        </NuxtLink>
      </li>
      <li v-if="!jobs.length" class="p-3 text-sm text-neutral-500">暂无任务</li>
    </ul>
  </div>
</template>

<script setup lang="ts">
import type { Job } from "~/types"

const api = useApi()
const { apiBase } = useRuntimeConfig().public
const jobs = ref<Job[]>([])
const modelCount = ref(0)

onMounted(async () => {
  try {
    jobs.value = (await api.listJobs()) as Job[]
  } catch {
    jobs.value = []
  }
  try {
    const models = (await api.getModels()) as unknown[]
    modelCount.value = Array.isArray(models) ? models.length : 0
  } catch {
    modelCount.value = 0
  }
})
</script>
