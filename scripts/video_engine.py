"""
Video Engine — 统一视频生成调度 (v12.0)
支持 7 种视频模式，智能路由，自动降级。
被 main.py 的 _generate_scene_impl 调用，通过依赖注入获取 workflow 和 ComfyUI 客户端。

模式列表:
  1. cloud_t2v  — 云端文生视频（最高质量）
  2. ltx_t2v    — LTX 文生视频（纯文本驱动，无需参考图）
  3. wan21      — Wan2.1 图生视频（高质量，需大显存）
  4. dual_frame — 首尾帧双图 LTX（运动可控）
  5. multi_shot — 多镜头拼接（3段不同构图，叙事推进）
  6. ltx_single — LTX 单帧图生视频（默认本地路径）
  7. ken_burns  — FFmpeg zoompan 推拉摇移（零成本兜底）
  8. parallax   — 三层视差动画（需 SAM 预处理）
"""
import asyncio, subprocess, sys, os, json, copy, random, shutil, re
from pathlib import Path

PROJECT_DIR = Path(__file__).parent

from app.config import (
    WAN21_BLOCKS_TO_SWAP,
    WAN21_FPS,
    WAN21_FRAMES,
    WAN21_HEIGHT,
    WAN21_STEPS,
    WAN21_WIDTH,
)
FFMPEG = os.environ.get("FFMPEG_PATH") or shutil.which("ffmpeg") or "ffmpeg"
FFPROBE = os.environ.get("FFPROBE_PATH") or shutil.which("ffprobe") or "ffprobe"

# v12.4: 严格视频模式 —— 开启后，真视频引擎失败时【拒绝】降级为 ken_burns
# （ken_burns 是静态图+推拉，画面内容不动，交付级出片不应混入）
# .env 设 STRICT_VIDEO_MODE=1 启用
_STRICT_VIDEO_MODE = os.environ.get("STRICT_VIDEO_MODE", "0").strip().lower() in ("1", "true", "yes", "on")


# ─── 模式1: 云端文生视频 ──────────────────────────────────

async def _cloud_t2v(scene, scene_dir, job, ctx):
    token = os.environ.get("CLOUD_VIDEO_TOKEN", "")
    if not token: return ""

    from cloud_video import generate as cloud_gen
    prompt = getattr(scene, 'image_prompt', '')[:300] or getattr(scene, 'description', '')[:200]
    if len(prompt) < 20: return ""

    output = str(scene_dir / f"scene_{scene.id:03d}_cloud.mp4")
    ok = await asyncio.get_event_loop().run_in_executor(None, cloud_gen, prompt, output)
    if ok and Path(output).exists() and Path(output).stat().st_size > 10000:
        return output
    return ""


# LTX 22B 图生视频固定使用的 checkpoint（fp8，约29GB，靠 CPU/RAM 卸载在 8.5GB 显存上跑）。
# 注意：LTX 工作流的 CheckpointLoaderSimple / LTXVAudioVAELoader / LTXAVTextEncoderLoader
# 只接受这个 LTX 模型名；绝不能把图生图用的 job.vid_checkpoint（如 RealVisXL）填进去，
# 否则 ComfyUI 报 "Value not in list: ckpt_name" 校验失败 → prompt 被拒 → 路由静默回退 Ken Burns。
LTX_CHECKPOINT = "ltx-2.3-22b-dev-fp8.safetensors"


# ─── 模式2: LTX 文生视频 (T2V) ────────────────────────────

async def _ltx_t2v(scene, scene_dir, job, ctx):
    """LTX 文生视频 — 纯文本驱动，跳过图片生成"""
    comfyui = ctx.get("comfyui")
    lw = ctx.get("load_workflow")
    fw = ctx.get("fill_workflow")
    if not comfyui or not lw or not fw:
        return ""

    prompt = getattr(scene, 'video_prompt', '') or getattr(scene, 'image_prompt', '')
    if not prompt or len(prompt) < 10:
        return ""

    try:
        t2v_template = lw("txt2vid_ltx") if lw("txt2vid_ltx") else None
        if not t2v_template:
            return ""

        vid_seed = random.randint(0, 2**32 - 1)
        workflow = fw(t2v_template, {
            "POSITIVE_PROMPT": prompt,
            "NEGATIVE_PROMPT": getattr(scene, 'negative_prompt', '') or "low quality, blurry, deformed",
            "CHECKPOINT": LTX_CHECKPOINT,
            "TEXT_ENCODER": "gemma_3_12B_it_fpmixed.safetensors",
            "SEED": vid_seed,
            "WIDTH_BASE": 768,
            "HEIGHT_BASE": 1344,
            "LENGTH": 33,
            "FRAME_RATE": 24,
            "FILENAME_PREFIX": f"novel2vid/scene_{scene.id:03d}",
        })
        pid = await comfyui.submit_workflow(workflow)
        res = await comfyui.wait_for_result_ws(pid, job_id=job.id, scene_id=scene.id, timeout=3600)

        finder = ctx.get("find_output_file")
        if not finder:
            return ""
        vf, vs, _ = finder(res.get("outputs", {}), prefer_types=["videos", "gifs", "images"])
        if vf:
            lv = await comfyui.download_output(vf, vs, save_dir=scene_dir)
            if Path(lv).exists() and Path(lv).stat().st_size > 10000:
                return lv
    except Exception as e:
        print(f"[VideoEngine] LTX-T2V 失败: {str(e)[:100]}", flush=True)
    return ""


# ─── 模式3: Wan2.1 图生视频 ───────────────────────────────

async def _wan21(scene, scene_dir, job, ctx):
    """Wan2.1 图生视频 — 高质量，需大显存"""
    if not getattr(job, 'use_wan21', False):
        return ""

    comfyui = ctx.get("comfyui")
    lw = ctx.get("load_workflow")
    fw = ctx.get("fill_workflow")
    if not comfyui or not lw or not fw:
        return ""

    local_img = getattr(scene, 'image_path', None)
    if not local_img or local_img == "__T2V_SKIPPED__":
        return ""
    if not Path(local_img).exists():
        return ""

    vid_base_prompt = ctx.get("vid_base_prompt", "")
    max_retries = 2

    for attempt in range(max_retries + 1):
        try:
            uploaded_name = await comfyui.upload_image(local_img)
            vid_seed = random.randint(0, 2**32 - 1)
            wan21_template = lw("img2vid_wan21")
            workflow = fw(wan21_template, {
                "POSITIVE_PROMPT": vid_base_prompt or getattr(scene, 'video_prompt', ''),
                "NEGATIVE_PROMPT": getattr(scene, 'negative_prompt', '') or
                    "low quality, blurry, deformed, extra fingers, bad anatomy, watermark, text",
                "WAN21_T5_ENCODER": job.wan21_t5_encoder,
                "WAN21_VAE": job.wan21_vae,
                "WAN21_MODEL": job.wan21_model,
                "WAN21_CLIP_VISION": job.wan21_clip_vision,
                "INPUT_IMAGE": uploaded_name,
                "SEED": vid_seed,
                "WIDTH": WAN21_WIDTH,
                "HEIGHT": WAN21_HEIGHT,
                "LENGTH": WAN21_FRAMES,
                "FRAME_RATE": WAN21_FPS,
                "STEPS": WAN21_STEPS,
                "BLOCKS_TO_SWAP": WAN21_BLOCKS_TO_SWAP,
                "FILENAME_PREFIX": f"novel2vid/scene_{scene.id:03d}",
            })
            pid = await comfyui.submit_workflow(workflow)
            res = await comfyui.wait_for_result_ws(pid, job_id=job.id, scene_id=scene.id, timeout=1800)

            finder = ctx.get("find_output_file")
            if not finder:
                return ""
            vf, vs, _ = finder(res.get("outputs", {}), prefer_types=["gifs", "videos"])
            if vf:
                lv = await comfyui.download_output(vf, vs, save_dir=scene_dir)
                if Path(lv).exists() and Path(lv).stat().st_size > 10000:
                    return lv

            if attempt < max_retries:
                await asyncio.sleep((attempt + 1) * 5)
        except Exception as e:
            if attempt < max_retries:
                print(f"[VideoEngine] Wan2.1 重试 {attempt+1}: {str(e)[:80]}", flush=True)
                await asyncio.sleep((attempt + 1) * 5)
            else:
                print(f"[VideoEngine] Wan2.1 失败: {str(e)[:80]}", flush=True)
                break
    return ""


# ─── 模式4: 3层视差 ─────────────────────────────────────

async def _parallax(scene, scene_dir, job, ctx):
    layers = getattr(scene, 'parallax_layers', None)
    if not layers or len(layers) < 3: return ""
    if not all(Path(p).exists() for p in layers[:3]): return ""

    script = PROJECT_DIR / "parallax.py"
    if not script.exists(): return ""

    output = str(scene_dir / f"scene_{scene.id:03d}_parallax.mp4")
    result = await asyncio.get_event_loop().run_in_executor(
        None, lambda: subprocess.run(
            [sys.executable, str(script)] + layers[:3] + [output, "8"],
            capture_output=True, timeout=60
        )
    )
    if result.returncode == 0 and Path(output).exists(): return output
    return ""


# ─── 模式5: Ken Burns ────────────────────────────────────

async def _ken_burns(scene, scene_dir, job, ctx):
    """Ken Burns 推拉摇移 (FFmpeg zoompan) — 100% 稳定, 无 AI 漂移。"""
    kb_func = ctx.get("ken_burns_func")
    if not kb_func: return ""

    img = getattr(scene, 'image_path', None)
    if not img or not Path(img).exists(): return ""
    if img == "__T2V_SKIPPED__": return ""

    job_id = getattr(job, 'id', '')
    return await kb_func(img, scene, scene_dir, job_id)


# ─── 模式6: 双帧 LTX ────────────────────────────────────

async def _dual_frame(scene, scene_dir, job, ctx):
    if not getattr(job, 'use_dual_frame', False): return ""

    comfyui = ctx.get("comfyui"); lw = ctx.get("load_workflow"); fw = ctx.get("fill_workflow")
    if not comfyui or not lw or not fw: return ""

    local_img = getattr(scene, 'image_path', None)
    end_img = getattr(scene, 'end_image_path', None)
    if not local_img or not end_img: return ""
    if local_img == "__T2V_SKIPPED__" or not Path(local_img).exists(): return ""

    vid_base_prompt = ctx.get("vid_base_prompt", "")
    scene_frames = ctx.get("scene_frames", 97)

    try:
        start_uploaded = await comfyui.upload_image(local_img)
        end_uploaded = await comfyui.upload_image(end_img)
        vid_seed = random.randint(0, 2**32 - 1)
        dual_template = lw("img2vid_ltx_dual")
        workflow = fw(dual_template, {
            "POSITIVE_PROMPT": vid_base_prompt,
            "NEGATIVE_PROMPT": getattr(scene, 'negative_prompt', '') or "low quality, blurry, deformed",
            "CHECKPOINT": LTX_CHECKPOINT,
            "INPUT_IMAGE_START": start_uploaded,
            "INPUT_IMAGE_END": end_uploaded,
            "SEED": vid_seed,
            "WIDTH_BASE": 960,
            "HEIGHT_BASE": 1728,
            # [v2 全面修复·混合短片段] LTX 22B 在 8GB 显存下无法生成长视频
            # （强行匹配配音时长会卡死数小时）。改为短片段(≤33帧≈1.4s)，
            # 再由 combine_audio_video 循环填充到完整配音时长。
            "LENGTH": min(int(scene_frames), 33),
            "FRAME_RATE": 24,
            "FILENAME_PREFIX": f"novel2vid/scene_{scene.id:03d}",
            "LORA_NAME": "ltx-2.3-22b-distilled-lora-384.safetensors",
            "VAE_NAME": LTX_CHECKPOINT,
            "TEXT_ENCODER": "gemma_3_12B_it_fpmixed.safetensors",
            "UPSCALE_MODEL": "ltx-2.3-spatial-upscaler-x2-1.0.safetensors",
        })
        pid = await comfyui.submit_workflow(workflow)
        res = await comfyui.wait_for_result_ws(pid, job_id=job.id, scene_id=scene.id, timeout=1800)

        finder = ctx.get("find_output_file")
        if not finder: return ""
        vf, vs, _ = finder(res.get("outputs", {}), prefer_types=["videos", "gifs"])
        if vf:
            lv = await comfyui.download_output(vf, vs, save_dir=scene_dir)
            if Path(lv).exists() and Path(lv).stat().st_size > 10000:
                return lv
    except Exception as e:
        print(f"[VideoEngine] 双帧失败: {str(e)[:80]}", flush=True)
    return ""


# ─── 模式7: 多镜头拼接 ───────────────────────────────────

async def _multi_shot(scene, scene_dir, job, ctx):
    """多镜头 img2vid — 3段不同构图视频拼接，实现叙事推进"""
    if not getattr(job, 'use_multi_shot', False):
        return ""

    comfyui = ctx.get("comfyui"); lw = ctx.get("load_workflow"); fw = ctx.get("fill_workflow")
    if not comfyui or not lw or not fw: return ""

    local_img = getattr(scene, 'image_path', None)
    if not local_img or local_img == "__T2V_SKIPPED__":
        return ""
    if not Path(local_img).exists():
        return ""

    vid_base_prompt = ctx.get("vid_base_prompt", "")
    scene_frames = ctx.get("scene_frames", 97)
    job_id = getattr(job, 'id', '')
    img2vid_template = lw("img2vid")
    merge_func = ctx.get("merge_videos_func")

    try:
        from PIL import Image
        img = Image.open(local_img)
        w, h = img.size

        shot_configs = [
            {"name": "wide", "crop": (0, 0, w, h),
             "camera": "very slow cinematic push in, wide establishing shot, atmospheric"},
            {"name": "mid", "crop": (int(w*0.08), int(h*0.06), int(w*0.84), int(h*0.88)),
             "camera": "slow cinematic push in, medium shot, elegant composition"},
            {"name": "close", "crop": (int(w*0.12), int(h*0.1), int(w*0.76), int(h*0.8)),
             "camera": "gentle slow push in, intimate detail shot, atmospheric lighting"},
        ]

        shot_videos = []
        for si, sc in enumerate(shot_configs):
            crop_img = img.crop(sc["crop"]).resize((960, 1728), Image.LANCZOS)
            crop_path = str(scene_dir / f"scene_{scene.id:03d}_shot{si+1}.png")
            crop_img.save(crop_path, "PNG")

            uploaded = await comfyui.upload_image(crop_path)
            vid_seed = random.randint(0, 2**32 - 1)
            shot_prompt = f"{vid_base_prompt}, {sc['camera']}"

            workflow = fw(img2vid_template, {
                "POSITIVE_PROMPT": shot_prompt,
                "NEGATIVE_PROMPT": getattr(scene, 'negative_prompt', '') or "low quality, blurry, deformed",
                "CHECKPOINT": LTX_CHECKPOINT,
                "TEXT_ENCODER": "gemma_3_12B_it_fpmixed.safetensors",
                "INPUT_IMAGE": uploaded,
                "SEED": vid_seed,
                "WIDTH_BASE": 960,
                "HEIGHT_BASE": 1728,
                "LENGTH": scene_frames,
                "FRAME_RATE": 24,
                "FILENAME_PREFIX": f"novel2vid/scene_{scene.id:03d}_ms{si+1}",
            })
            pid = await comfyui.submit_workflow(workflow)
            res = await comfyui.wait_for_result_ws(pid, job_id=job_id, scene_id=scene.id, timeout=1800)

            finder = ctx.get("find_output_file")
            if not finder: break
            vf, vs, _ = finder(res.get("outputs", {}), prefer_types=["videos", "gifs", "images"])
            if vf:
                lv = await comfyui.download_output(vf, vs, save_dir=scene_dir)
                if Path(lv).exists() and Path(lv).stat().st_size > 10000:
                    shot_videos.append(lv)

        if len(shot_videos) >= 2 and merge_func:
            concat_path = str(scene_dir / f"scene_{scene.id:03d}_concat.mp4")
            await merge_func(shot_videos, concat_path)
            if Path(concat_path).exists():
                return concat_path
        elif len(shot_videos) == 1:
            return shot_videos[0]
    except Exception as e:
        print(f"[VideoEngine] 多镜头失败: {str(e)[:80]}", flush=True)
    return ""


# ─── 模式8: 单帧 LTX ────────────────────────────────────

def _build_ltx_camera_directive(scene) -> str:
    """v12.2: 将分镜/运镜(中文)翻译为 LTX 2.3 可理解的英文运镜指令。
    LTX 的 gemma I2V 编码器据提示词中的 camera 描述生成真实运动，
    因此把 shot_size + camera 写进视频正提示词即可驱动真实运镜（无需额外 LoRA）。"""
    shot = (getattr(scene, 'shot_size', '') or '')
    cam = (getattr(scene, 'camera', '') or '')
    parts = []
    # 景别
    if any(k in shot for k in ['特写', 'close']):
        parts.append("close-up shot")
    elif any(k in shot for k in ['近景', 'medium close']):
        parts.append("medium close-up shot")
    elif any(k in shot for k in ['中景', 'medium']):
        parts.append("medium shot")
    elif any(k in shot for k in ['全景', '远景', '广角', 'wide', 'establishing']):
        parts.append("wide establishing shot")
    # 运镜（输出英文，避免 LTX 误解中文；同时匹配中文关键词）
    cl = cam.lower()
    if any(k in cl for k in ['推', 'push', 'dolly in', '前推', 'zoom in']):
        parts.append("the camera slowly pushes in")
    elif any(k in cl for k in ['拉', 'pull', 'dolly out', '拉远', 'zoom out']):
        parts.append("the camera slowly pulls out")
    if any(k in cl for k in ['横移', '跟拍', 'pan', '平移', 'track', '推镜']):
        parts.append("the camera pans horizontally following the subject")
    if any(k in cl for k in ['环绕', 'orbit', 'circle', '绕']):
        parts.append("the camera slowly orbits around the subject")
    if any(k in cl for k in ['摇', 'tilt']):
        parts.append("the camera tilts")
    if any(k in cl for k in ['升', 'crane', 'jib up', '上移']):
        parts.append("the camera rises")
    if any(k in cl for k in ['降', 'jib down', '下移']):
        parts.append("the camera descends")
    # 去重保序
    seen = set(); out = []
    for p in parts:
        if p not in seen:
            seen.add(p); out.append(p)
    return "; ".join(out)


async def _ltx_single(scene, scene_dir, job, ctx):
    comfyui = ctx.get("comfyui"); lw = ctx.get("load_workflow"); fw = ctx.get("fill_workflow")
    if not comfyui or not lw or not fw: return ""

    img = getattr(scene, 'image_path', None)
    if not img or img == "__T2V_SKIPPED__": return ""
    if not Path(img).exists(): return ""

    vid_base_prompt = ctx.get("vid_base_prompt", "")
    preserve = ctx.get("preserve_first_frame", True)
    if preserve:
        vid_base_prompt = (vid_base_prompt + ". locked camera, subtle micro motion, keep first frame composition and character identity").strip()
    else:
        cam_dir = _build_ltx_camera_directive(scene)
        if cam_dir:
            vid_base_prompt = (vid_base_prompt + ". " + cam_dir).strip()
    scene_frames = ctx.get("scene_frames", 97)
    img2vid_template = lw("img2vid")

    try:
        uploaded_name = await comfyui.upload_image(img)
        vid_seed = random.randint(0, 2**32 - 1)
        workflow = fw(img2vid_template, {
            "POSITIVE_PROMPT": vid_base_prompt,
            "NEGATIVE_PROMPT": getattr(scene, 'negative_prompt', '') or (
                "low quality, worst quality, blurry, deformed, watermark, text, "
                "extra digits, fewer digits, cropped, ugly, duplicate, "
                "morbid, mutilated, out of frame, mutation, deformed, "
                "bad anatomy, bad proportions, missing arms, missing legs, "
                "extra limbs, fused fingers, too many fingers, "
                "long neck, username, watermark, signature"
            ),
            "CHECKPOINT": LTX_CHECKPOINT,
            "TEXT_ENCODER": "gemma_3_12B_it_fpmixed.safetensors",
            "INPUT_IMAGE": uploaded_name,
            "SEED": vid_seed,
            "WIDTH_BASE": 960,
            "HEIGHT_BASE": 1728,
            # [v2 全面修复·混合短片段] LTX 22B 在 8GB 显存下无法生成长视频
            # （强行匹配配音时长会卡死数小时）。改为短片段(≤33帧≈1.4s)，
            # 再由 combine_audio_video 循环填充到完整配音时长。
            "LENGTH": min(int(scene_frames), 33),
            "FRAME_RATE": 24,
            "FILENAME_PREFIX": f"novel2vid/scene_{scene.id:03d}",
        })
        pid = await comfyui.submit_workflow(workflow)
        res = await comfyui.wait_for_result_ws(pid, job_id=job.id, scene_id=scene.id, timeout=3600)

        finder = ctx.get("find_output_file")
        if not finder: return ""
        vf, vs, _ = finder(res.get("outputs", {}), prefer_types=["videos", "gifs", "images"])
        if vf:
            lv = await comfyui.download_output(vf, vs, save_dir=scene_dir)
            if Path(lv).exists() and Path(lv).stat().st_size > 10000:
                return lv
    except Exception as e:
        print(f"[VideoEngine] LTX 单帧失败: {str(e)[:80]}", flush=True)
    return ""


# ─── 调度器 ─────────────────────────────────────────────

# 所有可用模式
async def _wan_a14b(scene, scene_dir, job, ctx) -> str:
    """Wan 2.2 I2V-A14B 稳定管线（参考图强化角色一致性）。"""
    import asyncio, shutil
    from pathlib import Path
    from engines.wan import WanEngine
    from engines.base import GenerateRequest
    scene_dir = Path(scene_dir)
    kf = scene_dir / "keyframe.png"
    # 关键帧/首帧兜底：常见命名
    if not kf.exists():
        for cand in ("first_frame.png", "start.png", "kf.png"):
            if (scene_dir / cand).exists():
                kf = scene_dir / cand
                break
    if not kf.exists():
        # 从目录里挑一张 png
        pngs = sorted(scene_dir.glob("*.png"))
        if not pngs:
            return _ken_burns(scene, scene_dir, job, ctx)
        kf = pngs[0]
    # 角色参考图（人设锁定）
    ref = None
    for cand in ("reference.png", "character.png", "char_ref.png"):
        if (scene_dir / cand).exists():
            ref = scene_dir / cand
            break
    prompt = getattr(scene, "video_prompt", None) or getattr(scene, "description", "") or ""
    target = _scene_target_seconds(scene, job)
    # A14B 单次上限约 3s（81 帧）；按目标时长等分多段，末帧接力，最后无损拼接
    count = max(1, int(target / 3.0) + (1 if target % 3.0 else 0))
    seg_duration = round(target / count, 2)
    segs = [seg_duration] * count
    print(f"[VideoEngine] 场景 {getattr(scene, 'id', '?')}: Wan2.2 A14B GGUF "
          f"目标 {target:.1f}s，分 {count} 段 × {seg_duration}s（Lightx2v 4-step）", flush=True)

    engine = WanEngine(
        lora_high=[{"name": "wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise.safetensors", "strength": 3.0}],
        lora_low=[{"name": "wan2.2_i2v_lightx2v_4steps_lora_v1_low_noise.safetensors", "strength": 1.5}],
    )
    clips, first_frame = [], kf
    for idx, dur in enumerate(segs):
        req = GenerateRequest(
            prompt=prompt, first_frame=first_frame,
            reference_images=[ref] if (ref and idx == 0) else [],
            width=384, height=672, duration_seconds=dur, fps=24,
            seed=20261117 + idx * 7919,
            output_dir=scene_dir,
            output_name=("wan_a14b" if count == 1 else f"wan_a14b_seg{idx + 1:02d}"),
            timeout_seconds=2500,
        )
        clip = await engine.generate(req)
        if not clip or not Path(clip.video_path).exists():
            raise RuntimeError(f"A14B 第 {idx + 1} 段无输出")
        clips.append(Path(clip.video_path))
        if idx < count - 1:
            nxt = scene_dir / f"wan_a14b_seg{idx + 1:02d}_last.png"
            first_frame = nxt if _extract_last_frame(clips[-1], nxt) else kf
    if count == 1:
        return str(clips[0])
    out = scene_dir / "wan_a14b.mp4"
    if _concat_wan5b_clips(clips, out):
        return str(out)
    return str(clips[0])


def _scene_target_seconds(scene, job=None) -> float:
    """估算该镜头真正需要的视频时长（秒）。

    修复硬编码 2.0s 导致的「2 秒视频循环 9 次填满 17 秒配音」问题：
    取 ①已知配音时长 ②字幕字数估算 ③分镜标称时长 三者最大值。
    Edge-TTS 中文约 3.9 个有效字/秒，实测 67 个有效字 ≈ 17s，误差很小。
    """
    try:
        audio_dur = float(getattr(scene, "audio_duration", 0) or 0)
    except (TypeError, ValueError):
        audio_dur = 0.0

    declared = 0.0
    m = re.search(r"(\d+(?:\.\d+)?)\s*s", str(getattr(scene, "duration", "") or ""), re.I)
    if m:
        declared = float(m.group(1))

    text = str(getattr(scene, "subtitle_text", "") or "").strip()
    if not text:
        text = str(getattr(scene, "description", "") or "")[:80]
    chars = len(re.sub(r"[\s，。！？、；：,.!?;:…—-]", "", text))
    estimated = chars / 3.9 if chars else 0.0

    target = max(audio_dur, estimated, declared, 1.4)
    return min(target, 24.0)  # 最多 6 段 × 4s，防止极端长文本拖垮出片


def _split_wan5b_segments(target: float) -> list:
    """把目标时长切成 Wan5B 单次可生成的片段（引擎上限约 4s）。"""
    segs, left = [], target
    while left > 0.05:
        seg = min(4.0, left)
        segs.append(round(seg, 2))
        left -= seg
    return segs or [2.0]


def _extract_last_frame(video, out_png) -> bool:
    """取上一段的末帧作为下一段首帧，保证多段之间视觉连续。"""
    try:
        cmd = [FFMPEG, "-y", "-v", "error", "-sseof", "-0.6",
               "-i", str(video), "-frames:v", "1", str(out_png)]
        return subprocess.run(cmd, timeout=120,
                              stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL).returncode == 0 and Path(out_png).exists()
    except Exception:
        return False


def _concat_wan5b_clips(clips: list, output) -> bool:
    """无损拼接同规格分段视频。"""
    try:
        listing = output.parent / f"{output.stem}_concat.txt"
        listing.write_text("".join(f"file '{p.resolve().as_posix()}'\n" for p in clips),
                           encoding="utf-8")
        cmd = [FFMPEG, "-y", "-v", "error", "-f", "concat", "-safe", "0",
               "-i", str(listing), "-c", "copy", str(output)]
        return subprocess.run(cmd, timeout=300,
                              stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL).returncode == 0 and output.exists()
    except Exception:
        return False


async def _wan5b(scene, scene_dir, job, ctx) -> str:
    """Wan 2.2 TI2V-5B 轻量图生视频（8GB 显存稳定）。

    按镜头真实时长分段生成（每段 ≤4s），末帧接力下一段，最后无损拼接；
    不再固定生成 2 秒再靠后期循环填满整条配音。
    """
    from pathlib import Path
    from engines.wan5b import Wan5BEngine
    from engines.base import GenerateRequest
    scene_dir = Path(scene_dir)
    kf = scene_dir / "keyframe.png"
    if not kf.exists():
        for cand in ("first_frame.png", "start.png", "kf.png"):
            if (scene_dir / cand).exists():
                kf = scene_dir / cand
                break
    if not kf.exists():
        pngs = sorted(scene_dir.glob("*.png"))
        if not pngs:
            return ""
        kf = pngs[0]
    prompt = getattr(scene, "video_prompt", None) or getattr(scene, "description", "") or ""

    target = _scene_target_seconds(scene, job)
    segs = _split_wan5b_segments(target)
    print(f"[VideoEngine] 场景 {getattr(scene, 'id', '?')}: Wan5B 目标 {target:.1f}s，"
          f"分 {len(segs)} 段 {segs}", flush=True)

    clips = []
    first_frame = kf
    max_retries = 2
    for idx, dur in enumerate(segs):
        ok, last_err = False, ""
        for attempt in range(max_retries + 1):
            try:
                req = GenerateRequest(
                    prompt=prompt, first_frame=first_frame,
                    width=704, height=1280, duration_seconds=dur, fps=24,
                    seed=(20261116 + idx * 7919 + attempt * 104729) if len(segs) > 1
                         else (None if attempt == 0 else 1000 + attempt * 7919),
                    output_dir=scene_dir,
                    output_name=("wan5b" if len(segs) == 1 else f"wan5b_seg{idx + 1:02d}"),
                    timeout_seconds=2400,
                )
                clip = await Wan5BEngine().generate(req)
                if clip and getattr(clip, "video_path", None) and Path(clip.video_path).exists():
                    clips.append(Path(clip.video_path))
                    ok = True
                    break
                last_err = "引擎返回空结果"
            except Exception as e:
                last_err = f"{type(e).__name__}: {str(e)[:120]}"
                print(f"[VideoEngine] Wan5B 第{idx + 1}段第{attempt + 1}次失败: {last_err}", flush=True)
            if attempt < max_retries:
                await asyncio.sleep((attempt + 1) * 5)
        if not ok:
            scene.error_msg = f"wan5b 第{idx + 1}段失败（{last_err}）"
            return ""
        if idx < len(segs) - 1:
            nxt = scene_dir / f"wan5b_seg{idx + 1:02d}_last.png"
            first_frame = nxt if _extract_last_frame(clips[-1], nxt) else kf

    if len(clips) == 1:
        return str(clips[0])
    out = scene_dir / "wan5b.mp4"
    if _concat_wan5b_clips(clips, out):
        return str(out)
    scene.error_msg = "wan5b 分段拼接失败，仅保留第一段"
    return str(clips[0])


async def _agnes_flash(scene, scene_dir, job, ctx) -> str:
    """Agnes Video 2.5 Flash 云端文生视频（4–12 秒/次，长镜头分段拼接）。"""
    from pathlib import Path
    from engines.agnes import AgnesVideoEngine
    from engines.base import GenerateRequest

    scene_dir = Path(scene_dir)
    prompt = getattr(scene, "video_prompt", None) or getattr(scene, "description", "") or ""
    target = _scene_target_seconds(scene, job)
    count = max(1, int(target / 12.0) + (1 if target % 12.0 else 0))
    seg_duration = round(target / count, 2)
    print(f"[VideoEngine] 场景 {getattr(scene, 'id', '?')}: Agnes Video 2.5 Flash "
          f"目标 {target:.1f}s，分 {count} 段 × {seg_duration}s", flush=True)

    engine = AgnesVideoEngine()
    clips = []
    for idx in range(count):
        req = GenerateRequest(
            prompt=prompt,
            first_frame=None,
            width=720, height=1280,
            duration_seconds=seg_duration,
            fps=24,
            seed=(20261118 + idx * 7919),
            output_dir=scene_dir,
            output_name=("agnes_flash" if count == 1 else f"agnes_flash_seg{idx + 1:02d}"),
            timeout_seconds=900,
        )
        clip = await engine.generate(req)
        if not clip or not Path(clip.video_path).exists():
            raise RuntimeError(f"Agnes 第 {idx + 1} 段无输出")
        clips.append(Path(clip.video_path))
    if count == 1:
        return str(clips[0])
    out = scene_dir / "agnes_flash.mp4"
    if _concat_wan5b_clips(clips, out):
        return str(out)
    return str(clips[0])


_ILLUSTRATION_TOKENS = [
    "professional illustration", "award-winning artwork", "concept art", "digital painting",
    "illustration", "artwork", "painting", "anime", "cartoon", "3d render", "cgi",
    "drawing", "sketch", "masterpiece", "best quality", "ultra detailed", "8k uhd",
    "intricate details", "sharp focus",
]


def _photoreal_prompt(text: str, for_video: bool = False) -> str:
    """把分镜里泛滥的插画风格词换成真人实拍电影感提示词。"""
    p = str(text or "")
    for token in _ILLUSTRATION_TOKENS:
        p = re.sub(r"(?i)\b" + re.escape(token) + r"\b[,，]?\s*", "", p)
    p = re.sub(r"\s{2,}", " ", p).strip(" ,，.。")
    if for_video:
        prefix = ("photorealistic live-action cinematic video, real human skin and fabric texture, "
                  "practical lighting, natural physically plausible motion, smooth continuous movement, "
                  "subtle camera drift, 35mm film look, ")
        suffix = ", no illustration, no painting, no anime, no cartoon, no CGI, no morphing"
    else:
        prefix = ("photorealistic live-action film still, real human skin and fabric texture, "
                  "practical lighting, shallow depth of field, 35mm film look, ")
        suffix = ", no illustration, no painting, no anime, no cartoon, no CGI"
    return prefix + p + suffix


async def _local_qwen_keyframe(scene, scene_dir, prompt: str) -> Path:
    """用本地 ComfyUI + Qwen-Image 2.1 生成关键帧，不调用云端文生图。"""
    import json as _json
    import random as _random
    import scripts.main as _main

    wf = _main.load_workflow("txt2img_qwen21")
    raw = _json.dumps(wf, ensure_ascii=False)
    raw = (raw.replace("{{POSITIVE_PROMPT}}", prompt)
              .replace("{{NEGATIVE_PROMPT}}", "low quality, blurry, distorted, deformed, watermark, text")
              .replace("{{SEED}}", str(_random.randint(1, 2**31 - 1)))
              .replace("{{WIDTH}}", "736")
              .replace("{{HEIGHT}}", "1312"))
    wf = _json.loads(raw)
    pid = await _main.comfyui.submit_workflow(wf)
    result = await _main.comfyui.wait_for_result_ws(pid, timeout=1200)
    for node_out in result.get("outputs", {}).values():
        for img in node_out.get("images", []):
            saved = await _main.comfyui.download_output(
                img.get("filename", ""), img.get("subfolder", ""),
                img.get("type", "output"), save_dir=Path(scene_dir))
            print(f"[LocalKeyframe] Qwen-Image 2.1: {saved}", flush=True)
            return Path(saved)
    raise RuntimeError("Qwen 关键帧工作流没有返回图片")


async def _keyframe_url_from_local(local_path: Path, img_engine, scene_dir: Path) -> str:
    """把本地关键帧变成 Agnes 视频可用的 URL：走图生图中转拿公网 URL。"""
    import base64
    local_path = Path(local_path)
    # Step 1 输出是 1080×1920，先等比缩到 736×1312 再上传，减少 Base64 体积和接口超时
    src_w, src_h = 1080, 1920
    if src_w / src_h > 736 / 1312:
        src_h = int(src_w * 1312 / 736)
    else:
        src_w = int(src_h * 736 / 1312)
    scaled = Path(scene_dir) / "agnes_keyframe_upload.png"
    try:
        from PIL import Image
        with Image.open(local_path) as im:
            im.convert("RGB").resize((736, 1312), Image.LANCZOS).save(scaled)
        local_path = scaled
    except Exception as _e:
        print(f"[LocalKeyframe] 缩放失败，使用原图: {str(_e)[:80]}", flush=True)
    mime = "image/png" if str(local_path).lower().endswith(".png") else "image/jpeg"
    data_uri = f"data:{mime};base64,{base64.b64encode(local_path.read_bytes()).decode()}"
    print("[LocalKeyframe] 经 Agnes 图生图中转获取公网 URL", flush=True)
    try:
        hosted = await img_engine.generate(
            "keep this exact image, no changes, identical composition and lighting",
            width=736, height=1312,
            output_path=scene_dir / "agnes_keyframe_hosted.png",
            input_image=local_path,
        )
        url = hosted.get("url") or data_uri
        print(f"[LocalKeyframe] 已取得可访问 URL: {str(url)[:70]}…", flush=True)
        return url
    except Exception as exc:
        print(f"[LocalKeyframe] 中转失败，回退 Data URI: {str(exc)[:100]}", flush=True)
        return data_uri


async def _agnes_i2v(scene, scene_dir, job, ctx) -> str:
    """Agnes 文生图 → 图生视频：每张关键帧拿到公网 URL 后作为 first_frame。"""
    from pathlib import Path
    from engines.agnes_image import AgnesImageEngine
    from engines.agnes import AgnesVideoEngine
    from engines.base import GenerateRequest

    scene_dir = Path(scene_dir)
    image_prompt = _photoreal_prompt(
        getattr(scene, "image_prompt", "") or getattr(scene, "description", ""), for_video=False)
    video_prompt = _photoreal_prompt(
        getattr(scene, "video_prompt", "") or getattr(scene, "description", ""), for_video=True)
    # v13.3: 把本镜字幕/对白注入视频提示词，让画面动作与字幕对齐。
    # 原 video_prompt 只写运镜和环境（"subtle push-in, rain pouring"），不含说话/手势，
    # 导致成片人物动作对不上字幕。这里抽取对白与关键词，显式要求口型与手势表演。
    subtitle = str(getattr(scene, "subtitle_text", "") or "").strip()
    if subtitle:
        dialogue = re.sub(r"[\r\n]+", " ", subtitle)
        # 只取引号内的纯对白；没有引号时去掉「角色：」前缀后用整句
        quoted = re.findall(r"[「\"“']([^」\"”']+)[」\"”']", dialogue)
        if quoted:
            dialogue = " ".join(q.strip() for q in quoted if q.strip())
        else:
            dialogue = re.sub(r"^[^：:]{1,8}[：:]", "", dialogue)
        if len(dialogue) > 120:
            dialogue = dialogue[:120]
        video_prompt = (
            f"{video_prompt}, the character visibly speaks the line '{dialogue}' "
            "with natural lip movement and matching facial expression and hand gestures, "
            "mouth opening and closing in sync with speech, believable dialogue performance"
        )
    target = _scene_target_seconds(scene, job)
    count = max(1, int(target / 12.0) + (1 if target % 12.0 else 0))
    seg_duration = round(target / count, 2)
    print(f"[VideoEngine] 场景 {getattr(scene, 'id', '?')}: Agnes 文生图→图生视频 "
          f"目标 {target:.1f}s，分 {count} 段 × {seg_duration}s", flush=True)

    img_engine = AgnesImageEngine()
    vid_engine = AgnesVideoEngine()
    use_local = os.environ.get("LOCAL_KEYFRAME", "0").strip().lower() in ("1", "true", "yes", "on")

    # ── 关键帧只生成一次：优先复用 Step 1 已精选的 scene.image_path ──
    # Step 1 已做角色锚定、环境锚定、多 seed 质量评分；此处若再出图会丢弃这些成果，
    # 且本地 Qwen 每帧要 3-4 分钟。只有直接调用本函数（如冒烟脚本）没有 Step 1 时才现场出图。
    existing = getattr(scene, "image_path", None)
    if existing and Path(existing).exists():
        local_kf = Path(existing)
        print(f"[VideoEngine] 复用 Step 1 关键帧: {local_kf.name}（不再二次出图）", flush=True)
    elif use_local:
        print("[VideoEngine] 无 Step 1 关键帧，本地 Qwen-Image 2.1 现场出图", flush=True)
        local_kf = await _local_qwen_keyframe(scene, scene_dir, image_prompt)
    else:
        local_kf = None

    if local_kf is not None:
        first_url = await _keyframe_url_from_local(local_kf, img_engine, scene_dir)
    else:
        result = await img_engine.generate(
            image_prompt, width=736, height=1312,
            output_path=scene_dir / "agnes_keyframe.png",
        )
        first_url = result["url"]
    print(f"[VideoEngine] 关键帧来源 URL: {str(first_url)[:70]}…", flush=True)

    clips = []
    for idx in range(count):
        req = GenerateRequest(
            prompt=video_prompt,
            first_frame=None,
            first_frame_url=first_url,
            width=720, height=1280,
            duration_seconds=seg_duration,
            fps=24,
            seed=20261118 + idx * 7919,
            output_dir=scene_dir,
            output_name=("agnes_i2v" if count == 1 else f"agnes_i2v_seg{idx + 1:02d}"),
            timeout_seconds=1800,
        )
        clip = await vid_engine.generate(req)
        if not clip or not Path(clip.video_path).exists():
            raise RuntimeError(f"Agnes I2V 第 {idx + 1} 段无输出")
        clips.append(Path(clip.video_path))
        if idx < count - 1:
            last = scene_dir / f"agnes_i2v_seg{idx + 1:02d}_last.png"
            if _extract_last_frame(clips[-1], last):
                nxt = await img_engine.generate(
                    "same scene and characters, the next moment, natural continuation, "
                    "keep composition and lighting consistent",
                    width=736, height=1312,
                    output_path=scene_dir / f"agnes_keyframe_{idx + 2:02d}.png",
                    input_image=last,
                )
                first_url = nxt["url"]
    if count == 1:
        return str(clips[0])
    out = scene_dir / "agnes_i2v.mp4"
    if _concat_wan5b_clips(clips, out):
        return str(out)
    return str(clips[0])


VIDEO_MODES = {
    "cloud_t2v":  _cloud_t2v,
    "ltx_t2v":    _ltx_t2v,
    "wan21":      _wan21,
    "dual_frame": _dual_frame,
    "multi_shot": _multi_shot,
    "ltx_single": _ltx_single,
    "parallax":   _parallax,
    "ken_burns":  _ken_burns,
    "wan_i2v":    _wan_a14b,
    "wan_i2v_gguf": _wan_a14b,
    "a14b_gguf":  _wan_a14b,
    "wan5b":      _wan5b,
    "agnes_flash": _agnes_flash,
    "agnes":      _agnes_flash,
    "agnes_i2v":  _agnes_i2v,
}


def _classify_scene_video_mode(scene, job=None) -> str:
    """智能路由：默认 LTX 为主引擎；Ken Burns 仅用于无人物的大场景推拉/定场空镜 + 最终兜底。

    路由规则（v12.2 更新：用户要求 LTX 22B 为主，KB 只负责大场景推拉）：
      - 无人物 / 纯环境 / 全景·远景·广角等大场景 → Ken Burns（稳定、零成本推拉）
      - 其余（有角色、对白、动作、情绪）→ LTX（真视频运动）

    Returns:
        'ltx' | 'ken_burns' | 'dual_frame' | 'cloud'
    """
    desc = (getattr(scene, 'description', '') or '').lower()
    camera = (getattr(scene, 'camera', '') or '').lower()
    shot_size = (getattr(scene, 'shot_size', '') or '').lower()
    chars = getattr(scene, 'characters', '') or ''
    video_prompt = getattr(scene, 'video_prompt', '') or ''

    # 无人物场景标记
    no_char_markers = ["无", "无角色", "本镜未出场", "未出场", "环境开场"]
    is_env = any(m in str(chars) for m in no_char_markers) or not str(chars).strip()
    # 大场景推拉（定场空镜）
    big_shot = any(k in shot_size for k in ['全景', '远景', '广角', '大场景',
                                            'establishing', 'wide', 'panorama'])

    # 无人物 / 纯环境 / 大场景 → Ken Burns 推拉
    if is_env or big_shot:
        return 'ken_burns'

    # 其余默认 Wan 5B（有角色、对白、动作、情绪都走真视频；
    # 用户选定 Wan 2.2 TI2V-5B 为生产主引擎，8GB 稳定且首帧忠实度高）
    return 'wan5b'


def _is_static_video(path: str) -> bool:
    """检测视频是否静态（帧数 < 24）"""
    try:
        pr = subprocess.run(
            [FFPROBE, '-v', 'quiet', '-count_frames', '-select_streams', 'v:0',
             '-show_entries', 'stream=nb_read_frames', '-of', 'csv=p=0', path],
            capture_output=True, text=True, errors="replace", timeout=15
        )
        nframes = int(pr.stdout.strip() or 0)
        return nframes < 24
    except Exception:
        return False


async def dispatch(scene, scene_dir, ctx: dict) -> str:
    """统一视频生成调度入口。

    ctx 需要包含:
        - comfyui: ComfyUIClient 实例
        - job: JobState 实例
        - load_workflow: 加载工作流模板的函数
        - fill_workflow: 填充工作流参数的函数
        - ken_burns_func: Ken Burns 生成函数
        - find_output_file: 查找输出文件的函数
        - vid_base_prompt: 视频提示词
        - scene_frames: 视频帧数
        - merge_videos_func: 视频合并函数（多镜头模式用）

    返回视频文件路径，失败返回空字符串。
    """
    job = ctx.get("job")
    mode = getattr(job, 'video_mode', 'local') if job else 'local'
    local_img = getattr(scene, 'image_path', None)
    intensity = getattr(scene, 'emotional_intensity', 5)
    camera = (getattr(scene, 'camera', '') or '').lower()
    desc = (getattr(scene, 'description', '') or '').lower()
    action_kws = ['跑', '冲', '追', '打', '摔', '爆炸', '撞', '飞',
                  'jump', 'run', 'fight', 'chase', 'explosion', 'attack']
    is_action = any(kw in desc or kw in camera for kw in action_kws)

    # ── T2V 模式：纯文生视频，跳过图片 ──
    if mode == "ltx_t2v":
        print(f"[VideoEngine] 场景 {scene.id}: LTX-T2V 文生视频模式", flush=True)
        r = await _ltx_t2v(scene, scene_dir, job, ctx)
        if r:
            scene.video_mode_used = "ltx_t2v"
            return r
        # T2V 失败，降级到 Ken Burns（如果有图片）
        if local_img and local_img != "__T2V_SKIPPED__" and Path(local_img).exists():
            r = await _ken_burns(scene, scene_dir, job, ctx)
            if r:
                scene.video_mode_used = "ken_burns"
                return r
        return ""

    # ── Cloud T2V 模式 ──
    if mode == "cloud_t2v":
        r = await _cloud_t2v(scene, scene_dir, job, ctx)
        if r:
            scene.video_mode_used = "cloud_t2v"
            return r
        # 云端失败，继续走本地路径

    # ── Agnes 文生图 → 图生视频（公网 URL 首帧）──
    if mode == "agnes_i2v":
        print(f"[VideoEngine] 场景 {scene.id}: Agnes 文生图→图生视频模式", flush=True)
        try:
            r = await _agnes_i2v(scene, scene_dir, job, ctx)
            if r:
                scene.video_mode_used = "agnes_i2v"
                scene.error_msg = ""
                return r
        except Exception as e:
            print(f"[VideoEngine] Agnes I2V 失败({str(e)[:120]})，回退本地 Wan5B", flush=True)
        r = await _wan5b(scene, scene_dir, job, ctx)
        if r:
            scene.video_mode_used = "wan5b"
            scene.error_msg = ""
            return r
        return ""

    # ── Agnes Video 2.5 Flash 云端模式（文生视频，不占本地显存）──
    if mode in ("agnes_flash", "agnes"):
        print(f"[VideoEngine] 场景 {scene.id}: Agnes Video 2.5 Flash 云端模式", flush=True)
        try:
            r = await _agnes_flash(scene, scene_dir, job, ctx)
            if r:
                scene.video_mode_used = "agnes_flash"
                scene.error_msg = ""
                return r
        except Exception as e:
            print(f"[VideoEngine] Agnes 失败({str(e)[:120]})，回退本地 Wan5B", flush=True)
        r = await _wan5b(scene, scene_dir, job, ctx)
        if r:
            scene.video_mode_used = "wan5b"
            scene.error_msg = ""
            return r
        return ""

    # ── Wan 2.2 A14B GGUF 低显存模式（Q4_K_M 双专家 + Lightx2v 4-step）──
    if mode in ("wan_i2v_gguf", "a14b_gguf"):
        print(f"[VideoEngine] 场景 {scene.id}: Wan 2.2 A14B GGUF 模式", flush=True)
        r = await _wan_a14b(scene, scene_dir, job, ctx)
        if r:
            scene.video_mode_used = "wan_i2v_gguf"
            scene.error_msg = ""
            return r
        if local_img and local_img != "__T2V_SKIPPED__" and Path(local_img).exists():
            r = await _ken_burns(scene, scene_dir, job, ctx)
            if r:
                scene.video_mode_used = "ken_burns"
                return r
        return ""

    # ── Wan 2.2 I2V 稳定管线模式 ──
    if mode == "wan_i2v":
        print(f"[VideoEngine] 场景 {scene.id}: Wan 2.2 I2V 稳定管线模式", flush=True)
        r = await _wan_a14b(scene, scene_dir, job, ctx)
        if r:
            scene.video_mode_used = "wan_i2v"
            return r
        # Wan 失败，降级到 Ken Burns（如果有图片）
        if local_img and local_img != "__T2V_SKIPPED__" and Path(local_img).exists():
            r = await _ken_burns(scene, scene_dir, job, ctx)
            if r:
                scene.video_mode_used = "ken_burns"
                return r
        return ""

    # ── v12.0: 智能路由 — 根据场景特征选择主用引擎 ──
    if mode == "wan5b":
        print(f"[VideoEngine] 场景 {scene.id}: Wan 2.2 TI2V-5B 模式", flush=True)
        r = await _wan5b(scene, scene_dir, job, ctx)
        if r:
            scene.video_mode_used = "wan5b"
            scene.error_msg = ""   # 重试后成功，清除此前记录的失败原因
            return r
        # Wan 5B 失败，降级到 Ken Burns（如果有图片）
        # v12.4: 严格模式下宁可整条失败，也不产出「静态图+推拉」的假视频
        reason = getattr(scene, "error_msg", "") or "wan5b 失败（原因未记录）"
        if _STRICT_VIDEO_MODE and local_img and local_img != "__T2V_SKIPPED__" and Path(local_img).exists():
            scene.error_msg = f"{reason}｜严格模式：已拒绝降级，请修复后重跑该场景"
            print(f"[VideoEngine] 场景 {scene.id}: {scene.error_msg}", flush=True)
            return ""
        if local_img and local_img != "__T2V_SKIPPED__" and Path(local_img).exists():
            r = await _ken_burns(scene, scene_dir, job, ctx)
            if r:
                scene.video_mode_used = "ken_burns"
                # v12.4: 降级必须留痕，避免出片后才发现混着静态图
                scene.error_msg = f"{reason}｜已降级 ken_burns（静态图+推拉，画面内容不动）"
                print(f"[WARN] 场景 {scene.id} 降级为 ken_burns: {reason}", flush=True)
                return r
        return ""

    # ── v12.0: 智能路由 — 根据场景特征选择主用引擎 ──
    primary = _classify_scene_video_mode(scene, job)
    print(f"[VideoEngine] 场景 {scene.id}: 路由={primary} (mood={getattr(scene, 'mood', '')} "
          f"intensity={intensity} camera={camera[:15]})", flush=True)

    # 构建尝试顺序
    if primary == 'wan5b':
        ordered = ['wan5b', 'ltx_single', 'ken_burns']
    elif primary == 'ltx':
        ordered = ['wan21', 'ltx_single', 'ken_burns', 'dual_frame', 'parallax']
    elif primary == 'dual_frame' and job and getattr(job, 'use_dual_frame', False):
        ordered = ['dual_frame', 'ltx_single', 'ken_burns']
    else:
        # primary='ken_burns' 或默认 — 先 Ken Burns（快、稳），失败回退 LTX
        ordered = ['ken_burns', 'ltx_single', 'parallax']

    # 插入 multi_shot 到 LTX 之前（如果启用）
    if job and getattr(job, 'use_multi_shot', False):
        if 'ltx_single' in ordered:
            idx = ordered.index('ltx_single')
            ordered.insert(idx, 'multi_shot')

    for name in ordered:
        func = VIDEO_MODES.get(name)
        if not func:
            continue
        # 跳过未启用的模式
        if name == 'dual_frame' and not (job and getattr(job, 'use_dual_frame', False)):
            continue
        if name == 'wan21' and not (job and getattr(job, 'use_wan21', False)):
            continue
        if name == 'multi_shot' and not (job and getattr(job, 'use_multi_shot', False)):
            continue
        if name == 'ken_burns' and not (job and getattr(job, 'use_ken_burns', False)):
            # Ken Burns 仅在启用时使用，或作为最后兜底
            if name != ordered[-1]:
                continue

        try:
            r = await func(scene, scene_dir, job, ctx)
            if r and Path(r).exists():
                # 验证视频不是静态（>=24 帧），但 Ken Burns 除外
                if name == 'ltx_single' and _is_static_video(r):
                    print(f"[VideoEngine] 场景 {scene.id}: LTX 输出静态，跳过回退", flush=True)
                    try:
                        Path(r).unlink()
                    except Exception:
                        pass
                    continue
                scene.video_mode_used = name
                print(f"[VideoEngine] 场景 {scene.id}: 使用 {name} → {r}", flush=True)
                return r
        except Exception as e:
            print(f"[VideoEngine] {name} 失败: {str(e)[:80]}", flush=True)
            continue

    # ── 最终兜底：Ken Burns（即使未启用，也尝试） ──
    if local_img and local_img != "__T2V_SKIPPED__" and Path(local_img).exists():
        kb_func = ctx.get("ken_burns_func")
        if kb_func and not is_action and intensity < 8:
            try:
                r = await _ken_burns(scene, scene_dir, job, ctx)
                if r and Path(r).exists():
                    scene.video_mode_used = "ken_burns"
                    print(f"[VideoEngine] 场景 {scene.id}: 最终兜底 Ken Burns", flush=True)
                    return r
            except Exception:
                pass

    return ""
