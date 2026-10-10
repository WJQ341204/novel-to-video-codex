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

## 与后端的对接

`nuxt.config.ts` 中 `nitro.devProxy` 把以下前缀代理到 8190：

- `/api` → `http://localhost:8190`
- `/ws` → `ws://localhost:8190`（WebSocket 进度）
- `/output` → `http://localhost:8190`（产物文件）

进度订阅：`ws://<host>/ws/progress/{job_id}`，见 `composables/useJobProgress.ts`。

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
```

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
