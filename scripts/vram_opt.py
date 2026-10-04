"""vram_opt.py — 8GB 显存优化助手（查询 / 回收 / 预设）

三件事：
  1. stats()  查询 ComfyUI 与 GPU 的显存占用，出片前后各看一眼心里有数
  2. free()   让 ComfyUI 卸载模型并回收显存（多幕连跑时防止碎片堆积）
  3. preset() 输出解析度/块交换的推荐档位（供引擎读取环境变量）

用法：
  python scripts/vram_opt.py stats      # 打印显存现状
  python scripts/vram_opt.py free       # 回收显存（建议每幕之间调用）
  python scripts/vram_opt.py preset low # 打印 low 档参数（不改动引擎，需配合环境变量）

环境变量（引擎读取）：
  LF_BLOCKS_SWAP   块交换块数，越大越省显存越慢（默认 30，low=40，ultra=48）
  LF_WIDTH/LF_HEIGHT  采样分辨率（默认由调用方决定；ultra 建议 832x480）
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.request

COMFY = "http://127.0.0.1:8188"

# 档位：块交换块数 + 建议分辨率（分辨率由调用方决定是否采用）
PRESETS = {
    "normal": {"blocks": 30, "w": 1280, "h": 704, "note": "当前默认，画质优先"},
    "low":    {"blocks": 40, "w": 1024, "h": 576, "note": "省约 1GB，画质轻微下降"},
    "ultra":  {"blocks": 48, "w": 832,  "h": 480, "note": "极限省显存，明显降分辨率"},
}


def _post(path: str, payload: dict) -> bool:
    req = urllib.request.Request(
        f"{COMFY}{path}", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30):
            return True
    except Exception as e:
        print(f"  [显存] 请求 {path} 失败：{e}")
        return False


def comfy_stats() -> dict | None:
    try:
        with urllib.request.urlopen(f"{COMFY}/system_stats", timeout=8) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        print(f"  [显存] ComfyUI 不可达：{e}")
        return None


def gpu_stats() -> str:
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used,memory.total,utilization.gpu",
             "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=15)
        return out.stdout.strip().replace("\n", " | ")
    except Exception:
        return "nvidia-smi 不可用"


def stats() -> None:
    print("=== 显存现状 ===")
    print(f"  GPU: {gpu_stats()} (MB)")
    s = comfy_stats()
    if s:
        dev = s.get("devices", [{}])[0]
        print(f"  ComfyUI: {dev.get('name', '?')} · VRAM total={dev.get('vram_total', 0)//(1024**2)}MB")
        sysinfo = s.get("system", {})
        print(f"  内存: 已用 {sysinfo.get('ram_used', 0)//(1024**2)}MB / "
              f"{sysinfo.get('ram_total', 0)//(1024**2)}MB")
    q = queue_info()
    print(f"  队列: 运行 {q['running']} · 等待 {q['pending']}")


def queue_info() -> dict:
    try:
        with urllib.request.urlopen(f"{COMFY}/queue", timeout=8) as r:
            q = json.loads(r.read().decode())
        return {"running": len(q.get("queue_running", [])),
                "pending": len(q.get("queue_pending", []))}
    except Exception:
        return {"running": -1, "pending": -1}


def free(unload_models: bool = True, free_memory: bool = True) -> bool:
    """让 ComfyUI 卸载模型并回收显存。多幕连跑时每幕之间调一次。"""
    q = queue_info()
    if q["running"] > 0:
        print(f"  [显存] 队列仍有 {q['running']} 个任务在跑，跳过回收")
        return False
    ok = _post("/free", {"unload_models": unload_models, "free_memory": free_memory})
    if ok:
        print("  [显存] 已请求 ComfyUI 卸载模型并回收显存")
    return ok


def preset(level: str = "normal") -> dict:
    p = PRESETS.get(level)
    if not p:
        print(f"  [显存] 未知档位 {level}，可选：{', '.join(PRESETS)}")
        return PRESETS["normal"]
    print(f"=== 显存档位 {level} ===")
    print(f"  LF_BLOCKS_SWAP={p['blocks']}  建议分辨率 {p['w']}x{p['h']}  — {p['note']}")
    return p


def apply_env(level: str) -> dict:
    """把档位写进当前进程环境变量，供随后 import 的引擎读取。"""
    p = preset(level)
    os.environ["LF_BLOCKS_SWAP"] = str(p["blocks"])
    return p


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "stats"
    if cmd == "stats":
        stats()
    elif cmd == "free":
        free()
    elif cmd == "preset":
        preset(sys.argv[2] if len(sys.argv) > 2 else "normal")
    else:
        print(__doc__)
