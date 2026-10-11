# Nuxt 前端迁移计划（web/ → nuxt-app/）

> 状态：🚧 计划。骨架已搭好并跑通（`npm run dev` / `npm run build` 已验证），本文件是**把生产前端
> `web/`（React）整盘搬到 `nuxt-app/`（Nuxt 3）的落地路线**。
>
> 先决事实（已核对）：
> - 生产前端 `web/`：React 18 + Vite 5 + TS 5.5 + Tailwind 3.4 + **Zustand** + **react-query** + **lucide-react**，
>   路由用 react-router-dom，被 `scripts/main.py` 的 `app.mount("/", web/dist)` 顺手托管在 8190。
> - `nuxt-app/`：Nuxt 3 + Vue 3 + TS + **Iconify(`lucide:`)** + Tailwind + **Pinia**，通信层
>   `composables/useApi` / `useWebSocket` / `useJobProgress` 已就绪并联调通过。
> - 联调已踩坑并记录：`nitro.devProxy` 剥前缀（已修）、WS 代理不了（已用 `wsBase` 直连兜底）。

---

## 0. 迁移总览（一张表看清落点）

| `web/` 资产 | 行数 | `nuxt-app/` 落点 | 现状 |
| --- | --- | --- | --- |
| `pages/Dashboard.tsx` | 291 | `pages/index.vue`（总览） | ✅ 已有骨架，待补 job 列表细节 |
| `pages/CreateProject.tsx` | 554 | `pages/create.vue` | 🚧 新建 |
| `pages/StoryboardEditor.tsx` | 611 | `pages/storyboard.vue` | 🚧 新建（最大块） |
| `pages/ScenePreview.tsx` | 213 | `pages/storyboard.vue` 内 / `pages/scene/[id].vue` | 🚧 新建 |
| `pages/CharacterPanel.tsx` | 266 | `pages/characters.vue` | ✅ 已有骨架，待补声线/QA |
| `pages/TaskManager.tsx` | 301 | `pages/tasks.vue` | 🚧 新建 |
| `pages/Settings.tsx` | 431 | `pages/settings.vue` | ✅ 已有骨架，待补完整表单 |
| `stores/jobStore.ts` | 56 | `stores/job.ts` | 🚧 新建 Pinia |
| `stores/projectStore.ts` | 55 | `stores/project.ts` | 🚧 新建 Pinia |
| `stores/settingsStore.ts` | 137 | `stores/settings.ts` | 🚧 新建 Pinia |
| `stores/toastStore.ts` | 33 | `stores/toast.ts` + `components/ToastHost.vue` | 🚧 新建 |
| `hooks/useApi.ts` | 253 | `composables/useApi.ts`（合并 `lib/api.ts`） | 🔶 已有，需补 ~25 端点 |
| `hooks/useJobProgress.ts` | 52 | `composables/useJobProgress.ts` | ✅ 已有 |
| `hooks/useWebSocket.ts` | 62 | `composables/useWebSocket.ts`（含 `progressWsUrl`） | ✅ 已有 |
| `hooks/useModelList.ts` | 35 | 并入 `useApi.getModels()` | ✅ 无需单独 |
| `hooks/useCharacterVoice.ts` | 57 | `composables/useCharacterVoice.ts` | 🚧 新建 |
| `hooks/useComfyUI.ts` | 25 | 并入 `useApi`（comfyui-check/queue/models） | ✅ 无需单独 |
| `hooks/useKeyboardShortcuts.ts` | 30 | `composables/useHotkeys.ts` 或 Nuxt 插件 | 🚧 新建 |
| `lib/api.ts` | 452 | 并入 `composables/useApi.ts` | 🔶 合并 |
| `lib/types.ts` | 281 | `types/index.ts` | 🔶 已有，需补全 |
| `lib/utils.ts` | 48 | `utils/index.ts` 或 composable | 🚧 新建 |
| `lib/ws.ts` | 116 | 并入 `composables/useWebSocket.ts` | 🔶 合并 |
| `layout/AppLayout/Header/Sidebar` | 238 | `layouts/default.vue` + `AppHeader`/`AppSidebar` | ✅ 已有 |
| `components/ErrorBoundary.tsx` | 110 | `app.vue` 的 `onErrorCaptured` + `error.vue` | 🚧 新建 |
| `components/ToastContainer.tsx` | 40 | `components/ToastHost.vue` | 🚧 新建 |

**工作量粗估**：`web/` 共 ~4747 行 TS，扣除已就绪的通信层/布局，净迁移约 **4000 行**，
按页面 + store + 端点分批，建议 5 个里程碑（见 §6）。

---

## 1. 架构映射（一一对应，照着换）

| React 概念 | Nuxt/Vue 对应 | 注意 |
| --- | --- | --- |
| `react-router-dom` 路由 | **文件路由** `pages/*.vue` | `pages/storyboard.vue` ↔ `/storyboard`；动态路由 `pages/scene/[id].vue` |
| `<NavLink to>` | `<NuxtLink to>` | Sidebar 里把 `NavLink` 全换成 `NuxtLink` |
| `useNavigate()` | `navigate` / `useRouter().push()` | — |
| `useParams()` | `useRoute().params` | — |
| **Zustand** store | **Pinia** store（`defineStore`） | 写法接近：`const s = useJobStore()` |
| **react-query** (`useQuery/useMutation`) | `useAsyncData` / `useFetch` / 自管 `ref`+`composable` | 简单读用 `useAsyncData`；命令用 `useMutation` 等价写法（Nuxt 无内置，用 async 函数 + `ref` 状态封装） |
| `lucide-react` `<Video/>` | `<Icon name="lucide:video" />` | 名字一一对应：`Video`→`lucide:video`，见下 |
| `ErrorBoundary` | `app.vue` 内 `onErrorCaptured` + `error.vue` | Nuxt 有全局错误页 |
| `react-hot-toast` / 自写 Toast | `stores/toast.ts` + `ToastHost.vue` | — |
| `import.meta.env` | `useRuntimeConfig().public` | 密钥走 `NUXT_PUBLIC_*` |
| `Vite` 代理（`vite.config` server.proxy） | `nitro.devProxy` | ⚠️ 见 §5 坑 |

### 图标迁移（lucide-react → Iconify）
组件名基本同形，仅改写法：
```tsx
// React
import { Video, Play, RefreshCw } from "lucide-react"
<Video className="h-4 w-4" />
```
```vue
<!-- Nuxt（本地 @iconify-json/lucide 集合，离线可用） -->
<Icon name="lucide:video" class="h-4 w-4" />
<Icon name="lucide:play" class="h-4 w-4" />
<Icon name="lucide:refresh-cw" class="h-4 w-4" />
```
> 全量对照：https://icon-sets.iconify.design/lucide/ （`lucide:` 前缀即 lucide-react 同名字典）

---

## 2. 通信层补全（最关键，先做完再搬页面）

`composables/useApi.ts` 目前覆盖约 **17** 个端点，而 `web/lib/api.ts` 用了约 **50** 个。
**缺口清单**（需补进 `useApi`）：

```
健康检查/环境：  comfyuiCheck  ffmpegCheck  comfyuiQueue
任务管理：        jobExport  jobImport  jobArchive  archivedJobs  archivedRestore
                 jobDelete(DELETE /api/job/{id})  runPipeline  autoPipeline
分镜：            sceneRetry(/api/scene/{j}/{s}/retry)  sceneSkip  scenesReorder
                 sceneDebugPrompts  sceneError  scenesExportPrompts  testScene
                 regenerateImages  sceneBatchEdit(若用)
成片/合成：       mergeVideos  remerge
角色/配音：        characters(jobId)  analyzeCharacters  updateCharacterVoice
                 splitDialogues  updateSmartDubbing  previewTts  uploadPulidRef
提示词：          generatePrompts  generateStoryboard  debugPrompts
BGM：             bgmList  bgmUpload
QA 自测：         qaTest  qaFix  qaSettings
上传：            uploadText(已有)  uploadNovel(已有)  uploadPulidRef
其他：            updateSettings(已有)  launcherConfig(get/set)
```

> 建议：把 `web/lib/api.ts` 的 `request<T>` 封装原样搬进 `useApi`（`$fetch` 已等价），
> 逐个端点翻译，**类型从 `web/lib/types.ts` 迁到 `nuxt-app/types/index.ts`**（目前仅 Job/Scene/Character/ProgressMessage，缺 HealthStatus / ComfyUIStatus / JobState / Character / TTSVoice / BGMItem 等）。

WebSocket：✅ 已有 `progressWsUrl()`（走 `wsBase` 直连 8190），`useJobProgress.ts` 已解析
`progress/percent/stage/message`，直接复用，无需重写。

---

## 3. 状态层（Zustand → Pinia）

每个 Zustand store 1:1 翻成 Pinia（`stores/*.ts`，已在 `nuxt.config.ts` 挂 `@pinia/nuxt`）：
```ts
// stores/job.ts
export const useJobStore = defineStore("job", () => {
  const jobs = ref<JobSummary[]>([])
  const current = ref<JobState | null>(null)
  async function load() { jobs.value = (await useApi().listJobs()).jobs }
  return { jobs, current, load }
})
```
- `toastStore` → `stores/toast.ts` + `components/ToastHost.vue`（`AppLayout` 里挂一次）。
- `settingsStore` 里若有 localStorage 持久化，改用 `useLocalStorage` 或 Pinia `persist` 插件。

---

## 4. 页面逐个搬（含要点）

1. **`index.vue`（总览/Dashboard）**：补 job 卡片字段（状态色、进度条、操作菜单：导出/归档/删除）。
2. **`create.vue`（CreateProject, 554 行，最大块之一）**：文本/小说上传、参数选择（引擎/风格/质量）、一键 `/api/generate` 或分步建 job。表单 + 拖拽上传（`<input type=file>` + `FormData`）。
3. **`storyboard.vue`（StoryboardEditor, 611 行，最大块）**：分镜时间轴、逐镜编辑（prompt/角色/运镜）、`scenesReorder`、`sceneRetry/Skip`、`regenerateImages`、`scenesExportPrompts`。可内嵌 `ScenePreview` 作为镜详情抽屉。
4. **`scene/[id].vue`**：单镜大图预览 + 首/尾帧 + 视频回放（`<video>` 走 `/output/...`）。
5. **`characters.vue`（CharacterPanel）**：角色卡、声线下拉（`getTtsVoices`）、`analyzeCharacters`、`updateCharacterVoice`、试听 `previewTts`。
6. **`tasks.vue`（TaskManager）**：任务队列、进度订阅（`useJobProgress` + WS）、取消/重试、QA 自测入口（qaTest/qaFix）。
7. **`settings.vue`（Settings）**：完整设置表单（`getComfyuiModels`/`models`、`updateSettings`、`launcherConfig`、BGM 管理 `bgmList/bgmUpload`）。

---

## 5. 部署切换（上线那一步）

**开发**：`npm run dev`（3000），`nitro.devProxy` 把 `/api`、`/output` → 8190；
WS 经 `wsBase`（默认 `ws://localhost:8190`）直连。
> ⚠️ 已知坑：`devProxy` 会剥前缀（target 写成 `http://localhost:8190/api` 才对）、
> 且代理不了 WS（必须用 `wsBase`）——已在 `nuxt.config.ts` 处理，别改回去。

**生产两种姿势**（二选一，推荐 A）：

- **A. 独立 Node 服务 + nginx 反代**（最干净）
  ```bash
  npm run build
  node .output/server/index.mjs   # 监听 3000
  ```
  nginx：`/api`、`/output`、`/ws`（升级透传）反代到 8190；`/` 反代到 3000。
- **B. 静态站 + 后端托管**（贴近现在的 web/ 模式）
  ```bash
  npm run generate      # 纯静态 .output/public
  ```
  把 `.output/public` 交给 FastAPI `app.mount("/", ...)` 替换 `web/dist`，
  或 nginx 直接 serve 静态 + 反代 `/api /output /ws`。

**渐进式切流（推荐，零风险）**：nginx 按路由把 `/new/*` 指到 Nuxt（3000），
其余仍走 React（8190 的 web/dist），逐页迁移、逐页切，全量后再整体换挂载点。
回滚只需改 nginx upstream，不动代码。

---

## 6. 里程碑拆分

| 阶段 | 交付 | 验证 |
| --- | --- | --- |
| **M1 通信层** | `useApi` 补 ~25 端点 + `types/index.ts` 补全；`useCharacterVoice`/`useComfyUI` 等 hook 到位 | 用 `npm run mock` + `npm run dev` 逐个端点 curl 200 |
| **M2 状态层** | 4 个 Pinia store + ToastHost | 页面内状态联动 |
| **M3 轻页面** | `index`/`settings`/`characters` 功能补全 | 页面渲染 + 读写设置 |
| **M4 重页面** | `create`/`storyboard`(+scene)/`tasks` | 走通「建任务→分镜→生成→进度→成片」全链路 |
| **M5 收尾部署** | ErrorBoundary→`error.vue`、快捷键插件、nginx 配置、README+MIGRATION 并入根 README | `npm run build` + 生产冒烟 + 渐进切流 |

> 依赖顺序：M1 → M2 → M3/M4（页面并行）→ M5。M1 不完成，页面没法联调。

---

## 7. 风险与回滚

- **端点漂移**：后端 `scripts/main.py` 是单一事实源，搬之前用 `grep "^@app\." scripts/main.py`
  核对端点真实存在（README 曾把 `/api/model-list` 写错，实际是 `/api/models`）。
- **WS 在 dev 下不可用**：别在开发期依赖 3000 的 `/ws`，进度订阅走 `wsBase`。
- **faststart**：成片 mp4 必须 faststart 才能浏览器边下边播——这是后端职责，前端只管 `<video>`。
- **回滚**：Nuxt 是独立端口/目录，最坏情况把 nginx upstream 指回 8190 的 web/dist 即可，
  不影响生产；代码分仓 `nuxt-app/`，不碰 `web/` 直到全量切换。

---

## 8. 完成判据

- [ ] `npm run build` 通过，`npm run dev` 全页面 SSR 200
- [ ] 50 个端点全部可在 `useApi` 调用且 mock/真后端返回 200
- [ ] 走通「建任务 → 分镜编辑 → 启动生成 → WS 进度 → 成片预览」闭环
- [ ] nginx 渐进切流验证；html 预览面板打开成片 `video` 正常
- [ ] 根 `README.md`「五/六」补 `nuxt-app/` 与 `docs/全栈技术文档.md` / 本文件链接
