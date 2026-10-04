#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
LuminaForge 智能体出图 —— 效果演示片合成
=========================================
把「同一条指令出的多种风格图」+「wan5b 真视频」拼成一条可看的演示片。

用法:
    python scripts/make_agent_demo.py
    python scripts/make_agent_demo.py --show-duration 3.0

输出: output/智能体出图效果演示.mp4
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

AGENT_DIR = PROJECT_ROOT / "output" / "agent"
OUT_FILE = PROJECT_ROOT / "output" / "智能体出图效果演示.mp4"

W, H, FPS = 1280, 720, 24
FONT_REG = r"C:\Windows\Fonts\msyh.ttc"
FONT_BOLD = r"C:\Windows\Fonts\msyhbd.ttc"

FFMPEG = shutil.which("ffmpeg") or \
    r"C:\Users\Mr.Wang\ffmpeg-shared\ffmpeg-master-latest-win64-gpl\bin\ffmpeg.exe"

# 图片模糊背景填充 + 居中（竖图/方图不留丑黑边）
_PAD = (f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=24:2[bg];"
        f"[0:v]scale={W}:{H}:force_original_aspect_ratio=decrease[fg];"
        f"[bg][fg]overlay=(W-w)/2:(H-h)/2")


def run(cmd: list[str]) -> None:
    r = subprocess.run(cmd, capture_output=True, timeout=600)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.decode("utf-8", "replace")[-800:])


def make_card(lines: list[tuple[str, int, str]], out: Path) -> None:
    """生成一张标题卡 PNG。lines = [(文字, 字号, 颜色), ...]"""
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", (W, H), (16, 18, 27))
    d = ImageDraw.Draw(img)
    # 顶部一条渐变感的紫色装饰条（纯色，避免渐变闪烁）
    d.rectangle([0, 0, W, 6], fill=(99, 102, 241))
    total_h = sum(size + 26 for _, size, _ in lines)
    y = (H - total_h) // 2
    for text, size, color in lines:
        font = ImageFont.truetype(
            r"C:\Windows\Fonts\msyhbd.ttc" if size >= 40 else r"C:\Windows\Fonts\msyh.ttc", size)
        bbox = d.textbbox((0, 0), text, font=font)
        x = (W - (bbox[2] - bbox[0])) // 2
        d.text((x, y), text, font=font, fill=color)
        y += size + 26
    img.save(out, "PNG")


def _fit(img, mode: str):
    """按 cover / contain 把图缩放到 W×H 画布尺寸，返回新图。"""
    from PIL import Image
    iw, ih = img.size
    scale = max(W / iw, H / ih) if mode == "cover" else min(W / iw, H / ih)
    return img.resize((max(1, int(iw * scale)), max(1, int(ih * scale))), Image.LANCZOS)


def _center_crop(img):
    iw, ih = img.size
    return img.crop(((iw - W) // 2, (ih - H) // 2, (iw - W) // 2 + W, (ih - H) // 2 + H))


def compose_frame(src: Path, label: str, sub: str, out: Path,
                  bottom_caption: bool = True) -> None:
    """把一张图铺进 1280×720：模糊背景填充 + 居中前景 + PIL 绘制文字条。

    文字全部在 PIL 里画（ffmpeg 的 drawtext 在 Windows 路径冒号上会解析失败）。
    """
    from PIL import Image, ImageDraw, ImageFont, ImageFilter
    img = Image.open(src).convert("RGB")
    bg = _center_crop(_fit(img, "cover")).filter(ImageFilter.GaussianBlur(26))
    fg = _fit(img, "contain")
    canvas = bg.copy()
    canvas.paste(fg, ((W - fg.width) // 2, (H - fg.height) // 2))
    if label and bottom_caption:
        d = ImageDraw.Draw(canvas, "RGBA")
        f1 = ImageFont.truetype(FONT_BOLD, 34)
        f2 = ImageFont.truetype(FONT_REG, 24)
        tw = max(d.textbbox((0, 0), label, font=f1)[2],
                 d.textbbox((0, 0), sub, font=f2)[2] if sub else 0)
        box_w, box_h = tw + 56, 104 if sub else 62
        x0, y0 = (W - box_w) // 2, H - box_h - 46
        d.rounded_rectangle([x0, y0, x0 + box_w, y0 + box_h], radius=14,
                            fill=(12, 14, 20, 165))
        d.text((x0 + 28, y0 + 16), label, font=f1, fill=(255, 255, 255, 245))
        if sub:
            d.text((x0 + 28, y0 + 60), sub, font=f2, fill=(186, 196, 224, 235))
    canvas.save(out, "PNG")


def make_label_overlay(text: str, out: Path) -> None:
    """生成一张透明 PNG，顶部一条文字条，用于叠加到视频上。"""
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img, "RGBA")
    f = ImageFont.truetype(FONT_BOLD, 30)
    tw = d.textbbox((0, 0), text, font=f)[2]
    box_w, box_h = tw + 48, 60
    x0, y0 = (W - box_w) // 2, 34
    d.rounded_rectangle([x0, y0, x0 + box_w, y0 + box_h], radius=12, fill=(12, 14, 20, 170))
    d.text((x0 + 24, y0 + 13), text, font=f, fill=(255, 255, 255, 245))
    img.save(out, "PNG")


def make_image_segment(src: Path, out: Path, duration: float, label: str,
                       sub: str = "") -> None:
    """单张图 → 带轻微推拉 + 文字标注的片段。"""
    frame = out.with_name(out.stem + "_frame.png")
    compose_frame(src, label, sub, frame, bottom_caption=bool(label))
    frames = int(round(duration * FPS))
    # 注意：单帧输入 + zoompan d=总帧数。若加 -loop 1，每个输入帧都会产生 d 个输出帧，
    # 2.5 秒会被放大成上百秒（实测踩过）。
    vf = (f"scale={W*2}:{H*2},"
          f"zoompan=z='min(zoom+0.0008,1.12)':d={frames}:s={W}x{H}:fps={FPS}")
    run([FFMPEG, "-y", "-i", str(frame),
         "-vf", vf, "-t", str(duration), "-r", str(FPS), "-c:v", "libx264",
         "-pix_fmt", "yuv420p", "-preset", "medium", "-crf", "22", "-an", str(out)])
    frame.unlink(missing_ok=True)


def _esc(p: Path) -> str:
    """concat 列表里的路径：只把反斜杠换成正斜杠，冒号不转义（冒号转义是 filter 语法）。"""
    return str(p).replace("\\", "/")


def make_video_segment(src: Path, out: Path, label: str) -> None:
    """已有视频 → 统一规格 + 顶部文字条叠加。"""
    ov = out.with_name(out.stem + "_label.png")
    make_label_overlay(label, ov)
    run([FFMPEG, "-y", "-i", str(src), "-i", str(ov),
         "-filter_complex", f"[0:v]{_PAD}[v];[v][1:v]overlay=0:0",
         "-r", str(FPS), "-c:v", "libx264", "-pix_fmt", "yuv420p",
         "-preset", "medium", "-crf", "20", "-an", str(out)])
    ov.unlink(missing_ok=True)


def concat(segments: list[Path], out: Path) -> None:
    lst = out.with_suffix(".txt")
    lst.write_text("\n".join(f"file '{_esc(p)}'" for p in segments), encoding="utf-8")
    run([FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "medium", "-crf", "20",
         "-movflags", "+faststart", "-an", str(out)])
    lst.unlink(missing_ok=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--show-duration", type=float, default=2.5, help="每张图展示秒数")
    args = ap.parse_args()

    tmp = Path(tempfile.mkdtemp(prefix="agentdemo_"))
    segs: list[Path] = []

    # ── 片头 ──
    c = tmp / "card_title.png"; s = tmp / "seg_title.mp4"
    make_card([("LuminaForge · 智能体出图", 56, "#ffffff"),
               ("一句指令，变出不一样的画", 34, "#a5b4fc"),
               ("11 维差异引擎 · 7 种风格包 · 可转真视频", 24, "#9ca3af")], c)
    make_image_segment(c, s, 3.2, "", "")
    segs.append(s)

    # ── 章节 1：同一指令 4 种画风 ──
    c = tmp / "card_ch1.png"; s = tmp / "seg_ch1.mp4"
    make_card([("同一条指令 = 4 种完全不同的画", 44, "#ffffff"),
               ("「一位身披红袍的女剑客立于雪山之巅」", 26, "#a5b4fc"),
               ("主体与地点被保留，其余维度自由发挥", 22, "#9ca3af")], c)
    make_image_segment(c, s, 3.0, "", "")
    segs.append(s)

    group1 = [
        ("agent_1790432157_505097347.png", "3D 渲染", "低角度仰拍 · 日出金色逆光 · 暴风雪"),
        ("agent_1790432187_505105266.png", "水彩插画", "高空俯瞰 · 人物缩为一点 · 蓝调时刻"),
        ("agent_1790432230_505113185.png", "日系动漫", "战国月夜 · 黑白朱红双色调 · 硬侧光"),
        ("agent_1790432269_505121104.png", "国风水墨", "唐边塞 · 过肩松枝前景 · 干笔飞白"),
    ]
    for i, (name, style, note) in enumerate(group1):
        src = AGENT_DIR / name
        if not src.exists():
            print(f"[skip] 缺少 {name}")
            continue
        out = tmp / f"g1_{i}.mp4"
        make_image_segment(src, out, args.show_duration, f"{i+1}/4  {style}", note)
        segs.append(out)

    # ── 章节 2：换一条指令 ──
    c = tmp / "card_ch2.png"; s = tmp / "seg_ch2.mp4"
    make_card([("换一条指令，又是另一套画面", 44, "#ffffff"),
               ("「一只橘猫在雨中弹吉他」/「雪夜提灯的古代少女」", 24, "#a5b4fc")], c)
    make_image_segment(c, s, 2.6, "", "")
    segs.append(s)

    group2 = [
        ("agent_1790431079_626179851.png", "3D 渲染", "「橘猫弹吉他」霓虹雨夜"),
        ("agent_1790431117_626187770.png", "国风水墨", "「橘猫弹吉他」山水留白"),
        ("agent_1790431479_1795962178.png", "电影写实", "「雪夜提灯少女」"),
        ("agent_1790431516_1795970097.png", "国风水墨", "「雪夜提灯少女」"),
        ("agent_1790432404_1496525268.png", "赛博朋克", "「雨夜里的赛博朋克拉面摊」16:9"),
    ]
    for i, (name, style, note) in enumerate(group2):
        src = AGENT_DIR / name
        if not src.exists():
            print(f"[skip] 缺少 {name}")
            continue
        out = tmp / f"g2_{i}.mp4"
        make_image_segment(src, out, args.show_duration, style, note)
        segs.append(out)

    # ── 章节 3：真视频 ──
    c = tmp / "card_ch3.png"; s = tmp / "seg_ch3.mp4"
    make_card([("图片还能继续转成真视频", 44, "#ffffff"),
               ("Wan 2.2 TI2V-5B · 画面真会动", 28, "#a5b4fc")], c)
    make_image_segment(c, s, 2.6, "", "")
    segs.append(s)

    for i, (name, label) in enumerate([
        ("agent_1790432404_1496525268.mp4", "赛博朋克拉面摊 · 完整模式（补帧+4x超分 2560×1408）"),
        ("agent_1790432157_505097347_fast.mp4", "女剑客 · 快速模式（原生 704×1280 不超分）"),
    ]):
        src = AGENT_DIR / name
        if not src.exists():
            print(f"[skip] 缺少 {name}")
            continue
        out = tmp / f"v_{i}.mp4"
        make_video_segment(src, out, label)
        segs.append(out)

    # ── 片尾 ──
    c = tmp / "card_end.png"; s = tmp / "seg_end.mp4"
    make_card([("指令 → 画面规格 → 图 → 视频", 42, "#ffffff"),
               ("出图约 30 秒 · 真视频约 15~20 分钟（8G 显存）", 24, "#9ca3af")], c)
    make_image_segment(c, s, 3.0, "", "")
    segs.append(s)

    print(f"共 {len(segs)} 段，开始合成…")
    concat(segs, OUT_FILE)
    size_mb = OUT_FILE.stat().st_size / 1024 / 1024
    print(f"\n✅ 演示片已生成: {OUT_FILE}\n   {size_mb:.1f} MB")
    shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
