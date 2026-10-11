// Nuxt 配置：接入 Iconify（@nuxt/icon）+ Tailwind + Pinia，并代理后端 FastAPI(8190)
//
// 后端地址：构建期由 NUXT_BACKEND_ORIGIN 决定（默认 http://localhost:8190）。
// 例：NUXT_BACKEND_ORIGIN=http://10.0.0.5:8190 npm run build
const BACKEND = process.env.NUXT_BACKEND_ORIGIN || "http://localhost:8190"

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
      "/api": { target: `${BACKEND}/api`, changeOrigin: true },
      "/output": { target: `${BACKEND}/output`, changeOrigin: true },
      // 注意：这里**不要**配 /ws —— devProxy 处理不了 upgrade（见上方 wsBase 注释），
      // 配了也只会被当成普通 HTTP 请求代理过去，反而误导。
    },

    // ⚠️ 更要命的坑：devProxy **只在 nuxt dev 生效**，npm run build 出来的产物不带它，
    // 生产模式下 /api 会全 404。生产代理必须走 routeRules（Nitro 的 proxy handler 会
    // 打进构建产物）。这里的 ** 会被替换成匹配到的路径，所以不存在剥前缀问题。
    routeRules: {
      "/api/**": { proxy: `${BACKEND}/api/**` },
      "/output/**": { proxy: `${BACKEND}/output/**` },
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
