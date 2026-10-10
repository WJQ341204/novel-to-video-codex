<template>
  <header
    class="flex items-center gap-3 border-b border-neutral-800 bg-neutral-900 px-6 py-4"
  >
    <Icon name="lucide:clapperboard" class="h-6 w-6 text-amber-400" />
    <h1 class="text-lg font-medium">墨影流光 · LuminaForge</h1>
    <span class="ml-auto text-sm text-neutral-400">
      后端 {{ apiBase }}
    </span>
  </header>
</template>

<script setup lang="ts">
const { apiBase } = useRuntimeConfig().public
</script>
