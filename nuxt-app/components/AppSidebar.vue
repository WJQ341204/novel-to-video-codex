<template>
  <nav class="w-56 shrink-0 border-r border-neutral-800 bg-neutral-900 p-4">
    <ul class="space-y-1">
      <li v-for="item in items" :key="item.to">
        <NuxtLink
          :to="item.to"
          class="flex items-center gap-2 rounded-lg px-3 py-2 text-sm hover:bg-neutral-800"
          active-class="bg-neutral-800 text-amber-400"
        >
          <Icon :name="item.icon" class="h-4 w-4" />
          {{ item.label }}
        </NuxtLink>
      </li>
    </ul>
  </nav>
</template>

<script setup lang="ts">
const items = [
  { to: "/", label: "总览", icon: "lucide:layout-dashboard" },
  { to: "/generate", label: "生成", icon: "lucide:wand-sparkles" },
  { to: "/characters", label: "角色与配音", icon: "lucide:users" },
  { to: "/settings", label: "设置", icon: "lucide:settings" },
]
</script>
