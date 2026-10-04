"""诊断 WanVideoImageToVideoEncode 在 Wan2.2-TI2V-5B 上的真实报错。
只跑一个场景的首尾双关键帧，提交后完整 dump execution_error（不截断）。
"""
import asyncio, json, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import httpx
from engines.base import GenerateRequest
from engines.wan5b import Wan5BEngine

COMFY = "http://127.0.0.1:8188"
OUT = ROOT / "output" / "novel_demo_v2"
START = OUT / "scene_001.png"
END = OUT / "scene_001_end.png"

W, H = 1280, 704

async def main():
    if not START.exists() or not END.exists():
        print("缺少关键帧图", flush=True); return
    eng = Wan5BEngine()
    seed = 12345
    frames = 57  # 2.5s * 24
    req = GenerateRequest(
        prompt="slow push in toward the young man, rain falling, cold lightning, cinematic",
        first_frame=START, width=W, height=H, duration_seconds=2.5, fps=24,
        seed=seed, negative_prompt="blurry, low quality, distorted",
        output_name="diag_i2venc", timeout_seconds=2400,
    )
    uploaded = await eng._upload_image(START)
    uploaded_end = await eng._upload_image(END)
    wf = eng._build_workflow(req, seed, frames, W, H, uploaded, uploaded_end)
    # 试验：FLF2V/Fun 模式（VAE 走普通 3 通道 encode 路径，规避 end_=True 的 12 通道崩溃）
    wf["i2venc"]["inputs"]["fun_or_fl2v_model"] = True
    print("[diag] 使用 fun_or_fl2v_model=True 模式", flush=True)
    # 提交
    async with httpx.AsyncClient(timeout=30, trust_env=False) as client:
        r = await client.post(f"{COMFY}/prompt", json={"prompt": wf},
                              headers={"Content-Type": "application/json"})
        if r.status_code != 200:
            print("提交失败", r.status_code, r.text[:500]); return
        pid = r.json()["prompt_id"]
    print(f"已提交 {pid}", flush=True)
    # 轮询并 dump 完整错误
    t0 = time.time()
    async with httpx.AsyncClient(timeout=15, trust_env=False) as client:
        while time.time() - t0 < 2400:
            try:
                h = await client.get(f"{COMFY}/history/{pid}")
                if h.status_code == 200:
                    data = h.json()
                    if pid in data:
                        entry = data[pid]
                        st = entry.get("status", {})
                        if st.get("status_str") == "error" or st.get("completed") is False and st.get("messages"):
                            print("=== COMFYUI ERROR ===", flush=True)
                            print(json.dumps(st.get("messages"), ensure_ascii=False, indent=2), flush=True)
                            # 找 execution_error 详情
                            for m in st.get("messages", []):
                                if isinstance(m, list) and len(m) > 1 and m[0] == "execution_error":
                                    print("--- execution_error ---", flush=True)
                                    print(json.dumps(m[1], ensure_ascii=False, indent=2), flush=True)
                            return
                        if st.get("completed"):
                            outs = entry.get("outputs", {})
                            print("=== 完成，输出节点 ===", flush=True)
                            print(json.dumps(outs, ensure_ascii=False)[:800], flush=True)
                            # 下载视频并抽取首/尾帧
                            vfile = None
                            for nid, o in outs.items():
                                if isinstance(o, dict):
                                    for gk in ("videos", "gifs", "images"):
                                        if isinstance(o.get(gk), list) and o[gk]:
                                            it = o[gk][0]
                                            vfile = (it["filename"], it.get("subfolder", ""), it.get("type", "output"))
                                            break
                                if vfile:
                                    break
                            if vfile:
                                import subprocess
                                dest = ROOT / "output" / "diag_i2venc.mp4"
                                async with httpx.AsyncClient(timeout=900, trust_env=False) as dl:
                                    r = await dl.get(f"{COMFY}/view", params={
                                        "filename": vfile[0], "subfolder": vfile[1], "type": vfile[2]})
                                    if r.status_code == 200:
                                        dest.write_bytes(r.content)
                                        ff = r"C:\Users\Mr.Wang\ffmpeg-shared\ffmpeg-master-latest-win64-gpl\bin\ffmpeg.exe"
                                        d0 = ROOT / "output" / "diag_frame0.png"
                                        d1 = ROOT / "output" / "diag_frame_last.png"
                                        subprocess.run([ff, "-y", "-i", str(dest), "-frames:v", "1",
                                                        "-vf", "select=eq(n\,0)", "-vsync", "vfr", str(d0)])
                                        subprocess.run([ff, "-y", "-sseof", "-0.1", "-i", str(dest),
                                                        "-frames:v", "1", str(d1)])
                                        print(f"已保存视频 {dest} ({dest.stat().st_size//1024}KB), "
                                              f"首帧 {d0.exists()}, 尾帧 {d1.exists()}", flush=True)
                            return
            except Exception as e:
                print("poll err", str(e)[:100], flush=True)
            await asyncio.sleep(3)
    print("超时", flush=True)

if __name__ == "__main__":
    asyncio.run(main())
