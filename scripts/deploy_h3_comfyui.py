"""MiniMax H3 一键部署脚本 —— NVIDIA CUDA 路线（智星云等国内 GPU 云 / 本地卡）。

在租来的 Linux GPU 实例上 SSH 登录后运行，自动完成：
  1. 安装/升级 huggingface_hub（国内默认走 hf-mirror.com 镜像）
  2. 克隆或更新 ComfyUI（要求 ≥ v0.30.0，H3 原生架构支持从这个版本开始）
  3. 安装 ComfyUI-GGUF 自定义节点，并执行 apply_gguf_arch_patch.py（幂等，
     不打补丁 ComfyUI-GGUF 不认 minimax_h3 架构，会报 unknown architecture）
  4. 检查 ffmpeg（ComfyUI 合成 mp4 需要；缺则尝试 apt 安装）
  5. 按 profile 下载 H3 量化权重到 ComfyUI 模型目录（扩散/文本编码器/VAE 自动归类）

用法（实例上，任选其一）：
    # 先看各量化仓库里到底有哪些文件（文件名以仓库页面为准，抓取前建议先跑这个）
    python scripts/deploy_h3_comfyui.py --profile 48g --list-files

    # 完整部署：A6000/A40/4090PLUS 48G → GGUF pruned Q6_K/Q5_K_S
    python scripts/deploy_h3_comfyui.py --profile 48g

    # RTX 5090 32G（Blackwell）→ NVFP4 pruned，速度最快
    python scripts/deploy_h3_comfyui.py --profile 5090

    # A100 80G → GGUF Q8_0 pruned（Ampere 无 NVFP4/FP8，不走量化精度损失大的路）
    python scripts/deploy_h3_comfyui.py --profile 80g

    # 24G 卡（4090/A5000/A30/3090）→ pruned INT4 / GGUF Q3_K_M，需 offload，慢
    python scripts/deploy_h3_comfyui.py --profile 24g

    # 只装环境不打权重（权重已存在/想手动挑文件时）
    python scripts/deploy_h3_comfyui.py --profile 48g --skip-models

    # ComfyUI 装在数据盘（智星云关机不删数据盘，权重可跨实例复用）
    python scripts/deploy_h3_comfyui.py --profile 48g --comfyui-dir /data/ComfyUI

profile 与智星云在售卡的对应关系（2026-10 官网价）：
    5090  RTX 5090 32G      ¥3.16/h（目前已满需预约；本地 5090 同款实测 10.1s 片段 175s）
    48g   RTX A6000 48G     ¥2.40/h（需预约）
    80g   A100-SXM4-80GB    ¥8.00/h（立即可用）
    24g   RTX 4090 24G      ¥1.65/h（需预约）
    V100 不支持：Volta 无 BF16，H3 权重混合精度跑不动，别租。

权重来源（HuggingFace，均为社区/官方量化重打包）：
    Abiray/MiniMax-H3-GGUF                     GGUF Q3_K_M~Q5_K_M（FL2VA+Ref2VA，15.6-23.9GB）
                                              + GGUF/INT4/NVFP4 文本编码器 + FL2V workflow
    Abiray/MiniMax-H3-Pruned-GGUF              pruned GGUF Q5_K_S 14.1GB / Q6_K 16.7GB / Q8_0 21.6GB
    Abiray/Minimax-H3-nvfp4-INT4-INT8-Convrot  pruned INT4 ~11.3GB / INT8 ~21GB / NVFP4 12.5GB（Blackwell）
    Comfy-Org/MiniMax-H3                       官方重打包：双 VAE + bf16/INT8 + 原生模板
    MiniMaxAI/MiniMax-H3                       官方原始权重（bf16/pruned INT8/NVFP4）

⚠️ 文件名以 HF 仓库页面实时为准：脚本用通配模式抓取，抓不到会报错并提示用
   --list-files 查看实际文件名后改 PROFILES 里的 patterns。
⚠️ 许可证：H3 Community License 有地域限制（有资料称不可在美区自托管），智星云是
   国内平台无碍；商用前请核 MiniMax 官方条款（收入阈值/署名要求）。
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

# ─── profile → 量化清单 ────────────────────────────────────────
# 每项: (repo_id, [allow_patterns], 目标子目录)
#   models/diffusion_models  扩散模型（GGUF unet / safetensors）
#   models/text_encoders     文本编码器（Qwen3-VL 32B 量化版）
#   models/vae               双 VAE（video fp16 + audio fp32，所有 profile 都要）
PROFILES: dict[str, dict] = {
    "5090": {
        "desc": "RTX 5090 32G（Blackwell）→ NVFP4 pruned 扩散 + NVFP4 AWQ 文本编码器",
        "vram": "resident 约 20GB；本地 5090 实测 243帧/10.1s/864×480 带音频/10步 = 175 秒",
        "items": [
            ("Abiray/Minimax-H3-nvfp4-INT4-INT8-Convrot",
             ["*[Nn][Vv][Ff][Pp]4*"], "models/diffusion_models"),
            ("Abiray/Minimax-H3-nvfp4-INT4-INT8-Convrot",
             ["*workflow*.json"], "user/default"),
        ],
    },
    "48g": {
        "desc": "RTX A6000 / A40 / 4090PLUS 48G → GGUF pruned Q6_K 16.7GB（或 Q5_K_S 14.1GB）",
        "vram": "扩散 16.7GB + 编码器约 14-24GB + 双 VAE 5.8GB，48G 内可基本 resident",
        "items": [
            ("Abiray/MiniMax-H3-Pruned-GGUF",
             ["*Pruned*Q6_K*", "*Pruned*Q5_K_S*"], "models/diffusion_models"),
            ("Abiray/MiniMax-H3-GGUF",
             ["*text_encoder*", "*TextEncoder*", "*encoder*.gguf", "*qwen*"],
             "models/text_encoders"),
            ("Abiray/MiniMax-H3-GGUF",
             ["minimax_fl2v_gguf_workflow.json"], "user/default"),
        ],
    },
    "80g": {
        "desc": "A100-SXM4-80GB → GGUF pruned Q8_0 21.6GB（Ampere 无 NVFP4/FP8）",
        "vram": "80G 全部 resident 无需 offload；A100 算力约为 Blackwell 一半，单镜头数分钟",
        "items": [
            ("Abiray/MiniMax-H3-Pruned-GGUF",
             ["*Pruned*Q8_0*"], "models/diffusion_models"),
            ("Abiray/MiniMax-H3-GGUF",
             ["*text_encoder*", "*TextEncoder*", "*encoder*.gguf", "*qwen*"],
             "models/text_encoders"),
            ("Abiray/MiniMax-H3-GGUF",
             ["minimax_fl2v_gguf_workflow.json"], "user/default"),
        ],
    },
    "24g": {
        "desc": "RTX 4090 / A5000 / A30 / 3090 24G → pruned INT4 ~11.3GB 或 GGUF Q3_K_M 15.6GB",
        "vram": "24G 装不下扩散+编码器+VAE 全家桶，需层 offload 到内存，单镜头 10 分钟级",
        "items": [
            ("Abiray/Minimax-H3-nvfp4-INT4-INT8-Convrot",
             ["*[Ii][Nn][Tt]4*"], "models/diffusion_models"),
            ("Abiray/MiniMax-H3-GGUF",
             ["*Q3_K_M*"], "models/text_encoders"),
            ("Abiray/MiniMax-H3-GGUF",
             ["minimax_fl2v_gguf_workflow.json"], "user/default"),
        ],
    },
}

# 双 VAE：所有 profile 都要，按优先级尝试的仓库
VAE_REPOS = ["Comfy-Org/MiniMax-H3", "MiniMaxAI/MiniMax-H3"]
VAE_FILES = ["minimax_h3_video_vae_fp16.safetensors",
             "minimax_h3_audio_vae_fp32.safetensors"]

COMFYUI_REPO = "https://github.com/comfyanonymous/ComfyUI.git"
GGUF_NODE_REPO = "https://github.com/city96/ComfyUI-GGUF.git"
COMFYUI_MIN_VERSION = (0, 30, 0)   # H3 原生架构支持的最低 ComfyUI 版本


def log(msg: str) -> None:
    print(msg, flush=True)


def ok(msg: str) -> None:
    log(f"  ✓ {msg}")


def warn(msg: str) -> None:
    log(f"  ⚠ {msg}")


def fail(msg: str) -> None:
    log(f"  ❌ {msg}")


def run(cmd: list[str], cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
    log(f"  $ {' '.join(cmd)}")
    return subprocess.run(cmd, cwd=str(cwd) if cwd else None,
                          check=check, text=True, capture_output=False)


# ─── 环境 ──────────────────────────────────────────────────────
def ensure_hub(use_mirror: bool) -> None:
    if use_mirror:
        os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
        log("[1/5] huggingface_hub（HF_ENDPOINT=hf-mirror.com 国内镜像）")
    else:
        log("[1/5] huggingface_hub（官方端点）")
    try:
        import huggingface_hub  # noqa: F401
    except ImportError:
        run([sys.executable, "-m", "pip", "install", "-U", "huggingface_hub"])
    else:
        run([sys.executable, "-m", "pip", "install", "-U", "huggingface_hub"])


def check_ffmpeg() -> None:
    log("[4/5] 检查 ffmpeg（ComfyUI 合成 mp4 必需）")
    if shutil.which("ffmpeg"):
        ok("ffmpeg 已存在")
        return
    warn("未找到 ffmpeg，尝试 apt 安装（需要 sudo 权限）")
    if run(["sudo", "apt-get", "install", "-y", "ffmpeg"], check=False).returncode != 0:
        warn("自动安装失败，请手动安装：sudo apt-get update && sudo apt-get install -y ffmpeg")


# ─── ComfyUI ───────────────────────────────────────────────────
def comfyui_version(comfy_dir: Path) -> tuple[int, ...] | None:
    """从 comfyui_version.py 解析版本号。"""
    vf = comfy_dir / "comfyui_version.py"
    if not vf.exists():
        return None
    m = re.search(r'version\s*=\s*["\']([\d.]+)["\']', vf.read_text(encoding="utf-8"))
    if not m:
        return None
    return tuple(int(p) for p in m.group(1).split(".") if p.isdigit())


def setup_comfyui(comfy_dir: Path) -> None:
    log(f"[2/5] ComfyUI（{comfy_dir}）")
    comfy_dir.parent.mkdir(parents=True, exist_ok=True)
    if not (comfy_dir / ".git").exists():
        if comfy_dir.exists() and any(comfy_dir.iterdir()):
            fail(f"{comfy_dir} 非空且不是 git 仓库，请换 --comfyui-dir 或清空该目录")
            sys.exit(1)
        run(["git", "clone", "--depth", "1", COMFYUI_REPO, str(comfy_dir)])
    else:
        run(["git", "pull"], cwd=comfy_dir, check=False)
    ver = comfyui_version(comfy_dir)
    if ver is None:
        warn("读不到 ComfyUI 版本号（comfyui_version.py），请自行确认 ≥ v0.30.0")
    elif ver < COMFYUI_MIN_VERSION:
        fail(f"ComfyUI 版本 {'.'.join(map(str, ver))} < 0.30.0，H3 需要 ≥0.30.0；"
             f"请 git pull 或重装后重跑")
        sys.exit(1)
    else:
        ok(f"ComfyUI 版本 {'.'.join(map(str, ver))}（≥0.30.0，支持 H3 原生架构）")

    log("[3/5] ComfyUI-GGUF 自定义节点")
    node_dir = comfy_dir / "custom_nodes" / "ComfyUI-GGUF"
    if not (node_dir / ".git").exists():
        run(["git", "clone", "--depth", "1", GGUF_NODE_REPO, str(node_dir)])
    else:
        run(["git", "pull"], cwd=node_dir, check=False)
    req = node_dir / "requirements.txt"
    if req.exists():
        run([sys.executable, "-m", "pip", "install", "-r", str(req)], check=False)
    # 架构补丁：不打则 ComfyUI-GGUF 不认 minimax_h3，报 unknown architecture
    patch = node_dir / "apply_gguf_arch_patch.py"
    if patch.exists():
        run([sys.executable, str(patch)], cwd=node_dir)
        ok("已执行 apply_gguf_arch_patch.py（幂等，重复运行无害）")
    else:
        warn("未找到 apply_gguf_arch_patch.py；若加载 GGUF 报 unknown architecture，"
             "请到节点目录手动执行一次该脚本")


# ─── 权重 ──────────────────────────────────────────────────────
def classify(name: str) -> str:
    """按文件名猜测权重该放 ComfyUI 哪个模型子目录。"""
    low = name.lower()
    if low.endswith((".json", ".md", ".txt")) or "workflow" in low:
        return "user/default"
    if "vae" in low:
        return "models/vae"
    if any(k in low for k in ("text_encoder", "encoder", "qwen", "clip", "umt5")):
        return "models/text_encoders"
    return "models/diffusion_models"


def list_repo_files(repo_id: str) -> None:
    """打印仓库全部文件及大小（--list-files 模式）。"""
    from huggingface_hub import HfApi
    log(f"\n── {repo_id} ──")
    try:
        entries = HfApi().list_repo_tree(repo_id, recursive=True)
    except Exception as exc:  # noqa: BLE001
        fail(f"列举失败：{exc}")
        return
    for e in entries:
        size = getattr(e, "size", None)
        sz = f"{size / 1024**3:.2f} GB" if size else ""
        log(f"    {e.path:<60} {sz}")


def download_items(items: list[tuple[str, list[str], str]], comfy_dir: Path) -> list[Path]:
    """按 (repo, patterns, dest) 清单下载；返回本次落地文件列表。"""
    from huggingface_hub import snapshot_download
    staged: list[Path] = []
    for repo_id, patterns, dest in items:
        log(f"  ↓ {repo_id}  patterns={patterns}")
        tmp = comfy_dir / "models" / "_h3_staging"
        try:
            local = snapshot_download(
                repo_id=repo_id,
                allow_patterns=patterns,
                local_dir=str(tmp),
            )
        except Exception as exc:  # noqa: BLE001
            fail(f"下载失败：{exc}")
            warn(f"  → 用 --list-files 看 {repo_id} 实际文件名，再改 PROFILES 里的 patterns")
            continue
        found = sorted(Path(local).rglob("*"))
        files = [p for p in found if p.is_file() and p.suffix != ".md"]
        if not files:
            fail(f"{repo_id} 没匹配到任何文件（patterns={patterns}）")
            warn("  → 用 --list-files 查看实际文件名")
            continue
        for f in files:
            target_dir = comfy_dir / classify(f.name)
            target_dir.mkdir(parents=True, exist_ok=True)
            target = target_dir / f.name
            if target.exists():
                ok(f"已存在，跳过 {f.name}")
                continue
            shutil.move(str(f), str(target))
            rel = target.relative_to(comfy_dir)
            ok(f"{f.name} → {rel}  ({f.stat().st_size / 1024**3:.2f} GB)")
            staged.append(target)
    # 清理 staging 空目录
    staging = comfy_dir / "models" / "_h3_staging"
    if staging.exists():
        shutil.rmtree(staging, ignore_errors=True)
    return staged


def download_vaes(comfy_dir: Path) -> None:
    """双 VAE：人人需要，按仓库优先级尝试精确文件名。"""
    from huggingface_hub import hf_hub_download
    vae_dir = comfy_dir / "models" / "vae"
    vae_dir.mkdir(parents=True, exist_ok=True)
    for name in VAE_FILES:
        target = vae_dir / name
        if target.exists():
            ok(f"已存在，跳过 {name}")
            continue
        for repo_id in VAE_REPOS:
            try:
                got = hf_hub_download(repo_id=repo_id, filename=name,
                                      local_dir=str(vae_dir))
            except Exception:  # noqa: BLE001
                continue
            ok(f"{name} ← {repo_id}  ({Path(got).stat().st_size / 1024**3:.2f} GB)")
            break
        else:
            fail(f"所有仓库都没找到 {name}，请手动下载并放入 {vae_dir}")


def print_next_steps(comfy_dir: Path, profile: str) -> None:
    info = PROFILES[profile]
    log("")
    log("═" * 64)
    log(f"部署完成：{info['desc']}")
    log(f"显存预期：{info['vram']}")
    log("═" * 64)
    log("启动 ComfyUI（实例上，后台跑建议配 nohup 或 tmux）：")
    log(f"    cd {comfy_dir} && python main.py --listen 0.0.0.0 --port 8188")
    log("")
    log("本地访问（SSH 隧道，端口/IP 换成智星云控制台给的）：")
    log("    ssh -p <SSH端口> -L 8188:127.0.0.1:8188 <用户>@<实例IP>")
    log("    然后浏览器开 http://127.0.0.1:8188")
    log("")
    log("工作流：ComfyUI 左侧 Browse workflow → video_minimax_h3_t2v / _i2v / _r2v 模板；")
    log("    GGUF 路线用 models/diffusion_models 里的 .gguf 配 UnetLoaderGGUF 节点加载。")
    log("    H3 一次前向同时出视频 + 32kHz 立体声（VAE 要同时挂 video + audio 两个）。")
    log("")
    log("接进出片管线：跑通后两条路——(a) ComfyUI 手动/API 出片，脚本回流 output/；")
    log("    (b) SGLang/vLLM 起 OpenAI 兼容服务，settings.yaml 走 local_kind: h3_ascend")
    log("    （H3_ASCEND_URL 指向它，原生音频可替代外部 TTS）。见 docs/H3_COMFYUI_DEPLOY.md")
    log("═" * 64)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="MiniMax H3 ComfyUI 一键部署（智星云/国内 GPU 云/Linux）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="profile: " + " | ".join(f"{k} {v['desc']}" for k, v in PROFILES.items()))
    ap.add_argument("--profile", choices=sorted(PROFILES), default="48g",
                    help="按显卡显存/架构选量化方案（默认 48g）")
    ap.add_argument("--comfyui-dir", default=str(Path.home() / "ComfyUI"),
                    help="ComfyUI 安装目录（默认 ~/ComfyUI；建议数据盘，关机不删）")
    ap.add_argument("--skip-models", action="store_true",
                    help="只装 ComfyUI 环境和 GGUF 节点，不下载权重")
    ap.add_argument("--list-files", action="store_true",
                    help="只列出各量化仓库的文件名和大小，不下载不安装")
    ap.add_argument("--no-mirror", action="store_true",
                    help="不用 hf-mirror.com，直连 huggingface.co")
    args = ap.parse_args()

    comfy_dir = Path(args.comfyui_dir).resolve()

    if args.list_files:
        repos = {repo for repo, _, _ in PROFILES[args.profile]["items"]} | set(VAE_REPOS)
        for repo in sorted(repos):
            list_repo_files(repo)
        return 0

    ensure_hub(use_mirror=not args.no_mirror)
    setup_comfyui(comfy_dir)
    check_ffmpeg()

    if args.skip_models:
        log("[5/5] --skip-models：跳过权重下载")
    else:
        log(f"[5/5] 下载 H3 权重（profile={args.profile}）")
        download_items(PROFILES[args.profile]["items"], comfy_dir)
        download_vaes(comfy_dir)

    print_next_steps(comfy_dir, args.profile)
    return 0


if __name__ == "__main__":
    sys.exit(main())
