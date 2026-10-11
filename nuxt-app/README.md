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

## 部署（生产）

### 1. 构建 + 启动

```bash
npm run build                 # → .output/（Nitro node-server 预设）
npm run start                 # = node .output/server/index.mjs，默认 3000
# 换端口：PORT=8080 npm run start
# 后端不在本机：NUXT_BACKEND_ORIGIN=http://10.0.0.5:8190 npm run build
```

实测（生产模式，3000 → 8190）：

| 项 | 结果 |
| --- | --- |
| `/api/health` `/api/jobs` `/api/models` `/api/status/*` `/api/scenes/*` `/api/characters/*` | 全 200 |
| `/output/*.mp4` | 200 `video/mp4`（支持 Range 拖动） |
| `/` `/generate` `/characters` `/settings` | SSR 全 200，Iconify 图标正常 |

### ⚠️ 部署必知：devProxy 不进产物

`nitro.devProxy` **只在 `nuxt dev` 生效**，`npm run build` 出来的产物不带它 ——
只配 devProxy 的话，生产模式启动后 `/api` 全 404（这是最容易踩的一个）。
本项目的解法是**同时配 `nitro.routeRules`**（Nitro 的 proxy handler 会打进构建产物）：

```ts
routeRules: {
  "/api/**":    { proxy: `${BACKEND}/api/**` },
  "/output/**": { proxy: `${BACKEND}/output/**` },
}
```
`routeRules` 的 `**` 会替换成匹配到的路径，**不存在 devProxy 那个剥前缀的问题**（机制不同）。

### 2. 进程守护

```bash
pm2 start .output/server/index.mjs --name luminaforge-nuxt   # 推荐
# Windows 无 pm2 时：nssm 注册为服务，或开一个常驻终端跑 npm run start
```

### 3. nginx 反代（对外发布）

见 [`deploy/nginx.conf.example`](./deploy/nginx.conf.example)。
要点三条：**`/ws/` 必须带 `Upgrade` 头**（否则进度订阅连不上）、
`proxy_read_timeout` 要放到 300s+（生成一次十几分钟）、
`/output/` 要透传 `Range`（否则 mp4 拖不动进度条）。

上了 nginx 之后，前端的 `wsBase` 改成域名：

```bash
NUXT_PUBLIC_WS_BASE=wss://your.domain.com npm run build
```

### 4. 另一种姿势：纯静态

```bash
npm run generate     # → .output/public（纯静态，无需 Node 进程）
```
把 `.output/public` 交给 nginx 直接 serve，或替换掉 `scripts/main.py` 里
`app.mount("/", web/dist)` 的 `web/dist`。适合前端纯展示、后端独立部署的场景。

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

- 整盘迁移路线见 **[`MIGRATION.md`](./MIGRATION.md)**（web/ → nuxt-app/ 的页面/store/hook/端点映射与里程碑）。
- 目标架构与后端对接见 `docs/全栈技术文档.md` §4.2。
- 现状 `web/`（React + Vite）与本目录并行，按页面逐步切换（推荐 nginx 按路由渐进切流）。
