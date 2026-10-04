#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""重渲指定场景的「真实 wan5b 图生视频」，复用已生成的首帧/尾帧关键帧 PNG。

用于把此前因 ComfyUI 孤立任务霸占 GPU 而降级成 ken_burns（纯推拉）的场景 4 / 12
升级为真正的首帧单向 i2v 运动 + 尾帧落点。

用法：
  python scripts/rerender_i2v.py            # 重渲 4 / 12
  python scripts/rerender_i2v.py 4          # 只重渲 4
  python scripts/rerender_i2v.py 4 12       # 重渲 4 / 12
"""
from __future__ import annotations
import sys, asyncio, time, shutil
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(PROOT))

import agent_image
import novel_video
from novel_video import land_end_frame, compose, SCENES, OUT, NEG

ALL_IDS = [1, 4, 8, 12]


def scene_by_id(sid: int):
    return next(s for s in SCENES if s["id"] == sid)


async def rerender_one(sid: int) -> bool:
    s = scene_by_id(sid)
    img = OUT / f"scene_{sid:03d}.png"
    end_img = OUT / f"scene_{sid:03d}_end.png"
    if not img.exists():
        print(f"[rerender] 缺失首帧 {img.name}，跳过场景{sid}", flush=True)
        return False
    if not end_img.exists():
        print(f"[rerender] 缺失尾帧 {end_img.name}，跳过尾帧落点（仅做首帧 i2v）", flush=True)

    seed = (abs(hash(f"nv2_{sid}")) % (2 ** 31)) + 1
    out_name = f"nv2_{sid:03d}_vid"
    t0 = time.time()
    print(f"=== 重渲场景 {sid} {s['title']}（复用首帧 {img.name} → 真实 wan5b i2v）===", flush=True)
    res = await agent_image.image_to_video(
        image_path=str(img),
        prompt=s["vid"],
        ratio="16:9",
        duration=s["dur"],
        seed=seed,
        negative=NEG,
        output_name=out_name,
        fast=True,
        on_progress=None,
    )
    mode = res.get("mode", "")
    print(f"  [视频] 模式={mode} 耗时={res.get('elapsed')}s 大小={res.get('size_bytes', 0)//1024}KB", flush=True)

    real = mode.startswith("wan5b")
    final_path = OUT / f"scene_{sid:03d}_final.mp4"
    # 备份被覆盖前的成品（ken_burns 版），以便回退
    if final_path.exists():
        shutil.copyfile(final_path, OUT / f"scene_{sid:03d}_final.bak.mp4")
    if end_img.exists():
        land_end_frame(Path(res["file"]), end_img, final_path)
    else:
        shutil.copyfile(Path(res["file"]), final_path)
    print(f"  [rerender] 场景{sid} 真i2v={'是' if real else '否(降级)'} 用时{int(time.time()-t0)}s -> {final_path.name}", flush=True)
    return real


async def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("scenes", nargs="*", type=int, default=[4, 12])
    args = ap.parse_args()
    targets = [s for s in args.scenes if s in ALL_IDS]
    if not targets:
        print("未指定有效场景", flush=True)
        return

    results = {}
    for sid in targets:
        try:
            results[sid] = await rerender_one(sid)
        except Exception as e:
            print(f"[rerender] 场景{sid} 异常: {str(e)[:200]}", flush=True)
            results[sid] = False
        # 每渲完一个就重合成全片，部分进度立即可见
        print("=== 重新合成成片（含已升级场景）===", flush=True)
        compose(ALL_IDS)

    print("=== 重渲完成 ===", flush=True)
    for sid in targets:
        print(f"  场景{sid}: {'真实 wan5b i2v' if results.get(sid) else '降级 ken_burns（仍可用）'}")


if __name__ == "__main__":
    asyncio.run(main())
