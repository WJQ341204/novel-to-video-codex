#!/usr/bin/env bash
# MiniMax H3 自托管启动脚本 —— 昇腾 910B（8 卡 Atlas 800I A2/A3 / 4 卡 910B3）
# 用法（在 vLLM-Omni 容器内或已装 vllm-omni 的宿主机上）：
#   NUM_GPUS=8 TASK_TYPE=fl2va PORT=9098 MODEL=/model bash deploy_h3_ascend.sh
# 或先 docker 拉起容器再在容器内运行本脚本（见下方 DOCKER 段）。
set -euo pipefail

# ─── 可调参数（环境变量覆盖）────────────────────────────
export MODEL="${MODEL:-/model}"                 # 权重目录（含 FL2VA/Ref2VA 分区）
export NUM_GPUS="${NUM_GPUS:-8}"                # 8(Atlas 800I) 或 4(910B3)
export TASK_TYPE="${TASK_TYPE:-fl2va}"         # t2va | fl2va | ref2va（须与下载分区一致）
export PORT="${PORT:-9098}"
export IMAGE="${IMAGE:-quay.io/ascend/vllm-omni:v0.29.0-a5}"  # 上线前确认最新 tag
export CONFIG="${CONFIG:-lossless}"            # lossless(保守) | lossy(量化提速)

echo "==> H3 启动参数: gpus=${NUM_GPUS} task=${TASK_TYPE} port=${PORT} config=${CONFIG}"

# 离线 + 显存分配（recipe 要求）
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export PYTORCH_NPU_ALLOC_CONF=expandable_segments:True
export HCCL_NPU_SOCKET_PORT_RANGE="auto"
export VLLM_WORKER_MULTIPROC_METHOD=spawn
export VLLM_OMNI_VIDEO_SYNC_TIMEOUT=4000

# USP / ring 随卡数放大：8 卡 → usp 8 ring 2；4 卡 → usp 4 ring 1
if [ "${NUM_GPUS}" -ge 8 ]; then
  USP=8; RING=2; TEXP=8; VPP=8
else
  USP=4; RING=1; TEXP=4; VPP=4
fi

# ─── 启动命令 ───────────────────────────────────────────
# 注意：不要用 --use-fsdp-inference true（SGLang 侧曾报静默损坏），优先 TP+Ulysses 摆放。
EXTRA=""
if [ "${CONFIG}" = "lossy" ]; then
  # 量化提速（引入近似，上线前自测画质）
  EXTRA="--diffusion-attention-config '{\"default\":{\"backend\":\"RAINFUSION_ATTN\",\"block_sparse\":{\"sparsity\":0.8,\"precision\":\"mix\",\"start_step\":8,\"end_step\":12}}}' --diffusion-quantization-config '{\"transformer\":{\"method\":\"mxfp8\"}}'"
fi

echo "==> 执行 vllm serve ..."
# shellcheck disable=SC2086
vllm serve "${MODEL}" \
  --omni \
  --host 0.0.0.0 --port "${PORT}" \
  --trust-remote-code \
  --task-type "${TASK_TYPE}" \
  --num-gpus "${NUM_GPUS}" \
  --usp "${USP}" --ring "${RING}" \
  --text-encoder-tp-size "${TEXP}" \
  --vae-parallel-mode tile --vae-use-tiling --vae-patch-parallel-size "${VPP}" \
  --enable-diffusion-pipeline-profiler \
  ${EXTRA}

# ─── DOCKER 段（可选：在宿主机直接拉起容器）──────────────
# 取消注释并替换设备挂载后运行：
# docker run -it --rm --name h3 \
#   --device /dev/davinci0 --device /dev/davinci1 --device /dev/davinci2 --device /dev/davinci3 \
#   --device /dev/davinci4 --device /dev/davinci5 --device /dev/davinci6 --device /dev/davinci7 \
#   -v /usr/local/Ascend/driver:/usr/local/Ascend/driver \
#   -v "${MODEL}:/model" -v "$(pwd)":/work -w /work \
#   "${IMAGE}" \
#   bash -c "pip install mindie_sd decord && apt-get update && apt-get install -y ffmpeg && \
#            NUM_GPUS=${NUM_GPUS} TASK_TYPE=${TASK_TYPE} PORT=${PORT} bash /work/deploy_h3_ascend.sh"
