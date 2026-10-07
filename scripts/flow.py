"""flow.py — 墨影流光·主链路一键工作流（novel→分镜→图→视频→尾帧→合成→配音→faststart→自检）

把本次会话验证跑通的主链固化成一条命令。只做编排，不重写逻辑：
  1. 预检     ComfyUI 在线? cast.json/prompts 资产在位? run_state 摘要
  2. 渲染     scripts/novel_video.py（--cast --style --neg 原样透传；断点续跑/自动备份由其内部负责）
  3. 配音     scripts/add_stepfun_tts.py（FILMS 内各片：台词 TTS→字幕→配音合成）
  4. faststart 对每个成片做 box 序列自检（ftyp→moov→mdat），不对则 -c copy 重封装
  5. 报告     ffprobe 出时长/体积/编码表

用法：
  python scripts/flow.py --dry-run                 # 只打印将执行的命令链
  python scripts/flow.py --only 4 8 12 --cast --style --neg base,face
  python scripts/flow.py --skip-render             # 渲染已完成：只跑 配音+faststart+报告
  python scripts/flow.py --adopt                   # 把既有产物登记进 run_state 后再走后续
"""
from __future__ import annotations

import argparse
import struct
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = r"C:/Users/Mr.Wang/.workbuddy/binaries/python/envs/default/Scripts/python.exe"
FF = r"C:/Users/Mr.Wang/ffmpeg-shared/ffmpeg-master-latest-win64-gpl/bin/ffmpeg.exe"
FFPROBE = r"C:/Users/Mr.Wang/ffmpeg-shared/ffmpeg-master-latest-win64-gpl/bin/ffprobe.exe"
COMFY = "http://127.0.0.1:8188"
OUT = ROOT / "output" / "novel_demo_v2"
# 与 novel_video.compose_name 的号段规则保持一致：id<200 正篇 / id>=200 残篇
FINALS = [
    "青囊异闻录_雨夜药铺.mp4",
    "青囊异闻录_雨夜药铺_配音版.mp4",
    "青囊异闻录_残篇授书.mp4",
    "青囊异闻录_残篇授书_配音版.mp4",
    "青囊异闻录_铃兰令.mp4",
    "青囊异闻录_铃兰令_配音版.mp4",
    # 无字幕版：不烧屏显字幕的干净画面（--nosub 产出）
    "青囊异闻录_雨夜药铺_无字幕.mp4",
    "青囊异闻录_雨夜药铺_无字幕_配音版.mp4",
    "青囊异闻录_残篇授书_无字幕.mp4",
    "青囊异闻录_残篇授书_无字幕_配音版.mp4",
    "青囊异闻录_铃兰令_无字幕.mp4",
    "青囊异闻录_铃兰令_无字幕_配音版.mp4",
]


def sh(cmd: list[str]) -> int:
    print("  $", " ".join(cmd), flush=True)
    return subprocess.call(cmd, cwd=str(ROOT))


def preflight() -> bool:
    ok = True
    try:
        with urllib.request.urlopen(f"{COMFY}/system_stats", timeout=5):
            print(f"  [预检] ComfyUI 在线 {COMFY}")
            try:
                import vram_opt
                vram_opt.stats()
            except Exception as _e:
                print(f"  [预检] 显存查询跳过：{_e}")
    except Exception as e:
        print(f"  [预检][警告] ComfyUI 不可达：{e}（渲染步骤将失败）")
        ok = False
    for p in [ROOT / "assets" / "cast.json", ROOT / "prompts" / "camera.md",
              ROOT / "scripts" / "novel_video.py", ROOT / "scripts" / "add_stepfun_tts.py"]:
        print(f"  [预检] {'OK ' if p.exists() else '缺失'} {p.relative_to(ROOT)}")
        ok = ok and p.exists()
    return ok


def boxes_faststart(p: Path) -> bool:
    """True = moov 已前置。读前 256KB 解析顶层 box 序列。"""
    with open(p, "rb") as f:
        data = f.read(262144)
    pos, seen = 0, []
    while pos + 8 <= len(data) and len(seen) < 6:
        (size,) = struct.unpack(">I", data[pos:pos + 4])
        typ = data[pos + 4:pos + 8].decode("latin1", "replace")
        seen.append(typ)
        if size < 8:
            break
        pos += size
    return "moov" in seen and ("mdat" not in seen or seen.index("moov") < seen.index("mdat"))


def faststart_all() -> None:
    for name in FINALS:
        p = OUT / name
        if not p.exists() or p.stat().st_size < 5000:
            print(f"  [faststart] 跳过（不存在或过小）：{name}")
            continue
        if boxes_faststart(p):
            print(f"  [faststart] 已是 moov 前置：{name}")
            continue
        tmp = p.with_name(p.stem + "_fs.mp4")
        rc = sh([FF, "-y", "-loglevel", "error", "-i", str(p),
                 "-c", "copy", "-movflags", "+faststart", str(tmp)])
        if rc == 0 and tmp.exists():
            tmp.replace(p)
            print(f"  [faststart] 重封装完成：{name}")


def report() -> None:
    print("=== 自检报告 ===")
    for name in FINALS:
        p = OUT / name
        if not p.exists():
            print(f"  {name}: 缺失")
            continue
        r = subprocess.run([FFPROBE, "-v", "error", "-show_entries",
                            "format=duration,size,bit_rate", "-of", "csv=p=0", str(p)],
                           capture_output=True, text=True)
        dur, size, _ = (r.stdout.strip().split(",") + ["?", "?"])[:3]
        fs = "faststart OK" if boxes_faststart(p) else "faststart 未做"
        print(f"  {name}: {float(dur):.2f}s · {int(size)//1024}KB · {fs}")


def main() -> int:
    ap = argparse.ArgumentParser(description="主链路一键工作流")
    ap.add_argument("--only", nargs="*", type=int, default=[])
    ap.add_argument("--cast", action="store_true")
    ap.add_argument("--style", action="store_true")
    ap.add_argument("--neg", default="")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--adopt", action="store_true")
    ap.add_argument("--skip-render", action="store_true", help="跳过渲染（渲染已完成时）")
    ap.add_argument("--skip-tts", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    nv = [PY, "scripts/novel_video.py"]
    if a.only:
        nv += ["--only", *map(str, a.only)]
    for flag in ("cast", "style", "force", "adopt"):
        if getattr(a, flag):
            nv.append(f"--{flag}")
    if a.neg:
        nv += ["--neg", a.neg]
    tts = [PY, "scripts/add_stepfun_tts.py"]

    print("=== 主链路计划 ===")
    print("  1 预检 → 2 渲染(novel_video) → 3 配音(add_stepfun_tts) → 4 faststart → 5 报告")
    print("  渲染:", " ".join(nv[2:]) or "(全场景·默认参数)")
    print("  配音:", " ".join(tts[2:]) or "(FILMS 全部)")

    if a.dry_run:
        return 0
    print("=== 1/5 预检 ===")
    preflight()
    if not a.skip_render:
        print("=== 2/5 渲染 ===")
        rc = sh(nv)
        if rc != 0:
            print("[中止] 渲染失败，后续步骤取消（断点已存，可直接重跑本命令续跑）")
            return rc
    if not a.skip_tts:
        print("=== 3/5 配音 ===")
        sh(tts)
    print("=== 4/5 faststart ===")
    faststart_all()
    print("=== 5/5 报告 ===")
    report()
    return 0


if __name__ == "__main__":
    sys.exit(main())
