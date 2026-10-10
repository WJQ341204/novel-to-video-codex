<template>
  <div v-if="jobId" class="rounded-lg border border-neutral-800 bg-neutral-900 p-4">
    <div class="mb-2 flex items-center gap-2 text-sm">
      <Icon name="lucide:loader-circle" class="h-4 w-4 animate-spin text-amber-400" />
      <span>任务 {{ jobId }} 进度</span>
      <span class="ml-auto tabular-nums">{{ percent }}%</span>
    </div>
    <div class="h-2 overflow-hidden rounded-full bg-neutral-800">
      <div
        class="h-full rounded-full bg-amber-400 transition-all"
        :style="{ width: `${percent}%` }"
      />
    </div>
    <p v-if="message" class="mt-2 text-sm text-neutral-400">{{ message }}</p>
  </div>
</template>

<script setup lang="ts">
const props = defineProps<{ jobId: string }>()
const { percent, message } = useJobProgress(props.jobId)
</script>
