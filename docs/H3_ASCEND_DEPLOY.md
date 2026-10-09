# MiniMax H3 自托管部署（昇腾 910B）

把 **MiniMax H3** 跑在你自己的 **昇腾 910B** 服务器上（Atlas 800I A2/A3，8 卡），由 `engines/h3_ascend.py`
通过 OpenAI 兼容接口 `/v1/videos` 调用。权重**免费开源**，算力在你自己硬件上，故 墨影流光 侧 `cost_usd` 恒为 0。

> 本文档基于 vLLM-Omni 社区的 H3 NPU recipe（8 卡 Atlas 800I A2/A3 路线）+ 官方 MiniMax H3 文档整理。
> **recipe 为社区维护**，首次上线前请按你服务器的实际 CANN / MindIE 版本核对一遍镜像 tag 与启动参数。

---

## 0. 硬件与前提

| 项 | 要求 |
|---|---|
| NPU | 昇腾 910B × **4 或 8**（单卡跑不了完整 H3；8 卡即 Atlas 800I A2/A3） |
| 每卡 HBM | 910B 约 64GB；满血 BF16 峰值 50–140GB/卡 |
| 系统内存 | ≥ 64GB（推荐 128GB+，重卸载时依赖主机内存） |
| 存储 | NVMe SSD；单分区 FL2VA ≈ 135–144GB，Ref2VA 另计，全仓库 ≈ 270GB |
| 容器运行时 | Docker（能拉取 quay.io 镜像、挂载 NPU 设备） |
| 网络 | 能拉取镜像 + 从 HuggingFace/ModelScope 下权重（HF 需先申请模型访问权限） |

---

## 1. 准备镜像与依赖

```bash
# vLLM-Omni NPU 镜像（A5 变体）；上线前确认 tag 是否仍为最新
export IMAGE=quay.io/ascend/vllm-omni:v0.29.0-a5

# 启动容器并进入（设备/驱动挂载按你机房实际调整）
docker run -it --rm --name h3 \
  --device /dev/davinci0 --device /dev/davinci1 --device /dev/davinci2 --device /dev/davinci3 \
  --device /dev/davinci4 --device /dev/davinci5 --device /dev/davinci6 --device /dev/davinci7 \
  -v /usr/local/Ascend/driver:/usr/local/Ascend/driver \
  -v $MODEL_ROOT:/model -v $(pwd):/work -w /work \
  $IMAGE bash
```

容器内安装 H3 所需组件（recipe 明确要求的依赖）：

```bash
# 按官方 recipe：容器内安装 MindIE-SD 与媒体依赖
pip install mindie_sd            # 具体包名/版本以你 CANN 版本对应的文档为准
# fl2va / ref2va 媒体处理依赖
apt-get update && apt-get install -y ffmpeg
pip install decord
```

> ⚠️ MindIE-SD 的安装命令随 CANN 版本变化，请以你镜像配套的 vLLM-Omni NPU 文档为准。

---

## 2. 下载权重

H3 权重在 HuggingFace：`MiniMaxAI/MiniMax-H3`（需先申请访问权限）；国内可用 **ModelScope 魔搭**镜像，支持断点续传。

```bash
# 只服务首/尾帧生视频(fl2va) → 只需下载 FL2VA 分区
hf download MiniMaxAI/MiniMax-H3 --include "FL2VA/*" --local-dir /model
# 若要支持参考图生视频(ref2va) → 再下 Ref2VA 分区
hf download MiniMaxAI/MiniMax-H3 --include "Ref2VA/*" --local-dir /model
```

- **只下你真要用的分区**，减少磁盘与加载时间；每个分区是独立服务。
- 断点续传：重跑同一命令 + 同一 revision 即可；缓存损坏用 `hf download --force-download`。

---

## 3. 启动服务（8 卡 910B）

recipe 在 4 卡 950PR 上用 `--usp 4 --ring 1 --text-encoder-tp-size 4`；**8 卡按官方 8 卡路线放大为 8**：

```bash
export PORT=9098
export MODEL=/model
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
export PYTORCH_NPU_ALLOC_CONF=expandable_segments:True
export HCCL_NPU_SOCKET_PORT_RANGE="auto"
export VLLM_WORKER_MULTIPROC_METHOD=spawn

vllm serve "${MODEL}" \
  --omni \
  --host 0.0.0.0 --port "${PORT}" \
  --trust-remote-code \
  --task-type fl2va \          # t2va | fl2va | ref2va（按下载的分区选）
  --num-gpus 8 \
  --usp 8 --ring 2 \
  --text-encoder-tp-size 8 \
  --vae-parallel-mode tile --vae-use-tiling --vae-patch-parallel-size 8 \
  --enable-diffusion-pipeline-profiler
```

- 首请求含区域编译，先**预热一次**再测稳态延迟。
- 想提速度可加量化（MXFP8 / block-sparse attention），但会引入近似——详见官方 recipe 的 "lossy configuration"。
- **不要用** `--use-fsdp-inference true` 的 FSDP 路径（SGLang 侧曾报静默损坏视频/音频），优先 TP + Ulysses 摆放。

也可直接跑仓库里的 `scripts/deploy_h3_ascend.sh`（已参数化 NUM_GPUS / TASK_TYPE / PORT）。

---

## 4. 验证服务

```bash
# 健康检查（vLLM-Omni 默认监听 127.0.0.1，无公网入口；需暴露请放反向代理后）
curl -s http://127.0.0.1:9098/health   # 或 /v1/models

# 文本生视频(t2va) 冒烟测试
curl -s http://127.0.0.1:9098/v1/videos -H 'Content-Type: application/json' -d '{
  "model":"MiniMax-H3","prompt":"雨夜石桥，灯笼倒映水面，缓慢推镜","duration":5,
  "width":960,"height":1728,"fps":24
}'
```

返回视频 URL / data URI 即成功。**先把返回体的字段名抄下来**，对照 `engines/h3_ascend.py` 的
`_extract_video_url` 调整解析（不同版本 schema 可能不同）。

---

## 4b. 未来接口字段约定（墨影流光侧已接）

H3 是 omni 模型（T2VA / FL2VA / Ref2VA 的 "A" = Audio）。以下接口在 `engines/h3_ascend.py` 已接好，
真机上线时按你服务器实际 schema 校准字段名即可：

| 请求字段 | 触发条件 | 说明 |
|---|---|---|
| `task_type` | 自动推断，或 `GenerateRequest.task_type` 显式指定 | `t2va`（无首帧无参考图）/ `fl2va`（首帧图存在）/ `ref2va`（存在参考图）；显式值优先 |
| `first_frame` / `last_frame` | I2V | base64 data URI 内联（已有） |
| `reference_images` | `ref2va` 且有存在的参考图 | 角色一致性，base64 data URI 列表内联 |
| `generate_audio` | `GenerateRequest.generate_audio=True` | 请求 H3 **原生同步音频**（替代外部 TTS 的一步） |
| `audio_prompt` | `generate_audio=True` 时 | 原生音频的对白/音效提示词 |

**响应解析（宽松兼容，待真机校准）**：
- 视频：`data[].video` / `video_url` / `video` / `url`（支持 URL 或 data URI）
- 音频：`data[].audio` / `audio_url` / `audio_base64`（支持 `{"url":...}` / `{"b64":...}` / 裸字符串）
- 异步任务：提交后返回 `id` / `task_id` → `GET /v1/videos/{task_id}` 轮询至 `succeeded`

**产物落盘**：视频 `<output_name>.mp4`；原生音频 `<output_name>_h3audio.<ext>`（扩展名按 data URI mime 推断），
并通过 `ClipResult.audio_path` 暴露给下游（默认 `generate_audio=False`，与既有「视频 + 外部 TTS」管线解耦）。

---

## 5. 接入 墨影流光

服务起来后，在**跑 墨影流光 的机器**上设置环境变量，并把路由切到本地 h3：

```bash
export H3_ASCEND_URL="http://<服务器IP>:9098"   # 或 H3 服务所在地址
# 可选：H3_ASCEND_TOKEN / H3_ASCEND_MODEL
```

`config/settings.yaml` 或代码里：

```yaml
engines:
  video_mode: local
  local:
    local_kind: h3_ascend
```

接着 `python -m engines.h3_ascend` 跑一次自检（需先开服务）。`flow.py` 的 i2v 环节即可走 H3：
SDXL 出的首帧 → `first_frame` → H3 `fl2va` 生成带原生音频的片段（可顺带替代 TTS 一步）。

---

## 6. 已知注意点

- **单卡跑不了完整 H3**：必须 4–8 卡并行；消费级 8GB 卡不适用本方案。
- **权重免费 ≠ 部署免费**：910B 服务器是重资产，本文档只解决"怎么把免费权重跑起来"。
- **recipe 社区维护**：启动参数、镜像 tag、MindIE-SD 包名随 CANN 版本会变，上线前核对一次。
- **存储用 NVMe**：HDD 的换层延迟会直接卡死流式加载。
- **只下用到的分区**（FL2VA / Ref2VA 二选一或都下），别一股脑下全仓库 270GB 除非空间充裕。
- 与云端 `minimax`(API) 区分：本引擎是**自托管**，不计费；云端 minimax 走 API key 付费。
