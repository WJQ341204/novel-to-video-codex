"""新小说打斗片段 → 短视频（复用 novel_video 的 txt2img / i2v / 落地 / 字幕 / 合成）。

把用户贴的《白璃/叶修/羲和 vs 司马谷岩》打斗文拆成 2 个分镜，跑通同一套
novel-to-video 管线，产出【一个】演示视频：
  分镜1 逼前戏言：司马谷岩逼近羲和、口出轻薄，叶修暗道"这家伙找死"
  分镜2 一掌崩飞：羲和一掌拍出，司马谷岩如离弦之箭撞断一排大树

用法：
  python scripts/novel_fight_demo.py
"""
from __future__ import annotations
import sys, asyncio, zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import novel_video as nv   # 复用 gen_image / gen_video / land_end_frame / 字幕 / 合成

W, H = nv.W, nv.H
NEG = nv.NEG

# 用户贴的打斗文拆出的分镜：id, 画面提示词(img), 视频提示词(vid), 尾帧提示词(img_end)
# nar   = 故事背景/动作描写 —— 只朗读，不混台词
# lines = 角色台词 —— 只做屏显字幕，不朗读
SCENES = [
    dict(id=101, title="逼前戏言", dur=2.2,
         img=("[color: moonlit cool blue with warm amber campfire accent] "
              "[lighting: low-key night, moonlight rim light, warm fire fill] "
              "[composition: medium shot, three figures in depth] "
              "masterpiece, best quality, ultra detailed, 8k uhd, cinematic photorealistic, "
              "an extremely beautiful young woman with long dark hair in flowing eastern silk "
              "robes standing calmly in a night forest clearing, a large muscular brutish man "
              "with a heavy long saber swaggering toward her with a sleazy grin, "
              "a young man and a naive pale girl watching nervously in the background, "
              "moonlit trees, atmospheric, chiaroscuro"),
         vid=("slow subtle motion, the brutish man takes a cocky step forward with a smirk, "
              "the beautiful woman remains still and composed, leaves drift down, cinematic, slow motion"),
         nar="司马谷岩提刀步步逼近，叶修与白璃屏息立在原地。",
         lines="司马谷岩：「小美人，今天就让你尝尝奇妙的滋味！」",
         img_end=("masterpiece, best quality, ultra detailed, the same beautiful woman in silk robes "
                  "begins to calmly raise her palm, the brutish man still approaching with a grin, "
                  "the young man in the background stepping forward protectively, night forest, "
                  "cinematic, photorealistic, chiaroscuro")),
    dict(id=102, title="一掌崩飞", dur=2.4,
         img=("[color: cold white burst against deep ink blue] [lighting: explosive palm-energy glow] "
              "[composition: dynamic, woman's palm thrust forward, man launched backward] "
              "masterpiece, best quality, ultra detailed, 8k uhd, cinematic photorealistic, "
              "an extremely beautiful woman thrusting her open palm forward releasing a soft "
              "shockwave of pale light, a large muscular man launched backward through the air "
              "like an arrow, shattered trees behind him, night forest, motion, dramatic, chiaroscuro"),
         vid=("extremely subtle motion, the pale shockwave ripples outward, the man is flung "
              "backward, debris and leaves scatter, slow motion, cinematic, dramatic"),
         nar="羲和出手如电，一掌拍出；司马谷岩如离弦之箭倒飞而出，一排大树应声而断。",
         lines="司马谷岩：「我要杀了你！」",
         img_end=("masterpiece, best quality, ultra detailed, the muscular man crashing into a row "
                  "of trees that splinter and topple, dust and leaves erupt around him, the beautiful "
                  "woman standing composed in the distance, night forest, cinematic, photorealistic, dramatic")),
]


def compose_demo(ids, title_text, sub_text):
    """拼标题卡 + 各场景（含字幕）为【一个】视频，写到独立文件名避免覆盖旧片。"""
    title = nv.make_title_card(title_text, sub_text, secs=3.0)
    parts = []
    for sid in ids:
        vid = nv.OUT / f"scene_{sid:03d}_final.mp4"
        if not vid.exists():
            print(f"  [合成] 跳过缺失场景{sid}", flush=True)
            continue
        sub_text = nv.scene_subtitle(next(s for s in SCENES if s["id"] == sid))
        sub_png = nv.make_subtitle_png(sub_text)
        over = nv.OUT / f"_subbed_{sid:03d}.mp4"
        ok = nv.run_ff([nv.FF, "-y", "-i", str(vid), "-i", str(sub_png),
                        "-filter_complex", "[0:v][1:v]overlay=0:0[v]",
                        "-map", "[v]", "-r", "24",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-shortest", str(over)])
        if ok:
            parts.append(str(over))
        else:
            parts.append(str(vid))
    if not parts:
        print("  [合成] 无场景可合成", flush=True)
        return None
    listf = nv.OUT / "_concat_fight.txt"
    with open(listf, "w", encoding="utf-8") as f:
        for p in [str(title)] + parts:
            f.write(f"file '{str(p).replace(chr(92), chr(47))}'\n")
    final = nv.OUT / "新小说演示_司马谷岩之战.mp4"
    nv.run_ff([nv.FF, "-y", "-f", "concat", "-safe", "0", "-i", str(listf),
               "-c", "copy", str(final)])
    if final.exists():
        print(f"  [合成] 成片 -> {final} ({final.stat().st_size//1024}KB)", flush=True)
        return final
    return None


def main():
    for s in SCENES:
        seed = (zlib.crc32(f"fight_{s['id']}".encode()) % (2 ** 31)) + 1
        print(f"=== 分镜 {s['id']} {s['title']}（出图→图生视频→尾帧落地）===", flush=True)
        try:
            img = nv.gen_image(s, seed, "img", "")
            end_img = nv.gen_image(s, seed, "img_end", "_end")
            time_sleep()
            vpath = asyncio.run(nv.gen_video(s, img, seed))
            nv.land_end_frame(vpath, end_img, nv.OUT / f"scene_{s['id']:03d}_final.mp4")
        except Exception as e:
            print(f"  [分镜{s['id']}] 失败: {str(e)[:200]}", flush=True)
    print("=== 合成演示视频 ===", flush=True)
    compose_demo([s["id"] for s in SCENES], "《新小说演示》", "司马谷岩之战 · 分镜→出图→图生视频")


import time
def time_sleep():
    time.sleep(1)


if __name__ == "__main__":
    main()
