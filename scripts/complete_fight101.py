"""补做打斗片场景101（之前两次都因 ComfyUI 队列争用超时），
然后重合成 101+102，最后接阶跃星辰 StepFun 配音。

用法：
  python scripts/complete_fight101.py
"""
from __future__ import annotations
import sys, asyncio, time, zlib, json, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import novel_fight_demo as fd
import add_stepfun_tts as tts

COMFY = "http://127.0.0.1:8188"


def queue_state():
    try:
        d = json.load(urllib.request.urlopen(f"{COMFY}/queue", timeout=8))
        return len(d.get("queue_running", [])), len(d.get("queue_pending", []))
    except Exception:
        return -1, -1


def wait_queue_empty(timeout=120):
    t0 = time.time()
    while time.time() - t0 < timeout:
        r, p = queue_state()
        if r <= 0 and p == 0:
            return True
        print(f"  [等队列空] running={r} pending={p}，稍候…", flush=True)
        time.sleep(8)
    return False


def render_101():
    s = next(x for x in fd.SCENES if x["id"] == 101)
    final = fd.nv.OUT / f"scene_{s['id']:03d}_final.mp4"
    if final.exists():
        print("[skip] scene_101_final 已存在，跳过渲染", flush=True)
        return True
    seed = (zlib.crc32(f"fight_{s['id']}".encode()) % (2 ** 31)) + 1
    print("=== 补做 分镜101 逼前戏言（先等队列空）===", flush=True)
    wait_queue_empty(180)
    try:
        img = fd.nv.gen_image(s, seed, "img", "")
        end_img = fd.nv.gen_image(s, seed, "img_end", "_end")
        time.sleep(1)
        vpath = asyncio.run(fd.nv.gen_video(s, img, seed))
        fd.nv.land_end_frame(vpath, end_img, final)
        print(f"[ok] scene_101_final -> {final} ({final.stat().st_size//1024}KB)", flush=True)
        return True
    except Exception as e:
        print(f"[fail] 101: {str(e)[:240]}", flush=True)
        return False


def main():
    ok = render_101()
    print("=== 重合成 新小说演示 (101+102) ===", flush=True)
    fd.compose_demo([101, 102], "《新小说演示》", "司马谷岩之战 · 分镜→出图→图生视频")
    print("=== 接阶跃星辰 StepFun 配音 ===", flush=True)
    print("[info] 引擎:", tts.main._select_tts_engine(), "端点:", tts.main._get_stepfun_tts_url())
    asyncio.run(tts.build("fight"))
    print("=== ALL DONE ===", flush=True)


if __name__ == "__main__":
    main()
