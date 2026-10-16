# MiniMax H3 部署指南 —— NVIDIA CUDA 路线（智星云 GPU 云 / 本地卡）

> 2026-10-16 实测查证版。H3 = MiniMax-H3，33B 全模态 Transformer，**一次前向同时出视频 + 32kHz 立体声**，
> 可整体取代本项目现行的「视频 + 外部 TTS」两步管线。
> 昇腾路线（vLLM-Omni）见 `scripts/deploy_h3_ascend.sh`；本文只写 NVIDIA 路线。

---

## 0. 结论速览（TL;DR）

1. **智星云能跑 H3，而且这是主力路径不是备选**——开发机本机实测只有 RTX 4060 Laptop 8GB
   显存（32G 是系统内存），H3 最小量化档权重（GGUF Q2 8.5GB / pruned INT4 11.3GB）本身
   就超显存，加编码器和双 VAE 必须全量 CPU offload，单镜头 15-40 分钟且画质打折，
   **只能凑合验证、不能量产**。卡要选对：**5090 32G 是唯一甜点卡（NVFP4，公开实测
   10.1s 片段 175 秒），目前已满需预约**；立即可用的高端卡只有 **A100-80G（¥8/h）**；
   A6000 48G（¥2.4/h）要预约；**V100 不能跑**（Volta 无 BF16）。
2. 部署已脚本化：实例上 SSH 登录后跑 `python scripts/deploy_h3_comfyui.py --profile 48g`
   （profile 按卡选：`5090` / `48g` / `80g` / `24g`），自动装 ComfyUI ≥0.30.0 + GGUF 节点 +
   架构补丁 + 按卡下载对应量化权重（国内走 hf-mirror）。
3. 两个必踩的坑脚本已处理：**ComfyUI-GGUF 不认 `minimax_h3` 架构**（要跑
   `apply_gguf_arch_patch.py`）；**VAE 必须同时挂 video + audio 两个**（只挂一个不出声）。
4. 成本量级：5090 约 **¥4-7/部**成片（60-80 镜），A100 约 **¥30-60/部**，另加首次下载
   权重 40-60GB 的 1-2 小时机时。
5. 许可证：H3 Community License 有地域限制（有资料称不可在美区自托管），**智星云是国内平台，
   无碍**；商用前核 MiniMax 官方条款（收入阈值/署名要求）。

---

## 1. 平台事实：智星云（gpu.ai-galaxy.cn）

上海亘聪科技（安诺其集团 300067 全资子公司）的 GPU 租赁平台，国内直连、按小时计费、
关机保留磁盘、支持 SSH 与 Windows RDP、有 ComfyUI 预装镜像。
以下为 2026-10-16 官网在售清单（价格以控制台实时为准）：

| 显卡 | 显存 | 价格 | 状态 | H3 适配 |
|---|---|---|---|---|
| **RTX 5090** | 32G | ¥3.16/h | ⚠️ 已满，需预约 | ✅ **最佳**（NVFP4 路线，见 §2） |
| A100-SXM4 | 80G | ¥8.00/h | ✅ 立即可用 | ✅ 可跑（GGUF Q8_0 pruned，慢于 5090） |
| A100-SXM4 | 40G | ¥2.75/h | ⚠️ 已满 | ✅ 可跑（同 48g 方案） |
| A800-SXM4 | 40G | ¥2.31/h | ⚠️ 已满 | ✅ 可跑（同 48g 方案） |
| RTX A6000 | 48G | ¥2.40/h | ⚠️ 已满，需预约 | ✅ 可跑（GGUF Q6_K，性价比档） |
| RTX 4090PLUS | 48G | ¥2.53/h | ⚠️ 已满 | ✅ 可跑（同 A6000） |
| NVIDIA A40 | 48G | ¥2.20/h | ⚠️ 已满 | ✅ 可跑（同 A6000） |
| RTX 4090 | 24G | ¥1.65/h | ⚠️ 已满 | ⚠️ 能跑但慢（offload，10 分钟/镜头级） |
| RTX A5000 / A30 / 3090 | 24G | ¥1.10-1.62/h | ⚠️ 已满 | ⚠️ 同上 |
| Tesla V100-32G | 32G | ¥1.32/h | ✅ 立即可用 | ❌ **不能跑**：Volta 无 BF16 |
| 1080Ti / 2080Ti / 3080 | ≤11G | ¥0.77/h | ⚠️ 已满 | ❌ 显存不够 |

**现实路径**：5090/A6000/4090 都要预约排队，立即可用的只有 A100-80G（¥8/h）和不适用的 V100。
建议**先预约 5090 排队**（最优），同时**先用 A100-80G 把流程跑通**（立即可用，不等待）。

> 页面信息以控制台实时为准；本文查证时间 2026-10-16。

---

## 2. 选卡 → 量化方案对照

H3 权重体积与量化档位（社区重打包，2026-10 在架）：

| 仓库 | 内容 | 体积 |
|---|---|---|
| `Abiray/MiniMax-H3-GGUF` | GGUF FL2VA + Ref2VA，Q3_K_M/S ~ Q5_K_M；GGUF/INT4/NVFP4 文本编码器；FL2V workflow | 15.6-23.9GB |
| `Abiray/MiniMax-H3-Pruned-GGUF` | pruned GGUF：Q5_K_S / Q6_K / Q8_0 | 14.1 / 16.7 / 21.6GB |
| `Abiray/Minimax-H3-nvfp4-INT4-INT8-Convrot` | pruned INT4 / 混合 INT4-INT8 / INT8 / **NVFP4**（附 per-GPU 指南） | 11.3 / 15.5 / 21 / 12.5GB |
| `Comfy-Org/MiniMax-H3` | 官方重打包：双 VAE + bf16/INT8 + ComfyUI 原生模板 | — |
| `MiniMaxAI/MiniMax-H3` | 官方原始权重（bf16 / pruned INT8 / NVFP4） | — |

**所有方案都需要的双 VAE**（缺一个就没声音或没画面）：
`minimax_h3_video_vae_fp16.safetensors` + `minimax_h3_audio_vae_fp32.safetensors`（约 5.8GB）。

脚本 profile 与卡的对应（`--profile` 参数）：

| profile | 适用卡 | 扩散模型 | 文本编码器 | 预估显存 | 速度量级（单镜头） |
|---|---|---|---|---|---|
| `5090` | RTX 5090 32G（Blackwell） | NVFP4 pruned 12.5GB | NVFP4 AWQ | ~20GB resident | **约 70-90 秒**（公开实测 RTX 5090：243帧/10.1s = 175s，按帧数折算） |
| `48g` | A6000 / 4090PLUS / A40 48G | GGUF pruned Q6_K 16.7GB | GGUF（14.6-27GB） | ~45GB，基本 resident | 约 4-8 分钟 |
| `80g` | A100-SXM4-80G | GGUF pruned Q8_0 21.6GB | GGUF/INT8 | ~50GB，无 offload | 约 3-6 分钟（A100 无 NVFP4/FP8） |
| `24g` | 4090 / A5000 / A30 / 3090 24G | pruned INT4 11.3GB | Q3_K_M | 超限→层 offload | 10 分钟以上，不推荐生产用 |

> A100 为何不选 bf16：bf16 扩散模型 66.3GB 虽能进 80G，但还要叠加 32B 文本编码器，
> 总量约 115GB 放不下；A100 是 Ampere，也没有 FP8/NVFP4，GGUF Q8_0 是它的合理上限。
> 5090 为何最快：Blackwell 有 NVFP4 张量核心，且 32G 足够 NVFP4 全家桶全常驻。

### 2.1 开发机本机能跑吗（2026-10-16 实测：不能）

本机（开发机）实测配置：**RTX 4060 Laptop GPU / 8GB 显存 / 32GB 系统内存**
（`nvidia-smi` + Win32_VideoController 确认；用户口中的"32G 算力卡"实为 32GB 内存）。
ComfyUI 环境本身很好：D:/ComfyUI v0.37.0 + ComfyUI-GGUF 节点已装（venv 在 D:/ComfyUI/venv，
torch 2.7.1+cu126）。但跑 H3 的现实：

- 最小量化档（GGUF Q2 8.5GB / pruned INT4 11.3GB）**光扩散模型权重就超过 8GB 显存**，
  再加编码器（最低 ~11GB）和双 VAE（5.8GB），全家桶约 25GB 权重只能全量 CPU offload；
- 粗估单镜头 15-40 分钟、Q2 画质明显打折，**能凑合跑 1-2 个镜头看效果，不能量产**；
- 24GB 是门槛（10 分钟+/镜头），32GB 才是甜点（NVFP4，约 70-90 秒/镜头）。

结论：**上云是主力路径**。本机 ComfyUI 保持给 Wan5B 出片用——但注意：8GB 显存下
settings.yaml 现行的 960×1728/96帧（staging 约 23GB）会卡死，若出片就在本机跑，
需调回 672×1152/65帧；除非那张 32G 卡其实在另一台机器上（待用户确认）。

---

## 3. 部署步骤（约 30 分钟 + 下载时间）

### 3.1 租实例（控制台操作，需要你本人登录）

1. 控制台 → 算力市场 → 选卡（建议先预约 5090；急用先开 A100-80G）
2. **镜像**：选 **ComfyUI 镜像**（平台预装）；若选通用深度学习镜像，脚本会自己装 ComfyUI
3. **磁盘**：数据盘开 **≥100G**（权重 40-60GB + ComfyUI 环境；智星云关机不删盘，权重可复用）
4. 开机后记录：**实例 IP、SSH 端口、用户名**

### 3.2 带上脚本

任选其一（项目仓库是 PUBLIC）：

```bash
# 方式 A：整仓克隆（推荐，脚本/文档/后续对接都在）
git clone https://github.com/WJQ341204/novel-to-video-codex.git
cd novel-to-video-codex

# 方式 B：只要单文件
scp -P <SSH端口> scripts/deploy_h3_comfyui.py <用户>@<实例IP>:~/
```

### 3.3 一键部署

```bash
# 先看仓库里实际有哪些权重文件（文件名以仓库页面为准，建议先跑）
python scripts/deploy_h3_comfyui.py --profile 48g --list-files

# 正式部署（按卡换 profile：5090 / 48g / 80g / 24g）
python scripts/deploy_h3_comfyui.py --profile 48g
```

脚本自动完成：装/升 `huggingface_hub`（默认 `HF_ENDPOINT=hf-mirror.com` 国内镜像）→
克隆/更新 ComfyUI 并校验 ≥ v0.30.0 → 装 ComfyUI-GGUF 节点 → **执行
`apply_gguf_arch_patch.py`（幂等）** → 检查 ffmpeg → 按 profile 下载权重并自动归类到
`models/diffusion_models`（扩散）、`models/text_encoders`（编码器）、`models/vae`（双 VAE）、
`user/default`（workflow JSON）→ 打印启动命令与隧道命令。

> 如果镜像自带 ComfyUI，把 `--comfyui-dir` 指向镜像里的 ComfyUI 目录即可复用；
> 建议装到数据盘：`--comfyui-dir /data/ComfyUI`。
> 权重已下过：加 `--skip-models` 只补环境。

### 3.4 启动与访问

```bash
cd ~/ComfyUI && python main.py --listen 0.0.0.0 --port 8188   # 建议 tmux/nohup 后台

# 本地电脑（不开公网 8188 的话，SSH 隧道最稳）：
ssh -p <SSH端口> -L 8188:127.0.0.1:8188 <用户>@<实例IP>
# 然后浏览器开 http://127.0.0.1:8188
```

工作流：左侧 Browse workflow → 模板 `video_minimax_h3_t2v` / `_i2v` / `_r2v`；
GGUF 路线用 `UnetLoaderGGUF` 节点加载 `models/diffusion_models` 里的 .gguf
（脚本顺带下载了 `minimax_fl2v_gguf_workflow.json` 到 user/default）。

---

## 4. 已知坑（脚本已处理 / 需人工确认）

| 坑 | 现象 | 处理 |
|---|---|---|
| ComfyUI-GGUF 不认架构 | 加载 GGUF 报 `unknown architecture minimax_h3` | 跑节点目录下的 `apply_gguf_arch_patch.py`（幂等，脚本已自动执行） |
| ComfyUI 版本过低 | 根本没有 H3 节点/模板 | 必须 ≥ v0.30.0（脚本启动时校验，不达标直接退出） |
| 只挂一个 VAE | 出片没声音（或没画面） | video + audio 两个 VAE 都要挂 |
| 缺 ffmpeg | 视频合成节点失败 | 脚本检查并尝试 apt 安装 |
| 权重文件名对不上 | 下载 0 文件 | 文件名以 HF 仓库页面为准；先 `--list-files` 看实际文件名，再改脚本 `PROFILES` 里的 patterns |
| GitHub 慢 | clone ComfyUI/节点卡住 | 实例在国内一般正常；仍慢可用 ghproxy 类镜像换 URL |
| V100 租了 | 跑不动或报 dtype 错 | Volta 无 BF16，别租 V100 |

---

## 5. 成本估算（量级，非承诺）

基准：公开实测 RTX 5090 + NVFP4：243 帧（10.1s）@864×480 带音频 10 步 = **175 秒**；
本项目镜头为 96 帧（4s）@24fps，按帧数折算约 70-90 秒/镜；一部成片按 60-80 镜计。

| 方案 | 单镜头 | 单部成片渲染 | 机时单价 | **单部成本** | 首次下载+调试 |
|---|---|---|---|---|---|
| 5090（NVFP4） | 70-90s | 1.2-1.6h | ¥3.16/h | **≈ ¥4-7** | +1-2h（¥3-6） |
| A100-80G（Q8_0） | 3-6min | 4-8h | ¥8.00/h | **≈ ¥32-64** | +1-2h（¥8-16） |
| A6000 48G（Q6_K） | 4-8min | 2.5-6h | ¥2.40/h | **≈ ¥6-15** | +1-2h（¥2-5） |
| 4090 24G（INT4+offload） | 10min+ | 10h+ | ¥1.65/h | ≈ ¥17+ | 同上 |

**省钱纪律**：权重下完、环境验通后**先关机**（智星云关机保留磁盘不计 GPU 费），
下次开机直接跑；批量出片前先单镜头试通再排队。

---

## 6. 接进出片管线（跑通之后）

H3 的价值不止于"能出片"，而在**原生音视频同步**。两条接法：

### 路线 A：ComfyUI 出片，脚本回流（当天就能用）

ComfyUI 里跑 `video_minimax_h3_t2v/i2v`，输出 mp4（已带人声/环境声），
拷回本地 `output/` 目录，直接进 `compose_final.py` 合成——**可以整段跳过
`add_stepfun_tts.py`**（H3 的 32kHz 立体声就是成品声轨）。
适合先验证画质与音质。

### 路线 B：SGLang/vLLM 起 OpenAI 兼容服务，接 `h3_ascend` 引擎（自动化终点）

在实例上按 MiniMax 官方 model card 用 SGLang 起服务（单卡去掉 `--num-gpus` 即可），
本项目 `engines/h3_ascend.py` 就是它的客户端：

```yaml
# settings.yaml
engines:
  video_mode: local
  local:
    local_kind: h3_ascend
```
```bash
export H3_ASCEND_URL=http://<实例IP>:9098   # 指向 SGLang 服务
```

- `generate_audio=True` 时请求 H3 原生音频，落盘 `<name>_h3audio.<ext>` 并经
  `ClipResult.audio_path` 暴露给下游（引擎已实现，schema 用
  `scripts/h3_schema_probe.py` 校准一次）。
- ref2va 路线（最多 9 张参考图）可直接吃本项目的角色锚定图，做**角色一致性 + 音色一致**。

---

## 7. 许可证与合规

- H3 遵循 **MiniMax H3 Community License Agreement**（仓库 `MiniMaxAI/MiniMax-H3` 的 LICENSE）。
- 有公开资料称该许可**限制在美区自托管**；智星云是国内平台，自用无碍。
- **商用前**核条款中的收入阈值与署名要求（本文不构成法律意见）。

---

## 8. 排障速查

```bash
# 架构报错
python ~/ComfyUI/custom_nodes/ComfyUI-GGUF/apply_gguf_arch_patch.py

# 版本存疑
cat ~/ComfyUI/comfyui_version.py

# 显存爆了 → 换更低的 profile，或 ComfyUI 启动加 --cpu-vae
nvidia-smi   # 看实时占用

# 下载中断 → 重跑同一条命令即可（snapshot_download 断点续传）
```

## 9. 参考

- ComfyUI 官方模板：`video_minimax_h3_t2v / _i2v / _r2v`（ComfyUI ≥0.30.0 内置）
- 量化仓库：见 §2 表格（HuggingFace）
- 本项目脚本：`scripts/deploy_h3_comfyui.py`（本文 §3 的一键化）
- 本项目引擎：`engines/h3_ascend.py`（OpenAI 兼容客户端，路线 B）
- 昇腾路线：`scripts/deploy_h3_ascend.sh`（vLLM-Omni，历史硬件，仅参考）
