# LuminaForge / novel-to-video-codex — 比赛交付说明

小说到视频自动生成系统。输入小说文本，经分镜编排、关键帧生成、图生视频、
配音与后期合成，输出竖屏短剧成片。

## 快速开始

```bash
# 1. 依赖
pip install -r requirements.txt

# 2. 配置密钥
cp .env.example .env
# 编辑 .env，填入 DEEPSEEK_API_KEY（分镜必需）及可选云端服务密钥

# 3. 启动本地 ComfyUI（8188 端口，需自行准备模型与自定义节点）
#    参考 README_本机部署.md / docs/H3_COMFYUI_DEPLOY.md

# 4. 启动主应用
python scripts/main.py          # 或 Windows 下运行 start_app.bat
#    访问 http://127.0.0.1:8190
```

FFmpeg / ffprobe 需加入 PATH（或设置 `FFMPEG_DIR` 环境变量）。
所有脚本均已改为从 PATH 或当前解释器自动查找，不含任何本机绝对路径。

## 目录结构

| 目录 | 说明 |
| --- | --- |
| `scripts/main.py` | 主应用（FastAPI，端口 8190）与全流程编排 |
| `scripts/video_engine.py` | 视频引擎统一调度（Agnes / Wan5B / A14B / LTX） |
| `engines/` | 各生成引擎封装（云端 Agnes、本地 Wan、质量门等） |
| `comfyui/` | ComfyUI 工作流 JSON 模板 |
| `app/` `web/` `nuxt-app/` | 前端与数据模型 |
| `pipeline/` `post/` `quality/` | 流水线、后期处理、质量评估 |
| `docs/` `技术文档.md` | 部署文档、架构说明与历次修复记录 |
| `config/` `settings.yaml` | 运行配置 |

## 环境要求

- Python 3.11+（推荐 3.13）
- FFmpeg（含 ffprobe）
- 本地 ComfyUI，需安装 WanVideoWrapper / GGUF / VideoHelperSuite /
  Frame-Interpolation / KJNodes 等自定义节点
- NVIDIA GPU（本机开发验证环境为 RTX 4060 Laptop 8GB；低显存档配置见
  `settings.yaml` 的 672×1152 / 65 帧）
- DeepSeek API Key（分镜生成必需）

## 关于密钥

`.env` 未包含在本仓库中（已在 `.gitignore` 排除）。请按 `.env.example`
自行填写。仓库内所有 `sk-your-key-here` 均为占位符。

## 交付清理说明

本仓库为干净代码副本，未包含：

- `output/` 下全部运行时生成产物（视频、图片、数据库，约 2.1GB）
- `.env` 及任何真实密钥
- 调试抽帧图、一次性测试残留、`__pycache__`、日志文件

生成产物由程序运行时自动创建，不影响功能。
