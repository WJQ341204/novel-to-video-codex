"""补做新小说演示的【分镜101 逼前戏言】并重新合成两幕完整版。

背景：novel_fight_demo.py 启动时被旧重渲（场景12 i2v）压在队列后面，
导致场景101在出图阶段 600s 超时崩掉，只产出了场景102。
本脚本单独重跑场景101（复用同一管线），并等场景102落地后把 101+102
重合成【一个】完整演示视频 新小说演示_司马谷岩之战.mp4。

用法：
  python scripts/rerun_scene101.py
"""
from __future__ import annotations
import sys, asyncio, time, zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import novel_video as nv
import novel_fight_demo as fd

TITLE = "《新小说演示》"
SUB = "司马谷岩之战 · 分镜→出图→图生视频"


def main():
    scene = next(s for s in fd.SCENES if s["id"] == 101)
    seed = (zlib.crc32(f"fight_{scene['id']}".encode()) % (2 ** 31)) + 1
    print(f"=== [补做] 分镜 {scene['id']} {scene['title']} ===", flush=True)
    try:
        img = nv.gen_image(scene, seed, "img", "")
        end_img = nv.gen_image(scene, seed, "img_end", "_end")
        time.sleep(1)
        vpath = asyncio.run(nv.gen_video(scene, img, seed))
        nv.land_end_frame(vpath, end_img, nv.OUT / f"scene_{scene['id']:03d}_final.mp4")
    except Exception as e:
        print(f"  [补做] 场景{scene['id']} 失败: {str(e)[:200]}", flush=True)

    # 等场景102落地（由 byiiWN 进程负责）
    s102 = nv.OUT / "scene_102_final.mp4"
    waited = 0
    while not (s102.exists() and s102.stat().st_size > 10000) and waited < 2400:
        time.sleep(15); waited += 15
        if waited % 60 == 0:
            print(f"  [补做] 等待场景102落地…已等 {waited}s", flush=True)
    if not s102.exists():
        print("  [补做] 警告：未等到场景102，将仅合成场景101", flush=True)
        ids = [101]
    else:
        ids = [101, 102]

    print("=== [补做] 重合成完整演示（101+102）===", flush=True)
    final = fd.compose_demo(ids, TITLE, SUB)
    if final and final.exists():
        print(f"  [补做] 完成 -> {final} ({final.stat().st_size//1024}KB)", flush=True)
    else:
        print("  [补做] 合成失败", flush=True)


if __name__ == "__main__":
    main()
