"""提示词素材库加载器：读 prompts/*.md，把提示词从脚本里搬出来。

为什么要有这个：
  以前每镜的运镜、负面词、风格都是手写进 SCENES 的，写完一次就锁死在那个剧本里，
  下一部片子得从头再写一遍。现在统一放进 prompts/ 下四个词典：
    camera.md           运镜（推/拉/摇/移/跟/环绕/角度/组合）
    micro_expression.md 微表情（眼/唇/呼吸/手/眉）—— 短片只有2~3秒，全靠这个演戏
    style.md            影调与构图风格
    neg.md              负面词分档（base / face / costume / period …）

文件格式（普通 markdown 列表）：
    - push_in: slow push in toward the subject, languid pace —— 慢推，最常用

用法：
    from promptbank import get, list_keys
    get("camera", "push_in")            -> "slow push in toward the subject, languid pace"
    list_keys("camera")                 -> ["push_in", "push_in_fast", ...]

命令行：
    python scripts/promptbank.py list camera
    python scripts/promptbank.py get camera push_in
    python scripts/promptbank.py find 推
"""
from __future__ import annotations
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROMPTS = ROOT / "prompts"

_CACHE: dict = {}
_ITEM = re.compile(r"^-\s*([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.+)$")


def _parse(path: Path) -> dict:
    out = {}
    if not path.exists():
        return out
    mt = path.stat().st_mtime
    hit = _CACHE.get(path.name)
    if hit and hit["mtime"] == mt:
        return hit["data"]
    for line in path.read_text(encoding="utf-8").splitlines():
        m = _ITEM.match(line.strip())
        if not m:
            continue
        key, rest = m.group(1), m.group(2)
        text, _, desc = rest.partition("——")
        out[key] = {"text": text.strip().rstrip(","), "desc": desc.strip()}
    _CACHE[path.name] = {"mtime": mt, "data": out}
    return out


def kinds() -> list:
    return sorted(p.stem for p in PROMPTS.glob("*.md"))


def list_keys(kind: str) -> list:
    return list(_parse(PROMPTS / f"{kind}.md").keys())


def get(kind: str, key: str, default: str = "") -> str:
    """取英文提示词片段；找不到返回 default（默认空串，不污染 prompt）。"""
    return _parse(PROMPTS / f"{kind}.md").get(key, {}).get("text", default)


def desc(kind: str, key: str) -> str:
    return _parse(PROMPTS / f"{kind}.md").get(key, {}).get("desc", "")


def find(keyword: str, kind: str = "") -> list:
    """按中文说明或 key 模糊搜。"""
    res = []
    for k in ([kind] if kind else kinds()):
        for key, v in _parse(PROMPTS / f"{k}.md").items():
            if keyword in key or keyword in v["desc"] or keyword in v["text"]:
                res.append((k, key, v["desc"]))
    return res


def _cli():
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "list"
    if cmd == "list":
        for k in ([sys.argv[2]] if len(sys.argv) > 2 else kinds()):
            keys = list_keys(k)
            print(f"[{k}] {len(keys)} 条")
            for key in keys:
                print(f"  {key:<22} {desc(k, key)}")
    elif cmd == "get":
        print(get(sys.argv[2], sys.argv[3]) if len(sys.argv) > 3 else "用法: get <kind> <key>")
    elif cmd == "find":
        for k, key, d in find(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else ""):
            print(f"  {k}.{key:<22} {d}")
    else:
        print(__doc__)


if __name__ == "__main__":
    _cli()
