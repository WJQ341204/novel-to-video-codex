// Nuxt 配置：接入 Iconify（@nuxt/icon）+ Tailwind + Pinia，并代理后端 FastAPI(8190)
export default defineNuxtConfig({
  modules: ["@nuxt/icon", "@nuxtjs/tailwindcss", "@pinia/nuxt"],

  devServer: { port: 3000 },

  css: ["~/assets/css/tailwind.css"],

  runtimeConfig: {
    public: {
      // 同源走 /api（dev 下由 nitro.devProxy 代理到 8190）；也可用 NUXT_PUBLIC_API_BASE 覆盖为绝对地址
      apiBase: "/api",
      // ⚠️ WebSocket 必须直连后端：nitro.devProxy 的 ws:true 在 dev 下**不生效**
      // （Nitro dev 的 handleUpgrade 直接把 upgrade 交给 worker，绕过 devProxy），
      // 实测连 3000 会报 "non-101 status code"。生产环境请用 nginx 反代 /ws，
      // 并把这里改成 wss://<你的域名>。
      wsBase: "ws://localhost:8190",
    },
  },

  nitro: {
    // ⚠️ 坑：nitro.devProxy 走 h3 的 app.use(route, handler)，挂载时会把 route 前缀
    // 从 event.path 上剥掉；若 target 不带 pathname，后端收到的是 /health 而不是
    // /api/health（实测 404）。故把前缀补在 target 上，由 httpxy 的
    // joinURL(target.pathname, requestPath) 拼回完整路径。
    devProxy: {
      "/api": { target: "http://localhost:8190/api", changeOrigin: true },
      "/output": { target: "http://localhost:8190/output", changeOrigin: true },
      // 注意：这里**不要**配 /ws —— devProxy 处理不了 upgrade（见上方 wsBase 注释），
      // 配了也只会被当成普通 HTTP 请求代理过去，反而误导。
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
