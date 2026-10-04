"""小说 → AI 短视频：主管线演示驱动器（分阶段执行）。

用法：
    python scripts/novel_demo.py storyboard   # 建任务 + 上传小说 + 生成分镜
    python scripts/novel_demo.py prompts      # 角色分析 + 对白拆分 + 生成提示词
    python scripts/novel_demo.py gen          # 出图 + 图生视频（长耗时）
    python scripts/novel_demo.py merge        # 合片（配音/BGM/字幕）
    python scripts/novel_demo.py status       # 查进度
    python scripts/novel_demo.py scenes       # 打印场景清单

job_id 存在 output/novel_demo_job.json，各阶段共享。
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8190"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
NOVEL_PATH = PROJECT_ROOT.parent / "demo_novel.txt"
STATE_FILE = PROJECT_ROOT / "output" / "novel_demo_job.json"
TIMEOUT = httpx.Timeout(1800, connect=30)


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {}


def save_state(st: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(st, ensure_ascii=False, indent=2),
                          encoding="utf-8")


def post(path: str, **kw) -> dict:
    with httpx.Client(timeout=TIMEOUT) as c:
        r = c.post(f"{BASE}{path}", **kw)
        r.raise_for_status()
        return r.json()


def get(path: str, **kw) -> dict:
    with httpx.Client(timeout=TIMEOUT) as c:
        r = c.get(f"{BASE}{path}", **kw)
        r.raise_for_status()
        return r.json()


# ───────────────────────────────────────────── 阶段 1：分镜
def stage_storyboard() -> None:
    st = load_state()
    job_id = st.get("job_id")
    if not job_id:
        job_id = post("/api/create-job")["job_id"]
        st["job_id"] = job_id
        save_state(st)
        print(f"[1/3] 建任务 job_id={job_id}")

    text = NOVEL_PATH.read_text(encoding="utf-8")
    res = post("/api/upload-text",
               data={"job_id": job_id, "text": text,
                     "novel_title": "青囊异闻录·雨夜药铺"})
    print(f"[2/3] 上传小说：{res['text_length']} 字")

    t0 = time.time()
    res = post("/api/generate-storyboard", params={"job_id": job_id, "bypass_safety": "true"})
    print(f"[3/3] 分镜生成完成，用时 {time.time() - t0:.1f}s")
    print(json.dumps(res, ensure_ascii=False)[:500])

    scenes = get(f"/api/scenes/{job_id}")
    st["scenes"] = scenes.get("scenes", scenes if isinstance(scenes, list) else [])
    save_state(st)
    print(f"\n共 {len(st['scenes'])} 个场景：")
    for s in st["scenes"]:
        print(f"  #{s.get('id')} {s.get('title', '')} | 情绪={s.get('mood', '')} "
              f"| 时长={s.get('duration', '')}s")


# ───────────────────────────────────────────── 阶段 2：提示词
def stage_prompts() -> None:
    st = load_state()
    job_id = st["job_id"]

    try:
        post("/api/analyze-characters", params={"job_id": job_id})
        print("[a] 角色分析完成")
    except Exception as e:
        print(f"[a] 角色分析跳过：{e}")
    try:
        post("/api/split-dialogues", params={"job_id": job_id})
        print("[b] 对白拆分完成")
    except Exception as e:
        print(f"[b] 对白拆分跳过：{e}")

    t0 = time.time()
    post("/api/generate-prompts", params={"job_id": job_id})
    print(f"[c] 提示词生成完成，用时 {time.time() - t0:.1f}s")

    scenes = get(f"/api/scenes/{job_id}")
    st["scenes"] = scenes.get("scenes", scenes if isinstance(scenes, list) else [])
    save_state(st)
    for s in st["scenes"]:
        ip = (s.get("image_prompt") or "")[:90]
        print(f"\n#{s.get('id')} {s.get('title','')}")
        print(f"   image_prompt: {ip}...")
        print(f"   camera: {(s.get('camera_prompt') or '')[:70]}")


# ───────────────────────────────────────────── 阶段 3：出图 + 视频
def stage_watch() -> None:
    """只轮询已在跑的任务（不重复触发 start-generation）。"""
    st = load_state()
    _poll(st["job_id"])


def stage_gen() -> None:
    st = load_state()
    job_id = st["job_id"]
    print(f"启动生成 job_id={job_id}（长耗时，后台轮询进度）")
    post("/api/start-generation", params={"job_id": job_id})
    _poll(job_id)


def _poll(job_id: str, max_seconds: int = 7200) -> None:
    t0 = time.time()
    last = ""
    while time.time() - t0 < max_seconds:
        try:
            s = get(f"/api/status/{job_id}")
        except Exception as e:
            print(f"  轮询失败：{e}")
            time.sleep(5)
            continue
        cur = json.dumps(s, ensure_ascii=False, sort_keys=True)
        if cur != last:
            p = s.get("progress", {})
            if isinstance(p, dict):
                line = (f"场景 {p.get('current', '?')}/{p.get('total', '?')} "
                        f"[{p.get('phase', '')}] scene_id={p.get('scene_id', '')} "
                        f"| done={s.get('done_count')} err={s.get('error_count')}")
            else:
                line = f"progress={p} step={s.get('current_step')}"
            print(f"  [{time.time()-t0:6.0f}s] {line}", flush=True)
            last = cur
        p = s.get("progress", {})
        pct = (p.get("current", 0) if isinstance(p, dict) else p) or 0
        total = (p.get("total", 0) if isinstance(p, dict) else 0) or 0
        stt = str(s.get("status", ""))
        if stt in ("completed", "done", "finished") or (total and pct >= total):
            print(f"\n✅ 生成完成，用时 {time.time() - t0:.0f}s")
            return
        time.sleep(10)
    print("⏱ 轮询超时（任务仍在后台跑，可用 status 继续查看）")


# ───────────────────────────────────────────── 阶段 4：合片
def stage_merge() -> None:
    st = load_state()
    job_id = st["job_id"]
    print(f"合并成片 job_id={job_id}")
    res = post(f"/api/merge-videos/{job_id}", params={"bgm_volume": 0.2})
    print(json.dumps(res, ensure_ascii=False)[:600])
    save_state(st)


def stage_status() -> None:
    st = load_state()
    print(json.dumps(get(f"/api/status/{st['job_id']}"), ensure_ascii=False, indent=2))


def stage_scenes() -> None:
    st = load_state()
    scenes = get(f"/api/scenes/{st['job_id']}")
    print(json.dumps(scenes, ensure_ascii=False, indent=2)[:8000])


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    {"storyboard": stage_storyboard, "prompts": stage_prompts, "gen": stage_gen,
     "watch": stage_watch, "merge": stage_merge, "status": stage_status,
     "scenes": stage_scenes}[cmd]()
