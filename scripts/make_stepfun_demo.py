#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""阶跃星辰配音效果演示片生成器（可换音色版）

复用已有 12 场景成片画面，用阶跃星辰 TTS 重新配音，合成一条完整竖屏演示片。
与上一版（儒雅男士 ruyananshi）的区别：只换音色，验证不同 timbre 的效果。

用法：
    python scripts/make_stepfun_demo.py [--voice linjiajiejie]

关键坑（已在代码中规避）：
  1. ffmpeg concat demuxer 的 list 内相对路径按 list 文件目录解析 → 一律绝对路径
  2. 音画对齐：tpad=stop_mode=clone 延长视频 + -shortest 裁剪
  3. Windows 下 ffprobe 输出编码问题已由 _safe_decode 修复，此处只用 ffmpeg 不解析文本
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

# ffmpeg 不在系统 PATH 时手动补齐
FFMPEG_DIR = Path("ffmpeg")
if FFMPEG_DIR.exists():
    os.environ["PATH"] = str(FFMPEG_DIR) + os.pathsep + os.environ.get("PATH", "")

import main  # noqa: E402  复用 main.py 的阶跃星辰 TTS 实现

JOB_ID = "de5b6bf7"
SCENE_DIR = ROOT / "output" / JOB_ID


def ffmpeg_bin() -> str:
    import shutil
    return shutil.which("ffmpeg") or str(FFMPEG_DIR / "ffmpeg.exe")


def load_scenes() -> list[dict]:
    """从 SQLite 读取场景台词与情绪，避免依赖运行时接口。"""
    db = sqlite3.connect(str(ROOT / "output" / "luminaforge.db"))
    cur = db.cursor()
    cur.execute("SELECT data FROM jobs WHERE job_id=?", (JOB_ID,))
    row = cur.fetchone()
    db.close()
    if not row:
        raise SystemExit(f"数据库里找不到 job {JOB_ID}")
    return json.loads(row[0])["scenes"]


async def synth_all(scenes: list[dict], voice: str, work: Path) -> list[tuple[Path, Path]]:
    """逐场景生成配音，返回 [(视频, 音频), ...]"""
    pairs = []
    t0 = time.time()
    for s in scenes:
        sid = s["id"]
        video = SCENE_DIR / f"scene_{sid:03d}_final.mp4"
        if not video.exists():
            print(f"  ⚠️ 场景 {sid:02d} 缺少成片，跳过")
            continue
        text = s.get("subtitle_display") or s.get("subtitle_text") or ""
        if not text.strip():
            print(f"  ⚠️ 场景 {sid:02d} 无台词，跳过")
            continue
        audio = work / f"scene_{sid:03d}_vo.mp3"
        mood = s.get("mood", "") or ""
        intensity = int(s.get("emotional_intensity") or 5)
        dur = await main._generate_tts_stepfun(
            text, str(audio), voice=voice, rate="+0%", volume="+0%",
            mood=mood, intensity=intensity, is_narration=True,
        )
        size_kb = audio.stat().st_size / 1024 if audio.exists() else 0
        print(f"  场景 {sid:02d} [{mood or '无'}] {len(text)}字 -> {dur:.1f}s / {size_kb:.0f}KB")
        pairs.append((video, audio))
    print(f"  配音总耗时 {time.time() - t0:.1f}s，成功 {len(pairs)}/{len(scenes)} 段")
    return pairs


def mux(video: Path, audio: Path, out: Path) -> bool:
    """音画合成：视频不足则克隆末帧延长，音频唱完即止。"""
    ff = ffmpeg_bin()
    cmd = [
        ff, "-y",
        "-i", str(video), "-i", str(audio),
        "-filter_complex", "[0:v]tpad=stop_mode=clone:stop_duration=6[v]",
        "-map", "[v]", "-map", "1:a",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
        "-shortest", str(out),
    ]
    r = subprocess.run(cmd, capture_output=True, timeout=900)
    if r.returncode != 0:
        print(f"  ❌ 合成失败 {video.name}: {r.stderr[-200:].decode('utf-8', 'replace')}")
        return False
    return True


def concat(parts: list[Path], out: Path) -> bool:
    ff = ffmpeg_bin()
    lst = out.parent / "concat_list.txt"
    # 坑：list 内相对路径按 list 文件目录解析 → 必须绝对路径
    lst.write_text("".join(f"file '{p.resolve().as_posix()}'\n" for p in parts), encoding="utf-8")
    cmd = [ff, "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
           "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", str(out)]
    r = subprocess.run(cmd, capture_output=True, timeout=1800)
    if r.returncode != 0:
        print(f"  ❌ 拼接失败: {r.stderr[-300:].decode('utf-8', 'replace')}")
        return False
    return True


async def main_async(voice: str) -> int:
    work = SCENE_DIR / f"_demo_{voice}"
    work.mkdir(parents=True, exist_ok=True)

    scenes = load_scenes()
    print(f"加载 {len(scenes)} 个场景，音色 = {voice}\n")

    print("[1/3] 生成阶跃星辰配音")
    pairs = await synth_all(scenes, voice, work)
    if not pairs:
        print("没有任何配音生成，终止")
        return 1

    print("\n[2/3] 音画合成")
    parts = []
    for i, (v, a) in enumerate(pairs, 1):
        out = work / f"part_{i:02d}.mp4"
        print(f"  合成 {i:02d}/{len(pairs)} {v.name}", end="", flush=True)
        if mux(v, a, out):
            parts.append(out)
            print(f" -> {out.stat().st_size / 1024 / 1024:.1f}MB")
        else:
            print(" -> 失败")
    if not parts:
        print("全部合成失败，终止")
        return 1

    print(f"\n[3/3] 拼接 {len(parts)} 段")
    final = ROOT / "output" / f"阶跃星辰·{voice}配音演示.mp4"
    if not concat(parts, final):
        return 1

    mb = final.stat().st_size / 1024 / 1024
    print(f"\n✅ 完成: {final}")
    print(f"   体积 {mb:.1f}MB")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--voice", default="linjiajiejie", help="阶跃星辰音色 ID")
    args = ap.parse_args()
    raise SystemExit(asyncio.run(main_async(args.voice)))
