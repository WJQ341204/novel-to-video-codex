<template>
  <div class="min-h-screen bg-neutral-950 text-neutral-100">
    <AppHeader />
    <div class="flex">
      <AppSidebar />
      <main class="flex-1 p-6">
        <slot />
      </main>
    </div>
  </div>
</template>
