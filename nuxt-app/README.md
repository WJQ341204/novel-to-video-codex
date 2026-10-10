# LuminaForge Nuxt 前端（目标架构）

> 状态：🚧 骨架已搭建，业务功能逐步迁移中。
> 现有生产前端仍是 `web/`（React 18 + Vite 5），本目录为**迁移目标**。

## 技术栈

| 项 | 选型 |
| --- | --- |
| 运行时 | Node.js ≥ 20 |
| 框架 | Nuxt 3（Vue 3） |
| 组件 | Vue SFC，`components/` 自动导入 |
| 图标 | **Iconify**（`@nuxt/icon` + `@iconify-json/lucide`，本地集合，离线可用） |
| 样式 | Tailwind CSS（`@nuxtjs/tailwindcss`） |
| 状态 | Pinia（`@pinia/nuxt`） |
| 数据请求 | `$fetch` / `useFetch`（封装在 `composables/useApi.ts`） |

## 快速开始

```bash
cd nuxt-app
npm install
npm run dev        # http://localhost:3000
```

需先启动后端 FastAPI（8190）：仓库根执行 `python scripts/main.py`。
本机没有 Python 依赖时，可用内置 mock 顶上（见下）。

## 与后端的对接

`nuxt.config.ts` 中 `nitro.devProxy` 把以下前缀代理到 8190：

- `/api` → `http://localhost:8190/api`
- `/output` → `http://localhost:8190/output`（产物文件）

进度订阅走 **WebSocket 直连后端** `ws://localhost:8190/ws/progress/{job_id}`，
见 `composables/useWebSocket.ts` 的 `progressWsUrl()` 与 `useJobProgress.ts`。

### ⚠️ 两个实测踩到的坑（已修，改配置时别踩回去）

1. **devProxy 会剥掉前缀**：`nitro.devProxy` 底层是 h3 的 `app.use(route, handler)`，
   挂载时把 route 前缀从 `event.path` 上摘掉。若 target 写成 `http://localhost:8190`，
   后端收到的是 `/health` 而不是 `/api/health`（实测全 404）。
   ✅ 正确写法是把前缀补到 **target 的 pathname** 上，由 httpxy
   `joinURL(target.pathname, requestPath)` 拼回。
2. **devProxy 代理不了 WebSocket**：即使写了 `ws: true` 也没用 —— Nitro dev server 的
   `handleUpgrade()` 直接把 upgrade 请求交给 worker，绕过 devProxy，
   连 3000 会报 `non-101 status code`。
   ✅ 解法是 `runtimeConfig.public.wsBase` 直连后端（默认 `ws://localhost:8190`），
   生产环境用 nginx 反代 `/ws` 后设为 `wss://<域名>`。

## Mock 后端（零依赖，用于没有 Python 环境时联调）

```bash
npm run mock        # 只依赖 Node 内置模块，手写最小 RFC6455 服务端
```

它顶在 8190，提供 `/api/health`、`/api/jobs`、`/api/status/{id}`、`/api/scenes/{id}`、
`/api/characters/{id}`、`/api/models`、`/api/comfyui-models`、`/api/tts-voices`、
`POST /api/create-job`、`/output/...`（映射到仓库根 `output/`），
以及 `ws://localhost:8190/ws/progress/{job_id}`（每 500ms 推一帧，4%→100%）。

联调冒烟（后端 + `npm run dev` 都起来后）：

```bash
curl http://localhost:3000/api/health          # → {"status":"ok",...}
curl http://localhost:3000/api/jobs            # → 任务列表
curl -I http://localhost:3000/output/novel_demo_v2/xxx.mp4   # → 200 video/mp4
```

## 目录结构

```
nuxt-app/
  app.vue                  # 根组件
  nuxt.config.ts           # 模块 / 代理 / 图标集合
  assets/css/tailwind.css
  layouts/default.vue      # Header + Sidebar + 内容区
  components/              # AppHeader / AppSidebar / JobProgress（自动导入）
  pages/                   # 文件路由：index / generate / characters / settings
  composables/             # useApi / useWebSocket / useJobProgress
  types/index.ts           # Job / Scene / Character / ProgressMessage
  mock-backend.mjs         # 零依赖 mock 后端（npm run mock）
  .env.example             # NUXT_PUBLIC_API_BASE / NUXT_PUBLIC_WS_BASE
```

## 联调验证记录（2026-10-10，Nuxt 3.21.11 / Nitro 2.13.4 / Vite 7.3.7）

| 项 | 结果 |
| --- | --- |
| `npm run build` | ✅ Build complete，Σ 2.99 MB |
| Iconify 本地集合 | ✅ 21 个图标打包 6.76 KB |
| REST 经 3000 → 8190 | ✅ `/api/health` `/api/jobs` `/api/models` `/api/status/*` `/api/scenes/*` 全 200 |
| `/output` 静态代理 | ✅ 200 `video/mp4`，210,964 字节；缺失文件 404 |
| WS 进度 | ✅ 25 帧 4%→100%，stage 由「分镜解析」过渡到「出库写盘」 |
| 四个页面 SSR | ✅ `/` `/generate` `/characters` `/settings` 全 200，图标正常渲染 |

## 图标用法（Iconify）

```vue
<Icon name="lucide:film" />
<Icon name="lucide:play" class="h-4 w-4" />
```

- 集合以本地 `@iconify-json/lucide` 提供（`icon.serverBundle.collections`），**不依赖外网**
- 从旧前端 `lucide-react` 迁移时，组件名基本一一对应：`Video` → `lucide:video`

## 迁移说明

见 `docs/全栈技术文档.md` §4.2（目标架构与迁移路径）。
现状 `web/`（React + Vite）与本目录并行，按页面逐步切换。
