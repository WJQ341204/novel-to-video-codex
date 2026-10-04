"""小说 → 短视频 直驱脚本（绕过脆弱的编排器，直接驱动 ComfyUI）。

阶段：
  A. 文生图：纯 txt2img.json + RealVisXL_V4.0（无 IPAdapter，避免人脸参考污染）
  B. 图生视频：复用 agent_image.image_to_video（wan5b 真视频，已验证）
  C. 合成：PIL 渲染中文旁白字幕 → ffmpeg 叠加 → 拼接标题卡 + 场景 + 尾板

断点续跑：每一步的状态记在 output/novel_demo_v2/run_state.json（见 scripts/run_state.py）。
重跑自动跳过"已完成且参数没变"的步骤；改了 prompt / 尺寸 / seed 只重做受影响的那一步。

用法：
  python scripts/novel_video.py            # 跑全部场景（自动续跑）
  python scripts/novel_video.py --only 1 4 12
  python scripts/novel_video.py --compose  # 仅合成（图/视频已存在时）
  python scripts/novel_video.py --cast     # 出图时追加角色锚点 token（一致性文本层锁定）
  python scripts/novel_video.py --force    # 忽略状态，全部重做
  python scripts/novel_video.py --adopt    # 把现有产物登记为已完成（不重渲，升级种子算法后用它）
  python scripts/run_state.py show         # 看各步状态

注意 seed：早期版本用内置 hash() 生成，Python 字符串哈希每进程随机 → 每次跑图都不一样，
关键帧无法复现。现已改为 hashlib 确定性种子（见 seed_for()）。
"""
from __future__ import annotations
import sys, os, json, time, asyncio, shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import httpx
import cast as castlib
import run_state as rs

COMFY = "http://127.0.0.1:8188"
FF = r"C:/Users/Mr.Wang/ffmpeg-shared/ffmpeg-master-latest-win64-gpl/bin/ffmpeg.exe"
OUT = ROOT / "output" / "novel_demo_v2"
OUT.mkdir(parents=True, exist_ok=True)
AGENT_DIR = ROOT / "output" / "agent"  # image_to_video 固定输出到这里

W, H = 1280, 704  # 16:9，与视频尺寸一致

NEG = ("deformed, mutated, ugly, disfigured, blurry, low quality, jpeg artifacts, "
       "extra limbs, bad anatomy, missing fingers, watermark, text, logo, signature, "
       "nine grid, grid layout, collage, multiple panels, split screen, photobash, "
       "oversaturated, cartoon, 3d render, plastic")


def seed_for(sid: int, tag: str = "nv2") -> int:
    """确定性种子。

    早期用 abs(hash(...))：Python 的 str hash 带随机盐，每次进程结果不同，
    等于每次出图都是新种子 → 关键帧不可复现 → 角色一致性无从谈起。
    改用 hashlib 后可跨天复现同一张图。
    """
    import hashlib
    h = hashlib.sha1(f"{tag}_{sid}".encode("utf-8")).hexdigest()
    return (int(h[:8], 16) % (2**31)) + 1

# id, 标题, 画面提示词, 视频提示词, 时长(秒), 旁白字幕
SCENES = [
    dict(id=1, title="雷雨叩门", dur=2.5,
         img=("[color: cool blue-gray with warm amber accent] [lighting: storm lightning cold white key light from above] "
              "[composition: wide establishing shot, three-layer depth, rain streaks] masterpiece, best quality, ultra detailed, "
              "8k uhd, a young man in dark robe standing before an old Chinese medicine shop at night, "
              "rain-soaked blue stone street gleaming, wooden plaque reading 回春堂, warm lamplight spilling from doorway, "
              "cold blue rain, cinematic, atmospheric, photorealistic, chiaroscuro"),
         vid=("slow push in toward the young man standing beneath the medicine shop plaque, "
              "rain falling steadily, cold white lightning flickering, cinematic, slow motion"),
         nar="暮色四合，江南小镇的青石板路被雨水浸得发亮。",
         lines="叶玄机：「有人吗？雨太大了，借宿一晚。」",
         img_end="masterpiece, best quality, ultra detailed, the same young man in dark robe pushing the medicine shop door open, door half open, warm amber lamplight spilling from inside, rain curtain sliced by doorway light, cool blue exterior versus warm interior, cinematic, photorealistic, chiaroscuro"),
    dict(id=4, title="老灯研墨", dur=2.5,
         img=("[color: deep umber brown, dark gold, cool blue rain-light accent] [lighting: low-key single oil lamp "
              "chiaroscuro from lower front, cool blue rim] [composition: medium shot, bowed old man at counter] "
              "masterpiece, best quality, ultra detailed, an elderly Chinese shopkeeper with a crystal magnifier "
              "glasses, grinding ink at an inkstone by oil lamp, hundred-eye medicine cabinets behind, "
              "warm lamplight, photorealistic, cinematic, atmospheric"),
         vid=("extremely slow push in toward the inkstone and the old man's bowed face, slow motion, "
              "languid pace, ink stick drawing unhurried circles, oil lamp flicker, cinematic"),
         nar="掌柜的是个花甲老者，戴一副水晶老花镜，正借着油灯捻须研墨。",
         lines="掌柜：「这般时辰还赶路，年轻人，你命硬。」",
         img_end="masterpiece, best quality, ultra detailed, the elderly shopkeeper pauses grinding ink and looks up gently, crystal glasses reflecting warm oil-lamp glow, calm wise expression, hundred-eye medicine cabinets blurred behind, photorealistic, cinematic, warm chiaroscuro"),
    dict(id=8, title="镜片后的刀", dur=2.5,
         img=("[color: cool blue] [lighting: storm lightning rim light] [composition: close-up portrait, "
              "eyes sharp as blade] masterpiece, best quality, ultra detailed, extreme close-up of an elderly "
              "man's face behind crystal glasses, gaze suddenly sharp and dangerous like a blade, "
              "storm light, photorealistic, cinematic, chiaroscuro, intense"),
         vid=("slow push in toward the old man's face, slow motion, languid pace snapping into sudden sharp "
              "focus, grizzled beard, eyes narrowing, cinematic, tense"),
         nar="老者终于抬起头，镜片后的目光陡然锐利如刀。",
         lines="掌柜：「你姓叶。」",
         img_end="masterpiece, best quality, ultra detailed, extreme close-up of the elderly man's face snapping upward, behind crystal glasses his gaze sharp and dangerous like a blade, cold storm rim light, intense, photorealistic, cinematic, chiaroscuro"),
    dict(id=12, title="七分相似", dur=2.5,
         img=("[color: cold white and deep ink] [lighting: storm lightning rim light] [composition: rule of thirds "
              "mirrored silhouettes, a yellowed medical chart on wall] masterpiece, best quality, ultra detailed, "
              "lightning illuminates a yellowed anatomical chart on the wall, the figure in the chart resembles "
              "the young man seven-tenths, silhouettes, ink wash mood, cinematic, atmospheric, photorealistic"),
         vid=("slow motion, subtle camera drift to the left following the lightning flash, hair tips dripping water, "
              "a droplet falling, cinematic, mysterious"),
         nar="窗外惊雷炸响，照亮墙上一幅泛黄医图——图中人影竟与叶玄机有七分相似。",
         lines="叶玄机：「这图上的人……怎么这样像我？」",
         img_end="masterpiece, best quality, ultra detailed, lightning fades, a yellowed anatomical chart on the wall, the figure in the chart overlapping with a silhouette resembling the young man, mysterious afterimage, ink wash mood, cinematic, atmospheric, photorealistic"),

    # ── 残篇授书（id>=200 独立号段，避免与青囊正篇 1/4/8/12 串片）──
    dict(id=201, title="灯下授书", dur=2.5,
         img=("[color: deep umber brown, dark gold lamp glow, cool blue dawn accent] [lighting: low-key oil lamp "
              "from lower front, warm pool of light on the counter] [composition: medium two-shot across the counter, "
              "hundred-eye medicine cabinets behind] masterpiece, best quality, ultra detailed, an elderly Chinese "
              "shopkeeper with crystal magnifier glasses handing a yellowed ancient medical scroll to a young "
              "Chinese man in dark robe across the medicine counter, hundred-eye medicine cabinets behind, "
              "warm oil-lamp glow, photorealistic, cinematic, atmospheric, chiaroscuro"),
         vid=("slow push in toward the yellowed scroll being handed over across the counter, oil lamp flicker, "
              "dust motes drifting in warm light, cinematic, slow motion"),
         nar="老者从百眼药柜深处取出一卷泛黄的医书，就着灯摊在柜上。",
         lines="掌柜：「这卷青囊残篇，我守了三十年。今日交给你。」",
         img_end="masterpiece, best quality, ultra detailed, the young Chinese man in dark robe holds the yellowed medical scroll with both hands, head bowed slightly, the elderly shopkeeper watching calmly behind the counter, warm oil-lamp glow, hundred-eye cabinets blurred behind, photorealistic, cinematic, warm chiaroscuro"),
    dict(id=202, title="雨收出门", dur=2.5,
         img=("[color: cool pale blue-grey dawn, faint warm amber from doorway] [lighting: soft diffused dawn light "
              "from behind, cool rim] [composition: wide shot, young man stepping over threshold, old man "
              "silhouetted inside] masterpiece, best quality, ultra detailed, a young Chinese man in dark robe "
              "holding a scroll stepping out of an old Chinese medicine shop at dawn, rain just stopped, wet blue "
              "stone street reflecting pale sky, elderly shopkeeper watching from the doorway, cinematic, "
              "atmospheric, photorealistic"),
         vid=("slow truck left following the young man stepping out into the wet street, dawn mist drifting, "
              "his robe hem swaying, cinematic, slow motion"),
         nar="雨停时天已破晓，叶玄机抱着医书跨出门槛。",
         lines="叶玄机：「掌柜的，我记下了。」",
         img_end="masterpiece, best quality, ultra detailed, the young man walking away down the rain-washed blue stone street, scroll held against his chest, the medicine shop plaque and the elderly shopkeeper small in the background, pale dawn light, ink wash mood, photorealistic, cinematic, atmospheric"),

    # ── 铃兰令（id>=300 独立号段）──
    # 素材取自 demo_novel.txt 原文：「'抓一味世上没有的药。'叶玄机将一枚青铜药铃放在柜台上。
    # 铃声清越，油灯的火苗骤然一缩。老者终于抬起头……'三十年了……终于有人拿着"铃兰令"走进我这间铺子。'」
    # 这是原小说里张力最强、但此前从未拍过的一段——正适合做全流程演示。
    dict(id=301, title="铜铃落柜", dur=2.5,
         img=("[color: deep umber brown, single warm amber oil lamp, dark shadow] [lighting: low-key oil lamp "
              "from lower left, rim light on metal] [composition: medium close-up across the counter, hands and "
              "bell in foreground, shopkeeper blurred behind] masterpiece, best quality, ultra detailed, a young "
              "Chinese man's hand placing a small archaic bronze medicine bell on a dark wooden medicine counter, "
              "elderly Chinese shopkeeper with crystal magnifier glasses blurred behind the counter, hundred-eye "
              "medicine cabinets in shadow, single oil lamp flame, photorealistic, cinematic, chiaroscuro"),
         vid=("slow push in toward the bronze bell settling on the wooden counter, the oil lamp flame guttering "
              "and shrinking, warm light rippling across the metal, shallow depth of field, cinematic, slow motion"),
         nar="叶玄机将一枚青铜药铃放在柜台上。铃声清越，油灯的火苗骤然一缩。",
         lines="叶玄机：「抓一味世上没有的药。」",
         img_end="masterpiece, best quality, ultra detailed, extreme close-up of an archaic bronze medicine bell resting on dark wood, tiny inscriptions on the bronze surface, the oil lamp flame shrunk to a small bright point behind it, warm amber light, shallow depth of field, photorealistic, cinematic"),
    dict(id=302, title="铃兰令", dur=2.5,
         img=("[color: cold blue shadow, hot amber catchlight on glass] [lighting: single oil lamp from lower "
              "front, hard catchlights in the lenses] [composition: medium single shot, elderly man looking up] "
              "masterpiece, best quality, ultra detailed, an elderly Chinese shopkeeper lifting his head sharply, "
              "crystal magnifier glasses catching the lamp flame, eyes suddenly keen and cutting, hands frozen on "
              "an ink stone, dark wooden counter, hundred-eye medicine cabinets behind, photorealistic, cinematic, "
              "tense atmosphere, chiaroscuro"),
         vid=("slow push in on the elderly shopkeeper raising his head, his gaze sharpening behind crystal "
              "magnifier glasses, lenses flaring with the lamp reflection, cinematic, slow motion"),
         nar="老者终于抬起头，镜片后的目光陡然锐利如刀。",
         lines="掌柜：「三十年了……终于有人拿着铃兰令走进我这间铺子。」",
         img_end="masterpiece, best quality, ultra detailed, extreme close-up of an elderly Chinese man's eyes behind round crystal magnifier glasses, tiny inverted flame reflected in each lens, deep nasolabial folds, intense unreadable expression, warm amber on cold shadow, photorealistic, cinematic"),
]


def scene_subtitle(scene) -> str:
    """屏显字幕文本：背景旁白(nar) 与角色台词(lines) 都要上屏。

    约定（2026-09-28 定稿，别再改反）：
      - nar   = 故事背景/环境/动作描写 —— 【不配音】，只上屏（灰白小字）
      - lines = 角色台词 —— 【要配音】，同时也要上屏（暖黄大字），
                否则会出现"念了台词但画面上看不见"的怪现象
    返回两段文本用 \n 分隔，make_subtitle_png 会分两档样式渲染。
    """
    nar = (scene.get("nar") or "").strip()
    line = (scene.get("lines") or "").strip()
    if nar and line:
        return f"{nar}\n{line}"
    return line or nar


def overlay_subtitle(video: Path, text: str, out: Path) -> Path:
    """把一行文本叠成屏显字幕条；失败时退回原片。"""
    png = make_subtitle_png(text)
    ok = run_ff([FF, "-y", "-i", str(video), "-i", str(png),
                 "-filter_complex", "[0:v][1:v]overlay=0:0[v]",
                 "-map", "[v]", "-r", "24",
                 "-c:v", "libx264", "-pix_fmt", "yuv420p", "-shortest", str(out)])
    return out if (ok and out.exists() and out.stat().st_size > 10000) else video


class ComfyClient:
    def __init__(self):
        self.cid = "novel_demo_v2"

    def submit(self, workflow):
        r = httpx.post(f"{COMFY}/prompt", json={"prompt": workflow, "client_id": self.cid}, timeout=60)
        r.raise_for_status()
        return r.json()["prompt_id"]

    def wait(self, pid, timeout=600):
        t0 = time.time()
        while time.time() - t0 < timeout:
            try:
                h = httpx.get(f"{COMFY}/history/{pid}", timeout=30).json()
            except Exception:
                time.sleep(3); continue
            if pid in h:
                return h[pid]
            time.sleep(3)
        raise TimeoutError(f"等待 ComfyUI 超时: {pid}")

    def download_first_image(self, outputs, dest: Path):
        for nid, o in outputs.items():
            if isinstance(o, dict) and "images" in o:
                for img in o["images"]:
                    u = (f"{COMFY}/view?filename={img['filename']}"
                         f"&subfolder={img.get('subfolder','')}&type={img.get('type','output')}")
                    data = httpx.get(u, timeout=60).content
                    dest.write_bytes(data)
                    return True
        return False


def backup_if_exists(p: Path) -> Path | None:
    """覆盖写产物前先留一份 .bak。

    为什么需要：只要参数指纹一变（改 prompt、开 --cast/--style/--neg），
    断点续跑就会判定该步需重做并直接覆盖原文件。没有备份的话，
    「改之前长什么样」就永远找不回来了——出片做前后对比时才发现已经晚了。
    """
    p = Path(p)
    if not p.exists() or p.stat().st_size == 0:
        return None
    bak = p.with_name(f"{p.stem}.bak{p.suffix}")
    shutil.copyfile(p, bak)
    return bak


def gen_image(scene, seed, field="img", suffix="", neg=None):
    wf = json.load(open(ROOT / "comfyui" / "txt2img.json", encoding="utf-8"))
    wf["1"]["inputs"]["ckpt_name"] = "RealVisXL_V4.0.safetensors"
    wf["4"]["inputs"]["width"] = W
    wf["4"]["inputs"]["height"] = H
    wf["5"]["inputs"]["seed"] = seed
    wf["2"]["inputs"]["text"] = scene[field]
    wf["3"]["inputs"]["text"] = neg or NEG
    wf["7"]["inputs"]["filename_prefix"] = f"nv2_{scene['id']:03d}{suffix}"
    c = ComfyClient()
    pid = c.submit(wf)
    res = c.wait(pid, 600)
    dest = OUT / f"scene_{scene['id']:03d}{suffix}.png"
    backup_if_exists(dest)
    if c.download_first_image(res.get("outputs", {}), dest):
        print(f"  [图] 场景{scene['id']}{suffix} ok -> {dest.name} ({dest.stat().st_size//1024}KB)", flush=True)
        return dest
    raise RuntimeError("未取到图")


async def gen_video(scene, image_path, seed, neg=None):
    import agent_image
    out_name = f"nv2_{scene['id']:03d}_vid"
    res = await agent_image.image_to_video(
        image_path=str(image_path),
        prompt=scene["vid"],
        ratio="16:9",
        duration=scene["dur"],
        seed=seed,
        negative=neg or NEG,
        output_name=out_name,
        fast=True,
        on_progress=None,
    )
    print(f"  [视频] 场景{scene['id']} -> {res.get('file')} mode={res.get('mode')} "
          f"({res.get('elapsed')}s, {res.get('size_bytes',0)//1024}KB)", flush=True)
    return Path(res["file"])


FFPROBE = r"C:/Users/Mr.Wang/ffmpeg-shared/ffmpeg-master-latest-win64-gpl/bin/ffprobe.exe"


def get_duration(path: Path) -> float:
    import subprocess
    try:
        r = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "format=duration",
                            "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
                           capture_output=True, text=True, timeout=30)
        return float(r.stdout.strip())
    except Exception:
        return 2.5


def land_end_frame(video_path: Path, end_image_path: Path, out_path: Path,
                   fps: int = 24, land_dur: float = 1.0, fade_dur: float = 0.8) -> Path:
    """尾部交叉淡入「尾帧关键帧」，让画面收于预想的尾帧——在首帧单向 TI2V 模型上
    实现近似双关键帧（起于心想首帧、收于预想尾帧）的视觉落点。"""
    end_clip = OUT / f"_endclip_{abs(hash(str(end_image_path)))}.mp4"
    vf_end = (f"scale={W}:{H},"
              f"zoompan=z='min(zoom+0.0011,1.06)':d={int(land_dur*fps)}:s={W}x{H}:fps={fps}")
    run_ff([FF, "-y", "-loop", "1", "-i", str(end_image_path), "-vf", vf_end,
            "-t", str(land_dur), "-r", str(fps), "-pix_fmt", "yuv420p",
            "-c:v", "libx264", "-crf", "18", str(end_clip)])
    backup_if_exists(out_path)
    vdur = get_duration(video_path)
    offset = max(0.1, round(vdur - fade_dur, 3))
    filt = f"[0:v][1:v]xfade=transition=fade:duration={fade_dur}:offset={offset:.3f}[v]"
    ok = run_ff([FF, "-y", "-i", str(video_path), "-i", str(end_clip),
                 "-filter_complex", filt, "-map", "[v]", "-r", str(fps),
                 "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", str(out_path)])
    if not ok or not out_path.exists() or out_path.stat().st_size < 10000:
        print(f"  [落帧] 交叉淡化失败，退化直用原视频", flush=True)
        shutil.copyfile(video_path, out_path)
    print(f"  [落帧] 场景尾帧落点 -> {out_path.name} (原{vdur:.2f}s, 淡入尾帧 {fade_dur}s)", flush=True)
    return out_path


def make_subtitle_png(text: str, w=W, h=H, font_size=40) -> Path:
    """用 PIL 渲染底部中文半透明字幕条（透明 PNG，避免 ffmpeg drawtext 的 Windows 冒号坑）。

    支持两段式：用换行符分隔，第一段是背景旁白（米白），第二段是角色台词（暖黄、略大），
    因为配音念的是台词，画面上必须同时看得见台词和背景。
    """
    from PIL import Image, ImageDraw, ImageFont
    font_path = r"C:/Windows/Fonts/msyh.ttc"
    try:
        font = ImageFont.truetype(font_path, font_size)
    except Exception:
        font = ImageFont.load_default()
    tmp = Image.new("RGBA", (10, 10)); d = ImageDraw.Draw(tmp)
    max_w = int(w * 0.86)
    def wrap(s, f):
        ls, cur = [], ""
        for ch in s:
            if ch == "\n":
                ls.append(cur); cur = ""; continue
            if d.textlength(cur + ch, font=f) > max_w and cur:
                ls.append(cur); cur = ch
            else:
                cur += ch
        if cur:
            ls.append(cur)
        return ls
    paras = text.split("\n")
    lines = []          # (文本, 字体, 颜色)
    try:
        font_big = ImageFont.truetype(font_path, int(font_size * 1.1))
    except Exception:
        font_big = font
    if len(paras) == 1:
        for l in wrap(paras[0], font):
            lines.append((l, font, (255, 244, 220, 255)))
    else:
        for l in wrap(paras[0], font):                    # 背景旁白
            lines.append((l, font, (226, 226, 232, 255)))
        for l in wrap(paras[1], font_big):                # 角色台词
            lines.append((l, font_big, (255, 226, 150, 255)))
    lh = int(font_size * 1.35)
    bar_h = lh * len(lines) + 28 + (10 if len(paras) > 1 else 0)
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    bar_y = h - bar_h - 24
    d.rounded_rectangle([int(w*0.06), bar_y, w - int(w*0.06), bar_y + bar_h],
                        radius=18, fill=(0, 0, 0, 150))
    ty = bar_y + 14
    for line, f, color in lines:
        tw = d.textlength(line, font=f)
        d.text(((w - tw) / 2, ty), line, font=f, fill=color)
        ty += lh
    import hashlib
    p = OUT / f"_sub_{hashlib.md5(text.encode('utf-8')).hexdigest()[:10]}.png"
    img.save(p)
    return p


def make_title_card(text, sub, w=W, h=H, secs=4.0) -> Path:
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", (w, h), (12, 14, 20))
    d = ImageDraw.Draw(img)
    try:
        f1 = ImageFont.truetype(r"C:/Windows/Fonts/msyh.ttc", 64)
        f2 = ImageFont.truetype(r"C:/Windows/Fonts/msyh.ttc", 30)
    except Exception:
        f1 = f2 = ImageFont.load_default()
    tw = d.textlength(text, font=f1)
    d.text(((w - tw) / 2, h * 0.40), text, font=f1, fill=(240, 226, 190, 255))
    sw = d.textlength(sub, font=f2)
    d.text(((w - sw) / 2, h * 0.40 + 90), sub, font=f2, fill=(180, 180, 190, 255))
    p = OUT / "_title.png"
    img.save(p)
    # 转成 secs 秒的视频（静态图 + 轻微 zoom）
    out = OUT / "_title.mp4"
    n = int(secs * 24)
    vf = (f"scale={w}:{h},"
          f"zoompan=z='min(zoom+0.0008,1.06)':d={n}:s={w}x{h}:fps=24:"
          f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)',"
          f"format=yuv420p")
    run_ff([FF, "-y", "-loop", "1", "-i", str(p), "-vf", vf, "-t", str(secs),
            "-r", "24", "-pix_fmt", "yuv420p", str(out)])
    return out


def run_ff(cmd):
    import subprocess
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print("  [ffmpeg] 非零退出:", r.stderr[-400:], flush=True)
    return r.returncode == 0


def scene_band(sid: int) -> str:
    """镜号 → 所属片（号段）。新增独立短片时在这里加一段即可。"""
    if sid >= 300:
        return "铃兰令"
    if sid >= 200:
        return "残篇授书"
    return "雨夜药铺"


def compose_name(scene_ids) -> str:
    """由场景号段推导成片名。

    C7 修复：此前成片名硬编码为「青囊异闻录_雨夜药铺.mp4」，
    导致渲染新号段时会静默覆盖已有成片。
    规则：同一号段 → 该片名；跨号段 → 显式列出镜号，绝不合并覆盖。
    """
    ids = sorted(scene_ids)
    if not ids:
        return "青囊异闻录.mp4"
    bands = {scene_band(i) for i in ids}
    if len(bands) == 1:
        return f"青囊异闻录_{bands.pop()}.mp4"
    return "青囊异闻录_选段_" + "-".join(f"{i:03d}" for i in ids) + ".mp4"


def compose(scene_ids, final_name: str = ""):
    ids = sorted(scene_ids)
    bands = {scene_band(i) for i in ids}
    band = bands.pop() if len(bands) == 1 else ""
    sub = {"铃兰令": "第二章 · 铃兰令", "残篇授书": "残篇 · 灯下授书"}.get(band, "第一章 · 雨夜药铺")
    title = make_title_card("《青囊异闻录》", sub)
    parts = []
    for sid in scene_ids:
        vid = OUT / f"scene_{sid:03d}_final.mp4"
        if not vid.exists():
            print(f"  [合成] 跳过缺失场景{sid}: {vid.name}", flush=True)
            continue
        sub_png = make_subtitle_png(scene_subtitle(next(s for s in SCENES if s["id"] == sid)))
        # 叠加字幕
        over = OUT / f"_subbed_{sid:03d}.mp4"
        ok = run_ff([FF, "-y", "-i", str(vid), "-i", str(sub_png),
                     "-filter_complex", "[0:v][1:v]overlay=0:0[v]",
                     "-map", "[v]", "-r", "24",
                     "-c:v", "libx264", "-pix_fmt", "yuv420p", "-shortest", str(over)])
        if ok:
            parts.append(str(over))
        else:
            parts.append(str(vid))
    if not parts:
        print("  [合成] 没有任何场景视频可合成", flush=True)
        return None
    # 拼接（标题卡 + 各场景，全部 24fps / 1280x704 / yuv420p / libx264，可无损 copy）
    listf = OUT / "_concat.txt"
    with open(listf, "w", encoding="utf-8") as f:
        for p in [str(title)] + parts:
            f.write(f"file '{str(p).replace(chr(92), chr(47))}'\n")
    final = OUT / (final_name or compose_name(scene_ids))
    # 护栏：绝不静默覆盖已有成片——目标文件已存在且不在本次备份范围内时先留 .bak
    if final.exists() and final.stat().st_size > 5000:
        backup_if_exists(final)
    run_ff([FF, "-y", "-f", "concat", "-safe", "0", "-i", str(listf),
            "-c", "copy", str(final)])
    if final.exists():
        print(f"  [合成] 成片 -> {final} ({final.stat().st_size//1024}KB)", flush=True)
        return final
    return None


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", type=int, default=[])
    ap.add_argument("--compose", action="store_true")
    ap.add_argument("--final", default="",
                    help="覆盖成片文件名（默认按镜号段推导，见 compose_name）")
    ap.add_argument("--cast", action="store_true",
                    help="出图时追加 assets/cast.json 的角色外貌描述（一致性文本层锁定）")
    ap.add_argument("--style", action="store_true",
                    help="出图时套用 cast.json 的 active_style 全片风格（如 古风·胡金铨）")
    ap.add_argument("--neg", default="",
                    help="叠加 prompts/neg.md 的分档负面词，逗号分隔，如 base,face,costume")
    ap.add_argument("--force", action="store_true", help="忽略断点续跑状态，全部重做")
    ap.add_argument("--adopt", action="store_true",
                    help="把现有产物登记为已完成（不重渲）；升级到确定性种子后用它接上旧产物")
    args = ap.parse_args()

    sel = [s for s in SCENES if (not args.only or s["id"] in args.only)]
    if args.compose:
        compose([s["id"] for s in sel], args.final)
        return

    def _sig(**kw):
        return castlib.sig(kw)

    if args.adopt:
        n = 0
        for s in sel:
            sid = s["id"]
            seed = seed_for(sid)
            base = dict(seed=seed, neg=NEG, w=W, h=H)
            pairs = [
                ("img", OUT / f"scene_{sid:03d}.png", _sig(**base, p=s["img"])),
                ("img_end", OUT / f"scene_{sid:03d}_end.png", _sig(**base, p=s["img_end"])),
                ("final", OUT / f"scene_{sid:03d}_final.mp4", _sig(**base, p=s["vid"], dur=s["dur"])),
            ]
            for step, p, sg in pairs:
                if p.exists() and p.stat().st_size > rs.MIN_BYTES:
                    rs.RS.mark_done(sid, step, sg, [p])
                    n += 1
        print(f"[adopt] 已登记 {n} 步现有产物（{rs.RS.summary()}）", flush=True)
        return

    # 负面词：基线 + prompts/neg.md 分档（可选）
    import promptbank
    neg_extra = [promptbank.get("neg", k) for k in args.neg.split(",") if k.strip()]
    NEG_USED = ", ".join([NEG] + [x for x in neg_extra if x])
    if args.neg:
        print(f"[neg] 叠加分档: {args.neg}", flush=True)

    for s in sel:
        sid = s["id"]
        seed = seed_for(sid)
        sc = dict(s)
        # prompt 三层组装：底稿 + 角色外貌(--cast) + 全片风格(--style)
        sc["img"] = castlib.build_prompt(sid, sc["img"], args.cast, args.style)
        sc["img_end"] = castlib.build_prompt(sid, sc["img_end"], args.cast, args.style)
        print(f"=== 场景 {sid} {s['title']}（首帧出图→图生视频→尾帧落点）seed={seed} ===", flush=True)
        try:
            import vram_opt
            vram_opt.free()   # 显存优化：每幕开始前卸载上一幕驻留模型，防多幕连跑碎片堆积
        except Exception:
            pass

        img_p = OUT / f"scene_{sid:03d}.png"
        end_p = OUT / f"scene_{sid:03d}_end.png"
        final_p = OUT / f"scene_{sid:03d}_final.mp4"
        base = dict(seed=seed, neg=NEG_USED, w=W, h=H)
        sig_img = _sig(**base, p=sc["img"])
        sig_end = _sig(**base, p=sc["img_end"])
        sig_vid = _sig(**base, p=sc["vid"], dur=sc["dur"])
        sig_fin = _sig(**base, p=sc["vid"], dur=sc["dur"], land=1.0, fade=0.8)

        try:
            # A1 首帧
            if not args.force and rs.RS.is_done(sid, "img", sig_img, [img_p]):
                print(f"  [跳过] 场景{sid} 首帧已存在且参数未变", flush=True)
                img = img_p
            else:
                img = gen_image(sc, seed, "img", "", neg=NEG_USED)
                rs.RS.mark_done(sid, "img", sig_img, [img])

            # A2 尾帧
            if not args.force and rs.RS.is_done(sid, "img_end", sig_end, [end_p]):
                print(f"  [跳过] 场景{sid} 尾帧已存在且参数未变", flush=True)
                end_img = end_p
            else:
                end_img = gen_image(sc, seed, "img_end", "_end", neg=NEG_USED)
                rs.RS.mark_done(sid, "img_end", sig_end, [end_img])

            time.sleep(1)

            # B 图生视频
            cached = rs.RS.get(sid, "video")
            vpath = None
            if not args.force and rs.RS.is_done(sid, "video", sig_vid):
                vpath = Path((cached.get("artifacts") or [None])[0])
                print(f"  [跳过] 场景{sid} 视频已存在且参数未变 -> {vpath.name}", flush=True)
            if vpath is None or not vpath.exists():
                vpath = asyncio.run(gen_video(sc, img, seed, neg=NEG_USED))
                rs.RS.mark_done(sid, "video", sig_vid, [vpath])

            # C 尾帧落点
            if not args.force and rs.RS.is_done(sid, "final", sig_fin, [final_p]):
                print(f"  [跳过] 场景{sid} 成片已存在且参数未变", flush=True)
            else:
                land_end_frame(vpath, end_img, final_p)
                rs.RS.mark_done(sid, "final", sig_fin, [final_p])
        except Exception as e:
            print(f"  [场景{sid}] 失败: {str(e)[:200]}", flush=True)

    # 合成
    print("=== 合成成片 ===", flush=True)
    compose([s["id"] for s in sel], args.final)


if __name__ == "__main__":
    main()
