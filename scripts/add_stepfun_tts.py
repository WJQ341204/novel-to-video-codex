"""把阶跃星辰 StepFun 配音接到 novel-to-video 成片上（复用 main.py 的 generate_tts）。

用法：
  python scripts/add_stepfun_tts.py qingnang     # 给已完成的《青囊异闻录》4 幕片加配音
  python scripts/add_stepfun_tts.py fight        # 给《司马谷岩之战》打斗片加配音（需 101/102 已渲染完）

重要约定（2026-09-28 修订）：
  - 台词(lines) → 【要配音】：用阶跃星辰把角色说的话念出来，按角色配不同音色与情绪
  - 旁白/背景介绍(nar) → 【不配音】：只作为画面文字显示，不朗读

流程：
  1. 每幕先把 nar（故事背景）叠成屏显文字
  2. 有台词则该幕用 main.generate_tts(engine="stepfun") 合成角色台词的语音
     （无台词则补静音轨，保证 concat 对齐）
  3. 混入音轨（语音长于画面则冻结末帧补足，保动作原生节奏）→ concat 出带语音成片

依赖：main.py（阶跃星辰 TTS）、novel_video.py（FF/ffprobe/get_duration/标题卡）。

声线配置：统一查 assets/cast.json（scripts/cast.py::voice_for），不再在脚本里硬编码角色音色。
改声线 / 加角色 → 只改 cast.json。单镜情绪覆写写在 cast.json 的 shot_overrides 里。
"""
from __future__ import annotations
import sys, asyncio, json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import main
import novel_video as nv   # FF / get_duration / make_title_card / OUT
import cast as castlib     # 资产表：角色 → 声线（voice/mood/intensity）

# 角色声线不再写在这里，统一查 assets/cast.json：
#   characters.<角色>.voice / mood / intensity    —— 该角色的基础声线
#   shot_overrides.<镜号>.mood / intensity        —— 单镜情绪覆写（同角色不同情绪）
# 脚本只负责"谁在说话"→ 查表 → 配音。

MANIFESTS = {
    "qingnang": dict(
        title=("《青囊异闻录》", "第一章 · 雨夜药铺 · 角色台词配音"),
        # 只取正篇（id<200）；id>=200 是独立短片号段，避免串片
        scenes=[s for s in nv.SCENES if s["id"] < 200],
        final="青囊异闻录_雨夜药铺_配音版.mp4",
    ),
    "shoushu": dict(
        title=("《青囊异闻录》", "残篇授书 · 角色台词配音"),
        # 号段严格收窄：300 段是《铃兰令》，别把它并进残篇里
        scenes=[s for s in nv.SCENES if 200 <= s["id"] < 300],
        final="青囊异闻录_残篇授书_配音版.mp4",
    ),
    "linglan": dict(
        title=("《青囊异闻录》", "第二章 · 铃兰令 · 角色台词配音"),
        scenes=[s for s in nv.SCENES if 300 <= s["id"] < 400],
        final="青囊异闻录_铃兰令_配音版.mp4",
    ),
    "fight": dict(
        title=("《新小说演示》", "司马谷岩之战 · 角色台词配音"),
        scenes=None,   # 延迟导入 novel_fight_demo
        final="新小说演示_司马谷岩之战_配音版.mp4",
    ),
}


def add_silent_audio(video: Path, out: Path) -> bool:
    """给无音轨视频补一条静音音轨，便于后续 concat 对齐。"""
    return nv.run_ff([
        nv.FF, "-y", "-i", str(video),
        "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
        "-c:v", "copy", "-c:a", "aac", "-shortest", str(out)])


def mux_one(video: Path, audio: Path, out: Path) -> bool:
    """旁白混音：配音长于视频则冻结末帧补足（保动作原生节奏 + 保全部台词）。"""
    vd = nv.get_duration(video)
    ad = nv.get_duration(audio)
    if ad > vd + 0.05:
        filt = f"[0:v]tpad=stop_mode=clone:stop_duration={ad-vd:.3f}[v]"
        return nv.run_ff([
            nv.FF, "-y", "-i", str(video), "-i", str(audio),
            "-filter_complex", filt, "-map", "[v]", "-map", "1:a",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
            "-r", "24", str(out)])
    else:
        return nv.run_ff([
            nv.FF, "-y", "-i", str(video), "-i", str(audio),
            "-map", "0:v", "-map", "1:a",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
            "-r", "24", "-shortest", str(out)])


def split_line(lines: str):
    """把 "角色名：台词" 拆成 (角色名, 台词)；台词去掉「」引号，只念文字本身。"""
    if not lines:
        return "", ""
    speaker, sep, content = lines.partition("：")
    if not sep:
        return "", speaker.strip().strip("「」")
    return speaker.strip(), content.strip().strip("「」")


async def gen_dialogue(text: str, out: Path, voice: str, mood: str, intensity: int) -> float:
    """合成【角色台词】语音（is_narration=False，不按旁白腔念）。"""
    return await main.generate_tts(
        text, str(out), voice=voice, engine="stepfun",
        mood=mood, intensity=intensity, is_narration=False)


async def build(target: str, nosub: bool = False, reuse_audio: bool = False):
    """配音成片。

    nosub=True       → 不烧屏显字幕，只出干净画面 + 配音（成片名带「_无字幕」）
    reuse_audio=True → 复用已存在的 _dlg_<镜号>.mp3，不再调 TTS 接口
                       （重出无字幕版时用：台词没变，没必要再合成一遍）
    """
    m = MANIFESTS[target]
    scenes = m["scenes"]
    if scenes is None:   # fight: 延迟导入，避免循环
        import novel_fight_demo
        scenes = novel_fight_demo.SCENES
    print(f"=== 阶跃星辰配音：{target}（{len(scenes)} 幕）===", flush=True)

    title_card = nv.make_title_card(*m["title"], secs=3.0)
    title_w = nv.OUT / "_title_voiced.mp4"
    add_silent_audio(title_card, title_w)

    voiced = []
    for s in scenes:
        sid = s["id"]
        final_clip = nv.OUT / f"scene_{sid:03d}_final.mp4"
        if not final_clip.exists():
            print(f"  [跳过] 场景{sid} 缺成片 {final_clip.name}（先去渲染）", flush=True)
            continue
        # 屏显：背景介绍(nar) + 角色台词(lines) 都要上屏（台词被念出来，画面上看不见就很怪）
        speaker, line = split_line(s.get("lines", ""))  # 角色台词：朗读对象

        # 1) 叠屏显文字（nosub 时跳过，直接用原始场景片）
        if nosub:
            src_clip = final_clip
        else:
            bg = nv.scene_subtitle(s)
            subbed = nv.OUT / f"_voicesub_{sid:03d}.mp4"
            src_clip = nv.overlay_subtitle(final_clip, bg, subbed)
            print(f"  [场景{sid}] 屏显(背景+台词): {bg.replace(chr(10), ' / ')}", flush=True)
        out_clip = nv.OUT / f"scene_{sid:03d}_voiced.mp4"

        # 2) 有台词才配音；台词念文字本身（不带角色名与引号）
        dur = None
        if line:
            mp3 = nv.OUT / f"_dlg_{sid:03d}.mp3"
            cached = reuse_audio and mp3.exists() and mp3.stat().st_size > 5000
            if cached:
                dur = nv.get_duration(mp3)
                print(f"       └ 复用已合成台词音频 {mp3.name} ({dur:.2f}s)", flush=True)
            else:
                v = castlib.voice_for(speaker, sid)     # 查资产表：角色 → 音色/情绪/强度
                voice, mood, intensity = v["voice"], v["mood"], v["intensity"]
                print(f"       └ 配音(台词) [{v['speaker'] or '角色'} · {voice} · {mood} · 强度{intensity}]: {line}", flush=True)
                try:
                    dur = await gen_dialogue(line, mp3, voice, mood, intensity)
                except Exception as e:
                    print(f"       [TTS] 台词合成失败: {str(e)[:160]}（该幕转静音）", flush=True)
            if dur is not None and mux_one(src_clip, mp3, out_clip):
                voiced.append(out_clip)
                print(f"       [混音] 场景{sid} 台词配音版 -> {out_clip.name}", flush=True)
                continue

        # 3) 无台词（或合成失败）→ 补静音轨，保证 concat 对齐
        print(f"       └ 无台词，补静音轨", flush=True)
        if add_silent_audio(src_clip, out_clip):
            voiced.append(out_clip)
        else:
            print(f"       [混音] 场景{sid} 静音轨失败，保留原片", flush=True)

    if not voiced:
        print("  [合成] 没有任何可配音场景，退出", flush=True)
        return None

    # 合成：标题卡(静音轨) + 各配音幕，concat 重编码
    inputs = [str(title_w)] + [str(p) for p in voiced]
    fc = "".join(f"[{i}:v][{i}:a]" for i in range(len(inputs)))
    filt = f"{fc}concat=n={len(inputs)}:v=1:a=1[outv][outa]"
    fname = m["final"]
    if nosub:
        # 与带字幕版严格区分文件名，绝不覆盖
        fname = fname.replace("_配音版.mp4", "_无字幕_配音版.mp4")
    final = nv.OUT / fname
    ok = nv.run_ff([
        nv.FF, "-y", *sum((["-i", p] for p in inputs), []),
        "-filter_complex", filt, "-map", "[outv]", "-map", "[outa]",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
        "-r", "24", str(final)])
    if ok and final.exists():
        print(f"  [合成] 配音成片 -> {final} ({final.stat().st_size//1024}KB)", flush=True)
        return final
    print("  [合成] concat 失败", flush=True)
    return None


def main_cli():
    argv = sys.argv[1:]
    flags = {a for a in argv if a.startswith("--")}
    pos = [a for a in argv if not a.startswith("--")]
    target = pos[0] if pos else "qingnang"
    if target not in MANIFESTS:
        print("用法: add_stepfun_tts.py [qingnang|shoushu|linglan|fight] [--nosub] [--reuse-audio]")
        print("      --nosub        不烧屏显字幕（成片名带「_无字幕」）")
        print("      --reuse-audio  复用已有 _dlg_<镜号>.mp3，不重复调 TTS")
        raise SystemExit(1)
    print("[info] 引擎:", main._select_tts_engine(), "端点:", main._get_stepfun_tts_url())
    res = asyncio.run(build(target,
                            nosub="--nosub" in flags,
                            reuse_audio="--reuse-audio" in flags))
    if res:
        print("[done]", res)
    else:
        print("[done] 未产出（检查上文错误）")


if __name__ == "__main__":
    main_cli()
