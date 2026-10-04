"""断点续跑状态机（对应 DramaClaw「虾条」任务中心的最小可用版）。

解决什么问题：
  以前每渲染一次都是"全量重来"，中途挂了只能手写一次性救火脚本（complete_fight101.py 之类）。
  现在每一步落盘记录：status / 参数指纹 / 产物路径。重跑自动跳过已完成且参数没变的步骤；
  改了 prompt 或参数（指纹变了）才重做那一步。

数据结构（output/novel_demo_v2/run_state.json）：
  {
    "job": "novel_v2",
    "steps": {
      "1.img":  {"status":"done","sig":"a1b2c3","artifacts":["output/.../scene_001.png"],"ts":...},
      "1.video":{"status":"failed","sig":"...","err":"..."}
    }
  }

用法：
  from run_state import RS
  if RS.is_done(1, "img", sig, [p]):
      ...跳过...
  RS.mark_done(1, "img", sig, [p])
  RS.mark_failed(1, "img", sig, "超时")

命令行：
  python scripts/run_state.py show
  python scripts/run_state.py reset 101        # 只重置场景 101
  python scripts/run_state.py reset --all
"""
from __future__ import annotations
import json, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PATH = ROOT / "output" / "novel_demo_v2" / "run_state.json"

MIN_BYTES = 5000   # 小于这个体积视为坏产物（ffmpeg 半成品常见）


class _State:
    def __init__(self, path: Path = DEFAULT_PATH, job: str = "novel_v2"):
        self.path = Path(path)
        self.job = job
        self.data = {"job": job, "steps": {}}
        self._load()

    # ---------- 持久化 ----------
    def _load(self):
        if self.path.exists():
            try:
                self.data = json.loads(self.path.read_text(encoding="utf-8"))
                self.data.setdefault("steps", {})
                self.data.setdefault("job", self.job)
            except Exception:
                pass

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---------- 查询 ----------
    @staticmethod
    def key(sid, step: str) -> str:
        return f"{sid}.{step}"

    def get(self, sid, step: str) -> dict:
        return self.data["steps"].get(self.key(sid, step), {})

    def _artifacts_ok(self, artifacts) -> bool:
        for a in artifacts or []:
            p = Path(a)
            if not p.exists() or p.stat().st_size < MIN_BYTES:
                return False
        return True

    def is_done(self, sid, step: str, sig: str, artifacts=None) -> bool:
        """已完成 + 参数没变 + 产物还在且不是半成品 = 可以跳过。"""
        e = self.get(sid, step)
        if e.get("status") != "done":
            return False
        if sig and e.get("sig") and e.get("sig") != sig:
            return False
        arts = artifacts if artifacts is not None else e.get("artifacts") or []
        return self._artifacts_ok(arts)

    # ---------- 写入 ----------
    def mark_done(self, sid, step: str, sig: str, artifacts=None):
        self.data["steps"][self.key(sid, step)] = {
            "status": "done", "sig": sig,
            "artifacts": [str(a) for a in (artifacts or [])],
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        self._save()

    def mark_failed(self, sid, step: str, sig: str, err: str = ""):
        self.data["steps"][self.key(sid, step)] = {
            "status": "failed", "sig": sig, "err": str(err)[:300],
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        self._save()

    def reset(self, sid=None):
        if sid is None:
            self.data["steps"] = {}
        else:
            for k in [k for k in self.data["steps"] if k.startswith(f"{sid}.")]:
                self.data["steps"].pop(k, None)
        self._save()

    # ---------- 展示 ----------
    def summary(self) -> str:
        done = sum(1 for v in self.data["steps"].values() if v.get("status") == "done")
        fail = sum(1 for v in self.data["steps"].values() if v.get("status") == "failed")
        return f"{self.path}  共 {len(self.data['steps'])} 步：完成 {done}，失败 {fail}"

    def show(self):
        print(self.summary())
        for k in sorted(self.data["steps"], key=lambda x: (int(x.split(".")[0]), x)):
            v = self.data["steps"][k]
            mark = {"done": "OK  ", "failed": "FAIL"}.get(v.get("status"), "??  ")
            extra = v.get("err") or ", ".join(Path(a).name for a in (v.get("artifacts") or []))
            print(f"  [{mark}] {k:<12} sig={v.get('sig','-'):<12} {v.get('ts','')}  {extra}")


RS = _State()


def _cli():
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "show"
    if cmd == "show":
        RS.show()
    elif cmd == "reset":
        arg = sys.argv[2] if len(sys.argv) > 2 else "--all"
        RS.reset(None if arg == "--all" else int(arg))
        print("已重置:", arg)
    else:
        print(__doc__)


if __name__ == "__main__":
    _cli()
