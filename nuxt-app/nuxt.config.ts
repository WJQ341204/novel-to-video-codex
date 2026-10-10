// Nuxt 配置：接入 Iconify（@nuxt/icon）+ Tailwind + Pinia，并代理后端 FastAPI(8190)
export default defineNuxtConfig({
  modules: ["@nuxt/icon", "@nuxtjs/tailwindcss", "@pinia/nuxt"],

  devServer: { port: 3000 },

  css: ["~/assets/css/tailwind.css"],

  runtimeConfig: {
    public: {
      // 同源走 /api（由 nitro.devProxy 代理到 8190）；也可在 .env 覆盖为绝对地址
      apiBase: "/api",
    },
  },

  nitro: {
    devProxy: {
      "/api": { target: "http://localhost:8190", changeOrigin: true },
      "/ws": { target: "ws://localhost:8190", ws: true },
      "/output": { target: "http://localhost:8190", changeOrigin: true },
    },
  },

  icon: {
    // 指定本地图标集合，避免运行时依赖 Iconify 公共 API（内网/离线可用）
    serverBundle: {
      collections: ["lucide"],
    },
    clientBundle: {
      scan: true,
      includeCustomCollections: true,
    },
  },

  typescript: {
    strict: true,
  },
})
