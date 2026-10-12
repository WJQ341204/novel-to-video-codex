# scripts/_legacy —— 一次性 / 调试脚本归档

本目录存放**一次性和调试用途**的脚本，非出片主链。

## 来历

2026-10-12 仓库整理时，从 `scripts/` 根目录（原 152 个扁平 `.py`）中，将 76 个
一次性/调试脚本 `git mv` 至本目录。**移动时已做三项核查**：

1. **无硬编码调用方**：全仓 grep `scripts/xxx.py`，命中全部为核心脚本
   （`main.py` / `flow.py` / `novel_video.py` / `cast.py` / `run_state.py` /
   `video_engine.py` / `launcher.py` / `industrial_bridge.py` / `industrial_pipeline.py` /
   `promptbank.py` / `script_layer.py` / `agent_image.py` 等），无一指向本目录脚本。
2. **无 bare-name 跨脚本 import**：核心脚本不 `import` / `from` 本目录任何模块。
3. **打包与启动链路不点名**：`luminaforge.spec` 入口仅 `scripts/launcher.py`；
   `start_app.bat` / `launch.bat` / `launch.sh` / `Dockerfile` 均只跑 `scripts/main.py`。

git 记录为 **rename（R）而非 delete（D）**，`git log --follow` 可追溯完整历史。

## 前缀含义

| 前缀 | 数量 | 用途 |
|---|---|---|
| `check_*` | 19 | 环境/模型/状态检查 |
| `test_*` | 17 | 单模块冒烟测试 |
| `dl_*` | 8 | 模型权重下载 |
| `verify_*` | 5 | 结果校验 |
| `fetch_*` / `parse_*` / `gen_*` 等 | 其余 | 抓取、解析、生成类一次性工具 |

## 使用方式

仍可独立运行，只是不在主链目录里：

```bash
python scripts/_legacy/check_models.py
python scripts/_legacy/test_wan5b.py
```

注意：这些脚本若内部用 `sys.path` 相对引用同级模块，需自行调整路径；
它们彼此之间以及与核心脚本之间**没有 import 依赖**（已核查）。

## 出片主链（仍在 scripts/ 根）

`flow.py`（入口）/ `novel_video.py`（渲染）/ `add_stepfun_tts.py`（配音）/
`compose_final.py`（合成）/ `cast.py`（角色音色）/ `run_state.py`（断点续跑）/
`video_engine.py` / `main.py`（FastAPI 服务）/ `launcher.py`（桌面拉起）。
