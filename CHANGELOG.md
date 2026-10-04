# 更新日志（CHANGELOG）

本项目所有值得记录的变更都写在这里。格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循语义化版本。

---

## [未发布]

### 新增（内容层补齐 · 2026-09-28，对照 AI 漫剧资源包的差距分析）
- **`prompts/` 提示词素材库**（新增，4 个词典共 81 条）
  - `camera.md` 28 条运镜（推/拉/摇/移/跟/环绕/角度/组合，含雨夜专用的 `lightning_push`）
  - `micro_expression.md` 22 条微表情（眼/唇/呼吸/手/眉）——短片只有 2~3 秒，全靠这个演戏
  - `style.md` 21 条影调与构图
  - `neg.md` 10 档负面词（base / face / hands / costume / interior / period / motion …）
  - 加载器 `scripts/promptbank.py`：`get("camera","push_in")` / `list` / `find`，按 mtime 缓存
  - **意义**：以前 prompt 手写进 SCENES，写完一次就锁死在那部片子里；现在可跨片复用
- **人物小传体系化**（`assets/cast.json` v2）
  - 每个角色新增 `look`（详细英文外貌）与 `bio`（年龄/身份/性格/背景/服装/习惯动作/声线风格）
  - 叶玄机「思考时摩挲药箱铜扣」、掌柜「抬眼时才真正看人」——习惯动作直接进 prompt 与情绪选择
- **风格模板**（对应 DramaClaw「虾格」）
  - `cast.json` 新增 `styles` + `active_style`：`古风·胡金铨`（青囊在用）/ `暗调悬疑` / `水墨写意`
  - 每段含 prompt_add / neg_add / color / lens；换风格只改 `active_style`，不改脚本
- **剧本层 `scripts/script_layer.py`**（补齐差距最大的一项）
  - 从「小说 → 分镜」一步到位，改为「小说 → 剧本（结构+节拍+爽点）→ 分镜」
  - `check()` 自动校验：钩子 / 节拍 / 爽点 / beat 引用 / 静音可懂 / 角色已登记 /
    声线已配 / 运镜与微表情在词典内 / 相邻幕不重复叙事 / 总时长
  - `to_scenes()` 导出 SCENES 兼容结构，`vid` 由运镜+微表情词典拼装，不再手写
  - 示例剧本 `story/青囊_剧本.json`（4 节拍 + 2 爽点 + 4 幕，校验零 ERROR）
- **`docs/出品自检清单.md`**：出品前 5 段自检（剧本/出图前/出图后/配音字幕/成片），含常用命令
- `novel_video.py` 新增 `--style` / `--neg` 开关（与 `--cast` 一样默认关闭，
  保证既有产物的参数指纹不受影响——已回归验证 4 幕仍判定为已完成）

### 新增（工程层调优 · 2026-09-28）
- **资产表 `assets/cast.json` + 加载器 `scripts/cast.py`**（对标 DramaClaw「虾塘」）
  - 四类资产统一收口：角色 / 场景 / 道具 / **声线**；新增角色、改音色、调 IPAdapter 权重只改 json
  - `voice_for(说话人, 镜号)`：shot_overrides > 角色自带 > defaults 三级查表，支持别名归一
    （"老者"→"掌柜"）。**声线不再硬编码在 `add_stepfun_tts.py`**
  - `enrich_prompt(镜号, prompt)`：文本层一致性锚点（`--cast` 开关启用，默认关闭以免影响既有产物）
  - CLI：`python scripts/cast.py show` / `voice 司马谷岩 101`
- **断点续跑 `scripts/run_state.py`**（对标 DramaClaw「虾条」）
  - 每步记录 status / 参数指纹 sig / 产物路径，落到 `output/novel_demo_v2/run_state.json`
  - 重跑自动跳过「已完成 + 参数未变 + 产物还在且不是半成品」的步骤；改 prompt 或改尺寸只重做受影响那一步
  - `novel_video.py` 新增 `--force`（忽略状态全量重做）/ `--adopt`（把现有产物登记为已完成，不重渲）
  - CLI：`python scripts/run_state.py show` / `reset [镜号|--all]`
- **青囊补台词**：4 幕原本无台词 → 成了纯字幕默片。现补叶玄机 / 掌柜对白，
  配好声线（叶玄机=boyinnanshi 平静4、掌柜=ruyananshi 平静5、镜8 神秘6）

### 修复
- **关键帧不可复现（重要）**：`seed = abs(hash(f"nv2_{id}"))` —— Python 字符串哈希带随机盐，
  每次进程结果都不同，等于每跑一次都是新种子，关键帧无法复现、角色一致性无从谈起。
  改为 `seed_for()`（hashlib 确定性种子），跨进程跨天稳定（实测两次运行 1→1073986316 一致）
- **配音的台词在画面上看不见**：`add_stepfun_tts.py` 屏显只叠了 `nar`，而念的是 `lines`，
  导致"听着有台词、画面上没有"。现 `scene_subtitle()` 改为两段式：背景旁白（灰白小字）
  + 角色台词（暖黄大字，1.1 倍字号）同时上屏
- **字幕 PNG 文件名用内置 hash**：同样受哈希随机化影响，每次运行都重新生成一遍。
  改为 md5 前 10 位，跨运行可复用缓存

### 新增（优化方案 P0/P2/P3 落地）
- **P2 · TTS 缓存 + 并发**（`main.py`）
  - `generate_tts` 拆为「缓存包装层 + `_generate_tts_impl` 实现层」，命中缓存直接复用，
    key = md5(engine|voice|rate|volume|mood|intensity|is_narration|text)，落 `output/_tts_cache/`
  - 新增 `generate_tts_batch(items, max_concurrency=4)`：`asyncio.gather` + 信号量限流（上限 8），
    避免串行等 RTT，也避免触发云端 429
  - 开关：`.env` 设 `TTS_CACHE=0` 可关闭
  - **实测**：6 段冷启动 6.7s → 缓存命中 1.1s，**提速 6.1 倍**，第二轮零云端消耗
- **P0 · 静默降级治理**（`video_engine.py`）
  - `_wan5b` 补重试：最多 2 次 + 指数退避（5s/10s），**每次重试换 seed**，与 `_wan_a14b` 对齐
    （原先一次失败即降级，实测降级率 8.3%）
  - 降级必须留痕：`scene.error_msg` 写入失败原因 + 「已降级 ken_burns（静态图+推拉，画面内容不动）」
  - 新增 `STRICT_VIDEO_MODE=1` 开关：开启后拒绝降级，宁可整条失败也不产出假视频

### 修复
- **P3 · 清理治理**（`main.py`）
  - 新增 `_safe_cleanup()` 三道保险：① 文件名必须带 `scene_{id:03d}_` 前缀
    ② 待删超 50 个视为通配过宽直接中止 ③ 绝不删 `final_video_path`
  - 场景收尾新增**断言**：成片缺失或为空时标记 `error` 而非 `done`，
    杜绝「final_video_path 指向已删中间产物 → QA 全 fail → 12 场景连环重跑（约 3 小时）」
  - 实测：他场景文件被跳过、成片保留、超限中止，均符合预期
  - 复用已有场景成片画面，只重配阶跃星辰 TTS，用于对比不同音色效果
  - `python scripts/make_stepfun_demo.py --voice linjiajiejie`
  - 内置规避：concat list 绝对路径、ffmpeg 不在 PATH 时自动补齐、`tpad=stop_mode=clone` + `-shortest` 音画对齐

### 修复
- **出图无法复现**：三处用内置 `hash()` 生成扩散模型种子（`main.py` 3152 角色立绘 / 8206 场景主种子 / 11086 备用路径）
  - 根因：Python 对 `str` 的 `hash()` 默认开启随机化（PYTHONHASHSEED），同一 job_id 在三个独立进程里
    分别得到 `1802862013` / `206793090` / `1101247780` —— 注释声称「固定 seed」但实际每次重启服务都变
  - 修复：新增 `_stable_seed(text)` 用 `zlib.crc32`（确定性算法），三处全部替换
  - 验证：同一 job_id 跨进程三次均为 `1245802820`，结果可复现
  - 行为保持不变：同一任务内场景仍共享 base seed（各场景仅偏移 `scene.id * 1000`），角色一致性不受影响：Windows 中文环境下 ffprobe/ffmpeg 输出 GBK(cp936) 或 UTF-8 字节，用 `text=True` 交给 Python 按本地编码解码时编码不匹配，会在子进程 **reader 线程**抛 `UnicodeDecodeError`（该异常外层 `try` 拦不住，导致时长误判为 0.0）
  - `quality/gate.py` 新增 `_safe_decode()`：字节捕获 + `utf-8 → gbk → cp936 → latin-1` 多编码回退
  - `story2/assemble.py`、`story2/gen_dialogue.py`、`story2/gen_ltx.py`、`post/compose.py`、`scripts/video_engine.py`、`scripts/main.py` 的 `subprocess.run(..., text=True)` 统一加 `errors="replace"`
  - 实测：UTF-8 中文 / GBK 中文 / ASCII 数值 / 非法字节 四类输入全部零异常

---

## [12.3] — 2026-09-26

### 新增
- **阶跃星辰（StepFun）TTS 引擎**，并设为默认
  - 端点 `POST /v1/audio/speech`，OpenAI 兼容格式，默认模型 `stepaudio-2.5-tts`
  - **Step Plan 订阅 Key 专属端点**支持：`STEPFUN_BASE_URL=https://api.stepfun.com/step_plan/v1`（订阅 Key 必须走此端点，否则报 `402 exceeded quota`）
  - 21 种情绪 → `instruction` 情绪指导词（≤200 字符），旁白附加「沉稳电影旁白」
  - 长文本自动分段：>900 字按句切分，多段 ffmpeg concat 拼接（无 ffmpeg 时 MP3 二进制直拼）
  - `rate` → `speed`、`volume` → `0.1~2.0` 参数换算
  - 33 个阶跃官方音色接入 UI（`/api/tts-voices` 带 `stepfun_available` 标志）
  - Edge→StepFun 音色映射表，回退 Edge 时反向翻译
- **引擎自动选择链**：`TTS_ENGINE` 显式指定 > stepfun（配了 Key）> cosyvoice（已启动）> edge（免费兜底）
- `test_stepfun_tts.py` 测试脚本（`--dry` 逻辑 18 项 / 完整 21 项，含真实合成与假 Key 回退链验证）

### 修复
- StepFun 返回 401/402 时自动回退 Edge-TTS，出片不中断，并给出 402 专属提示文案
- 3 个脚本 docstring 无效转义序列 `SyntaxWarning`（`compose_story2` / `smoke_render` / `train_wan_lora` 改 raw string）
- QA 阶段全场景失败并连环重跑（问题复盘 P15）：Step 7 清理的全局通配 `*_faded*` 会误删其他场景中间文件，收窄为 `scene_{id:03d}_` 前缀

### 文档
- `README.md` 重写为 v12.3 现状（此前仍写 LTX 22B + CosyVoice2）
- 新增 `README_问题复盘.md`（21 个坑的根因分类、解法与复发预防清单）
- 新增 `README_本机部署.md` 第八章 + 阶跃星辰 FAQ
- 新增 `docs/TROUBLESHOOTING.md`（18 条精简速查）
- 新增 `LICENSE`（MIT，此前 README 声称 MIT 但文件缺失）
- 补齐 `.env.example`（`STEPFUN_API_KEY` / `STEPFUN_BASE_URL` / `STEPFUN_TTS_MODEL` / `TTS_ENGINE` / `COMFYUI_PATH`）
- 补齐 `requirements.txt`（`pydantic` / `PyYAML` / `aiohttp`），GPU 重依赖改为注释化可选

### 视频链路
- Wan 2.2 A14B（wan5b）两段式引擎打通：采样+解码 → RIFE 补帧 → 2x 超分
- 换用 Kijai 版 T5 编码器（Comfy-Org repackaged 版含 `scaled_fp8` 键，节点拒收）
- `cupy-cuda12x` 依赖补齐，RIFE VFI 节点补齐 `dtype` / `torch_compile` / `batch_size` 必填参数
- clip_vision 改名适配 IPAdapter 正则（`CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors`）

### 其他
- PyInstaller onefile 打包 `dist/LuminaForge.exe`（`BASE_DIR` = exe 所在目录，便携数据）
- 项目推送至 GitHub：https://github.com/WJQ341204/naizui

---

## [12.0] 及更早

> 早期版本未纳入 Git 版本管理，变更记录不完整。以下为可追溯的关键节点：

- **JobStorage v12.0**：任务存储从 JSON 迁移到 SQLite（`output/luminaforge.db`），支持断点续跑
- 成片合并 `/api/remerge`：12 场景情绪感知转场合并
- MuseTalk 口型同步接入（`story2/assemble.py`）
- 质量门 L1（`quality/gate.py`）：时长 / 分辨率 / 帧率 / 码率 / 音频流 / 静态帧检测

---

## 版本命名说明

- **主版本**：架构级变更（如存储引擎替换、管线重构）
- **次版本**：功能性变更（如新增 TTS 引擎、新增视频引擎）
- **修订号**：Bug 修复与文档更新
