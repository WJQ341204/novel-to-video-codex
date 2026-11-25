# LuminaForge 本机部署实战指南

> 本文档记录在本机（Windows + RTX 4060 8GB）从零部署到成功出片的全部配置、
> 实测性能与踩坑修复。原项目说明见 [README.md](README.md)。

---

## 一、本机部署概览

| 项 | 值 |
|---|---|
| GPU | NVIDIA RTX 4060 8GB（显存峰值实测 4.2-6.9GB，绰绰有余） |
| 主应用 | FastAPI，`http://127.0.0.1:8190` |
| ComfyUI | `http://127.0.0.1:8188`（lowvram 模式） |
| Python | 主应用用 `~/.workbuddy/binaries/python/envs/default`；ComfyUI 用 `D:\ComfyUI\venv`（Python 3.13） |
| PyTorch | 2.7.1 + cu126 |
| TTS | Edge-TTS（联网）；CosyVoice2 未部署时自动降级 |
| 文案 LLM | DeepSeek `deepseek-v4-flash`（Key 在项目根 `.env`） |
| 字幕字体 | 微软雅黑（系统自带，中文 OK） |

## 二、一键启动

桌面上有两个脚本（项目根也有原件）：

1. **双击 `start_comfyui.bat`** → 等窗口出现 `Running`（约 20 秒）
2. **双击 `start_app.bat`** → 主应用就绪
3. 浏览器打开 `http://127.0.0.1:8190`

脚本内置三重保护（勿删）：
- `CODEBUDDY_SAFE_DELETE_ENABLED=0`：禁用 safe-delete 钩子。**没有它，场景收尾清理临时文件时进程会被钩子 fail-closed 杀死**
- 代理环境变量清空：防止 Clash 未运行时 httpx 报 `[Errno 22]`
- ffmpeg 加入 PATH：`<FFMPEG_DIR>/bin`

## 三、出片五步

1. 网页「创建项目」——填书名、类型
2. 「上传小说文本」——纯文本 .txt（UTF-8），建议一章一篇
3. 「生成分镜」——DeepSeek 自动拆场景、析角色、写画面提示词
4. 「开始生成」——每场景 12-17 分钟；**中断后重按自动跳过已完成场景**
5. 完成 → QA 自检（失败场景自动重跑）→ 自动合并

成片位置：`novel-to-video-codex/output/<项目ID>/<书名>_merged.mp4`
（1408×2560 竖版 · 48fps · TTS 配音 + 音效 + BGM + 烧录字幕 + 情绪转场）

单场景素材（关键帧 png、fx/sfx/with_bgm 中间版、配音 mp3）都在同目录。

## 四、模型资产清单（已全部就位）

| 模型 | 位置 | 大小 | 来源 |
|---|---|---|---|
| Wan2.2-TI2V-5B-Q5_K_M.gguf | `D:\ComfyUI\models\diffusion_models\` | 3.8GB | ModelScope |
| umt5-xxl-enc-fp8_e4m3fn.safetensors | `models\text_encoders\` | 6.4GB | **ModelScope `Kijai/WanVideo_comfy`（非 scaled 版，勿用 Comfy-Org repackaged 版）** |
| Wan2.2_VAE.safetensors | `models\vae\` | 1.3GB | ModelScope |
| clip_vision_h.safetensors | `models\clip_vision\` | 1.2GB | ModelScope（同时复制一份改名 `CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors` 供 IPAdapter 用） |
| animagine-xl-4.0.safetensors | `models\checkpoints\` | 6.6GB | ModelScope `cagliostrolab/animagine-xl-4.0`（动漫风关键帧，项目标配） |
| 4x-UltraSharp.pth | `models\upscale_models\` | 64MB | ModelScope |
| rife47.pth | `ComfyUI-Frame-Interpolation\ckpts\RIFE\` | 20MB | **GitHub Release（gh-proxy 下载），非 HF；`models\frame_interpolation` 里的 safetensors 格式不被 RIFE VFI 支持** |
| antelopev2（5 个 onnx） | `models\insightface\models\antelopev2\` | 427MB | ModelScope |
| IPAdapter plus / plus-face SDXL | `models\ipadapter\` | 809MB×2 | ModelScope |

自定义节点（`D:\ComfyUI\custom_nodes\`）：ComfyUI-WanVideoWrapper、ComfyUI-KJNodes、
ComfyUI-GGUF、ComfyUI-VideoHelperSuite、ComfyUI-Frame-Interpolation、ComfyUI_IPAdapter_plus。

venv 额外依赖：cupy-cuda12x（RIFE 必需）、insightface 2.0、onnxruntime、gguf、diffusers、peft 等。

## 五、本机已修复的问题（代码补丁，更新项目时注意保留）

| 文件 | 修改 |
|---|---|
| `engines/wan5b.py` | ① `COMFY_INPUT` 改 `D:\ComfyUI\input`；② `attention_mode` sageattn→**sdpa**（无 sageattention/triton）；③ RIFE VFI 补新版必填参数 `dtype/torch_compile/batch_size` |
| `scripts/main.py` Step 7 清理 | 通配 `*_faded*` 等会误删**其他场景**的中间文件 → 收窄为 `scene_{id:03d}_` 前缀，并加 `*_bgm_tmp*` 残留清理。**此 bug 曾导致 QA 全军覆没连环重跑** |
| `scripts/main.py` TTS v12.3 | 新增**阶跃星辰 StepFun** 云端引擎（`_generate_tts_stepfun`），引擎自动选择 `_select_tts_engine()`：stepfun(配Key) > cosyvoice > edge；失败自动回退 Edge |
| `app/config.py` 等 3 处 | `deepseek-chat` 已停用 → `deepseek-v4-flash` |
| 数据库 | `output/luminaforge.db`（SQLite，jobs 表）；备份在 `luminaforge.db.bak` |

## 六、实测性能

- 45 帧 704×1280 采样：16s/step × 30 步 ≈ 8 分钟；VAE 解码 3 分钟；RIFE+超分段 24 秒
- 单场景全链路 ≈ 12-17 分钟；12 场景 ≈ 2.5-3 小时
- 并发 2 安全（ComfyUI 队列本身串行执行）
- 已验证成片：《青囊异闻录·演示》59.9s / 78MB / 12 场景全链路成功

## 七、故障排查 FAQ

**Q：进程莫名退出，日志尾部有 SystemExit / safe-delete 字样？**
启动脚本没生效，确认 `CODEBUDDY_SAFE_DELETE_ENABLED=0` 已设置。

**Q：生成报 [Errno 22]？**
系统代理残留（Clash 没开）。bat 已清代理；手动启动时先 `set HTTP_PROXY=`。

**Q：pydub 报找不到 ffmpeg？**
Git Bash 环境的 PATH 翻译坑：用 `/c/Users/...` POSIX 格式，别用 `C:/Users/...`。bat 无此问题。

**Q：T5 加载报 "fp8 scaled is not supported"？**
text_encoders 里放的是 Comfy-Org repackaged 版（含 scaled_fp8 键）。换 Kijai 版。

**Q：QA 阶段全部场景失败并连环重跑？**
旧版清理 bug 删光了 faded 文件（已修复）。若再遇到，检查 `final_video_path` 指向的文件是否存在；急救可用页面「重新合并」。

**Q：中断了想续跑？**
直接重新「开始生成」，已完成场景自动跳过。

**Q：ModelScope 下载命令？**
`curl -L -C - -o 目标文件 "https://www.modelscope.cn/models/<org>/<repo>/resolve/master/<path>"`
（`-C -` 续传需警惕：中断后若服务器返回错误页会被拼进文件，建议下载到 .tmp 再改名）

## 八、TTS 配音引擎（v12.3 新增：阶跃星辰）

**引擎优先级**（`_select_tts_engine()` 自动选择）：
`stepfun`（.env 配了 STEPFUN_API_KEY）→ `cosyvoice`（本地 50000 端口已启动）→ `edge`（免费兜底）。
可用环境变量 `TTS_ENGINE=stepfun/cosyvoice/edge` 强制指定。

**启用阶跃星辰**：
1. 到 https://platform.stepfun.com 注册并创建 API Key
2. 填入 `.env`（或 `dist/.env`）的 `STEPFUN_API_KEY=`，重启应用
3. **Step Plan 订阅 Key 必须再设 `STEPFUN_BASE_URL=https://api.stepfun.com/step_plan/v1`**（本项目已配置；按量计费 Key 则注释掉该行走标准端点，否则报 402 quota）
4. 无需改代码——引擎自动切换；阶跃请求失败（断网/Key 无效/欠费）自动回退 Edge，出片不会中断

**能力说明**：
- API：`POST https://api.stepfun.com/v1/audio/speech`（OpenAI 兼容），默认模型 `stepaudio-2.5-tts`
- 场景情绪（紧张/悲伤/热血等 21 种）自动转为 `instruction` 情绪指导，强度 1-10 控制浓淡
- 旁白/对白差异化：旁白附加「沉稳电影旁白」指导
- 语速 `+8%` → speed 1.08（0.5~2.0）；音量 `+20%` → volume 1.2（0.1~2.0）
- Edge 音色自动映射官方音色（晓晓→邻家姐姐、云健→磁性男声…），UI 音色列表已含全部 32 个阶跃官方音色
- 长文本（>900 字）按句分段合成后 ffmpeg 拼接（官方单次 input ≤1000 字符）

**自检**：`python test_stepfun_tts.py --dry`（逻辑验证）/ `python test_stepfun_tts.py`（真实合成，耗额度）

**Q：StepFun 401？** Key 填错或过期，检查 `.env`；日志会提示并已回退 Edge。
**Q：StepFun 402 / exceeded quota？** 多为 **Step Plan 订阅 Key 走错了端点**——检查 `.env` 是否已设 `STEPFUN_BASE_URL=https://api.stepfun.com/step_plan/v1`（订阅 Key 专属）；确实是按量账户没余额才需要充值。期间自动回退 Edge，出片不中断。
**Q：想换轻量模型？** `.env` 设 `STEPFUN_TTS_MODEL=step-tts-mini`（更快更便宜，但情绪指导 instruction 不生效，情绪靠语速/音调兜底）。
