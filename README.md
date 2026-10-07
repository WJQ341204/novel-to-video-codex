# 墨影流光 / LuminaForge — 小说转视频 AI 管线

> **v12.3** · 把小说文本自动转成竖屏短视频：AI 分镜 → 关键帧 → 图生视频 → 情绪配音 → 字幕/BGM → 成片。

![status](https://img.shields.io/badge/TTS-%E9%98%B6%E8%B7%83%E6%98%9F%E8%BE%B0-green) ![status](https://img.shields.io/badge/%E8%A7%86%E9%A2%91-Wan2.2%20A14B-blue) ![license](https://img.shields.io/badge/license-MIT-lightgrey)

**文档导航**：[部署与出片手册](README_本机部署.md) · [**问题复盘与故障档案（21 个坑的根因与解法）**](README_问题复盘.md) · [故障速查](docs/TROUBLESHOOTING.md) · [更新日志](CHANGELOG.md) · [**优化方案（8 类）**](docs/OPTIMIZATION.md) · [架构](docs/ARCHITECTURE.md) · [管线](docs/PIPELINE.md)

---

## 一、它能做什么

输入一段小说文本，输出一条带**情绪配音 + 精确字幕 + 背景音乐**的竖屏视频：

| 环节 | 实现 |
|---|---|
| AI 分镜 | DeepSeek 拆解场景、生成画面描述与台词 |
| 关键帧 | ComfyUI SDXL / PULID 角色一致性出图 |
| 图生视频 | **Wan 2.2 A14B（wan5b 两段式引擎）**：采样+解码 → RIFE 补帧 → 2x 超分 |
| 配音 | **阶跃星辰 StepFun（默认）** / CosyVoice2（本地）/ Edge-TTS（兜底） |
| 情绪 | 21 种场景情绪自动转配音指导，强度 1-10 可调 |
| 后期 | 精确字幕、BGM 混音、转场、快进/快退、成片合并 |

**实测**：12 场景成片 68 秒 / 1408×2560@48fps；单场景全链路约 12-17 分钟（RTX 5070 8GB，低显存模式）。

---

## 二、快速开始（Windows 本机）

### 环境要求

- Python 3.11+（推荐 3.13）· Node.js 18+（仅前端构建需要）
- NVIDIA GPU 8GB+（Wan A14B 需低显存模式）
- FFmpeg 6+（加入 PATH）
- ComfyUI（端口 8188）· 可选 CosyVoice2（端口 50000）

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 启动 ComfyUI（**必须低显存**）

```bat
python "<ComfyUI目录>\main.py" --lowvram --async-offload 2 --port 8188 --listen 127.0.0.1
```

> 不加 `--lowvram` 会 OOM 崩进程。

### 3. 配置 `.env`

```bash
cp .env.example .env
```

必填 `DEEPSEEK_API_KEY`（AI 分镜）。**阶跃星辰配音**另需填 `STEPFUN_API_KEY`（见下文）。

### 4. 启动应用

双击 `start_app.bat` → 浏览器打开 **http://127.0.0.1:8190**，或运行 `dist/LuminaForge.exe`（桌面版，免安装 Python）。

前端开发模式：`cd web && npm install && npm run dev`

---

## 三、配音引擎（v12.3 重点）

引擎按优先级自动选择，**任何引擎失败都会自动降级，出片不会中断**：

```
stepfun（配了 Key） → cosyvoice（本地已启动） → edge（免费兜底）
```

可用 `TTS_ENGINE=stepfun|cosyvoice|edge` 强制指定。

### 阶跃星辰 StepFun（推荐）

1. 到 https://platform.stepfun.com 注册并创建 API Key
2. 填入 `.env` 的 `STEPFUN_API_KEY=`
3. **Step Plan 订阅 Key 必须再设** `STEPFUN_BASE_URL=https://api.stepfun.com/step_plan/v1`
   （按量计费 Key 注释掉这行。搞错会报 `402 exceeded quota`）

能力：

- 21 种场景情绪自动转为情绪指导（紧张/悲伤/热血/神秘…），强度 1-10 控制浓淡
- 旁白/对白差异化，旁白自动附加「沉稳电影旁白」风格
- 语速 `+8%` → speed 1.08；音量 `+20%` → volume 1.2
- Edge 音色自动映射官方音色（晓晓→邻家姐姐、云健→磁性男声…）
- UI 音色列表内含 32 个阶跃官方音色，可直接选
- 长文本（>900 字）自动按句分段合成后拼接

自检：`python test_stepfun_tts.py --dry`（逻辑验证）/ `python test_stepfun_tts.py`（真实合成，耗额度）

---

## 四、环境变量

| 变量 | 默认值 | 说明 |
|---|---|---|
| `DEEPSEEK_API_KEY` | - | AI 分镜分析（必填） |
| `COMFYUI_URL` | `http://127.0.0.1:8188` | ComfyUI 地址 |
| `COMFYUI_MODELS_DIR` | 空 | 模型目录，如 `D:/ComfyUI/models` |
| `COMFYUI_PATH` | 空 | ComfyUI 根目录（用于定位自带 ffmpeg） |
| `STEPFUN_API_KEY` | 空 | 阶跃星辰 Key，填写后自动成为默认配音引擎 |
| `STEPFUN_BASE_URL` | `https://api.stepfun.com/v1` | **Step Plan 订阅 Key 改成 `https://api.stepfun.com/step_plan/v1`** |
| `STEPFUN_TTS_MODEL` | `stepaudio-2.5-tts` | 可选 `step-tts-2` / `step-tts-mini`（轻量但不支持情绪指导） |
| `TTS_ENGINE` | 空（自动） | 强制 `stepfun` / `cosyvoice` / `edge` |

> ⚠️ `.env` 已在 `.gitignore` 中，**切勿提交密钥**。

---

## 五、项目结构

```
novel-to-video-codex/
├── scripts/main.py          # FastAPI 主应用（分镜/生成/TTS/后期全流程）
├── scripts/launcher.py      # PyInstaller 桌面启动器
├── app/                     # 配置、数据模型、ComfyUI 客户端
├── engines/                 # 视频引擎（wan5b 两段式、ltx、cloud 等）
├── config/settings.py       # YAML 配置（需 PyYAML）
├── quality/ scheduler/ pipeline/ post/   # 质量门、队列、流水线、后期合成
├── web/                     # React + Vite + TypeScript 前端
├── story2/                  # 独立脚本管线（不走桌面应用）
├── comfyui/                 # ComfyUI 工作流模板 + 启动脚本
├── cosyvoice2/              # CosyVoice2 本地 TTS 集成
├── dist/LuminaForge.exe     # 打包好的桌面版（免安装运行）
├── docs/                    # 文档（架构/搭建/管线/踩坑）
└── README_本机部署.md        # 本机实战部署指南（含实测性能与 FAQ）
```

详细文档：[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) · [`docs/SETUP.md`](docs/SETUP.md) · [`docs/PIPELINE_USE.md`](docs/PIPELINE_USE.md) · [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md)

---

## 六、技术栈

- **后端**：FastAPI + uvicorn + httpx + websockets
- **前端**：React 18 + TypeScript + Vite + Tailwind + Zustand
- **视频**：ComfyUI + Wan 2.2 A14B（I2V）· RIFE 补帧 · 2x 超分
- **配音**：阶跃星辰 StepFun / CosyVoice2 / Edge-TTS
- **后期**：FFmpeg（ASS 字幕烧录 + BGM 混音 + concat）
- **打包**：PyInstaller（onefile exe，便携数据存 exe 同级目录）

---

## 七、常见问题

见 [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md)，高频问题速查：

| 症状 | 原因 |
|---|---|
| StepFun `402 exceeded quota` | Step Plan Key 走错端点，设 `STEPFUN_BASE_URL` |
| StepFun `401 invalid_api_key` | Key 填错/过期（已自动回退 Edge，出片不中断） |
| 进程莫名退出、日志有 SystemExit | safe-delete 钩子，启动脚本需 `CODEBUDDY_SAFE_DELETE_ENABLED=0` |
| httpx 报 `[Errno 22]` | 系统代理残留（Clash 未开），`set HTTP_PROXY=` 清空 |
| T5 报 `fp8 scaled is not supported` | text_encoders 放的是 Comfy-Org repackaged 版，换 Kijai 版 |

---

## 八、许可证

MIT — 详见 [`LICENSE`](LICENSE)。

---

## 附：成片与演示（films/）

本仓库同时收录已生成的成片（渲染中间产物仍在 `output/`，被 `.gitignore` 排除，不进仓）。

三部短剧，每部含 4 个版本（带字幕 / 无字幕 / 配音版 / 无字幕配音版）：

| 片名 | 镜号段 | 文件前缀 |
| --- | --- | --- |
| 《雨夜药铺》 | 1/4/8/12 | `青囊异闻录_雨夜药铺` |
| 《残篇授书》 | 201/202 | `青囊异闻录_残篇授书` |
| 《铃兰令》 | 301/302 | `青囊异闻录_铃兰令` |

`films/` 另含各分镜首/尾帧 PNG 与三张演示页（`演示_新能力对比.html`、`成片预览.html`、`项目图文说明.html`），用浏览器直接打开即可预览（页面用相对路径引用同目录素材）。

成片名由镜号段自动推导：`id<200`=《雨夜药铺》、`200–299`=《残篇授书》、`300–399`=《铃兰令》；跨号段导出为「选段_NNN-NNN」。
