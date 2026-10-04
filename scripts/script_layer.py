"""剧本层：小说 → 剧本（结构 + 爽点 + 校验）→ 分镜。

为什么要这一层（这是对照资源包后差距最大的一项）：
  以前是「小说 → DeepSeek 分镜」一步到位，中间没有剧本，于是没有起承转合、没有钩子、
  也没有任何校验——出片即交付。现在中间加一层：先定结构与爽点，再落分镜，交付前过校验。

剧本文件结构（json，放在 story/ 下）：
{
  "title": "青囊异闻录·雨夜药铺",
  "structure": {
    "hook":      "一句话钩子：观众为什么看下去",
    "beats": [   {"id":"b1","name":"入场","purpose":"交代处境","hook":"悬念点","emotion":"疲惫→警觉"} ],
    "爽点":  [   {"at":"b4","type":"反转","desc":"墙上医图的人像他"} ]
  },
  "scenes": [
    {"id":1,"beat":"b1","title":"雷雨叩门","dur":2.5,
     "nar":"背景描写（不配音，只屏显）",
     "lines":"角色台词（要配音）",
     "camera":"push_in_then_hold",        # 取自 prompts/camera.md
     "micro":"",                          # 取自 prompts/micro_expression.md，可空
     "cast":["叶玄机"],
     "img":"首帧提示词","img_end":"尾帧提示词"}
  ]
}

命令行：
  python scripts/script_layer.py check  story/青囊_剧本.json    # 逻辑校验
  python scripts/script_layer.py scenes story/青囊_剧本.json    # 导出 SCENES（可直接喂 novel_video）
"""
from __future__ import annotations
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import cast as castlib
import promptbank


# ---------- 载入 ----------

def load_script(path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


# ---------- 校验（对应资源包的「逻辑校验清单」） ----------

def check(script: dict) -> list:
    """返回 [(level, msg)]，level ∈ ERROR / WARN / INFO。"""
    out = []
    st = script.get("structure") or {}
    scenes = script.get("scenes") or []

    if not st.get("hook"):
        out.append(("ERROR", "缺 structure.hook —— 没有钩子，观众不知道为什么看下去"))
    if not st.get("beats"):
        out.append(("ERROR", "缺 structure.beats —— 没有节拍，故事没有起承转合"))
    if not (st.get("爽点") or st.get("shuangdian")):
        out.append(("WARN", "没有标爽点 —— 平铺直叙，短剧会没人看完"))
    if not scenes:
        out.append(("ERROR", "没有分镜"))
        return out

    beat_ids = {b.get("id") for b in (st.get("beats") or [])}
    for i, s in enumerate(scenes, 1):
        sid = s.get("id", i)
        # 1) 节拍引用
        if s.get("beat") and beat_ids and s["beat"] not in beat_ids:
            out.append(("ERROR", f"场景{sid} 引用了不存在的 beat: {s.get('beat')}"))
        # 2) 静音可懂：背景文字是唯一能让静音观众看懂的东西
        if not (s.get("nar") or "").strip():
            out.append(("WARN", f"场景{sid} 没有 nar —— 静音播放时这一幕看不懂在演什么"))
        # 3) 角色锁定
        for name in (s.get("cast") or []):
            if name not in castlib.characters():
                out.append(("ERROR", f"场景{sid} 的角色「{name}」不在 assets/cast.json 里 —— 会串脸"))
        # 4) 声线：有台词就必须有音色
        lines = (s.get("lines") or "").strip()
        if lines:
            speaker = lines.split("：")[0]
            v = castlib.voice_for(speaker, sid)
            if not v.get("voice"):
                out.append(("ERROR", f"场景{sid} 说话人「{speaker}」没有配声线"))
        # 5) 运镜：必须来自词典
        cam = s.get("camera")
        if cam and not promptbank.get("camera", cam):
            out.append(("WARN", f"场景{sid} 的运镜「{cam}」不在 prompts/camera.md 里 —— 建议先加进词典"))
        mic = s.get("micro")
        if mic and not promptbank.get("micro_expression", mic):
            out.append(("WARN", f"场景{sid} 的微表情「{mic}」不在 prompts/micro_expression.md 里"))
        # 6) 因果链：从第二幕起，检查是否承接上一幕
        if i > 1:
            prev = scenes[i - 2]
            if (s.get("beat") == prev.get("beat")) and (s.get("nar") or "")[:8] == (prev.get("nar") or "")[:8]:
                out.append(("WARN", f"场景{sid} 与上一幕背景文字雷同 —— 可能重复叙事"))

    total = sum(float(s.get("dur") or 0) for s in scenes)
    if total < 8:
        out.append(("WARN", f"总时长 {total:.1f}s 偏短，短剧建议 10~20s"))
    if total > 25:
        out.append(("WARN", f"总时长 {total:.1f}s 偏长，前几秒留不住人"))
    out.append(("INFO", f"共 {len(scenes)} 幕，总时长 {total:.1f}s，"
                       f"节拍 {len(st.get('beats') or [])} 个，"
                       f"爽点 {len(st.get('爽点') or [])} 个"))
    return out


# ---------- 导出成分镜 ----------

def to_scenes(script: dict, with_cast: bool = True, with_style: bool = True) -> list:
    """把剧本导出成 novel_video.SCENES 兼容的结构。

    vid 提示词 = 运镜词条 + 微表情词条（都从 prompts/ 词典取），不再手写。
    img / img_end = 底稿 + 角色外貌(with_cast) + 全片风格(with_style)。
    """
    out = []
    for i, s in enumerate(script.get("scenes") or [], 1):
        sid = int(s.get("id", i))
        cam = promptbank.get("camera", s.get("camera", ""), "")
        mic = promptbank.get("micro_expression", s.get("micro", ""), "")
        vid_parts = [p for p in (cam, mic) if p]
        vid = ", ".join(vid_parts) if vid_parts else "slow push in toward the subject, cinematic"
        out.append(dict(
            id=sid,
            title=s.get("title", f"场景{sid}"),
            dur=float(s.get("dur") or 2.5),
            img=castlib.build_prompt(sid, s.get("img", ""), with_cast, with_style),
            img_end=castlib.build_prompt(sid, s.get("img_end", ""), with_cast, with_style),
            vid=vid,
            nar=(s.get("nar") or "").strip(),
            lines=(s.get("lines") or "").strip(),
        ))
    return out


def _cli():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    path = sys.argv[2] if len(sys.argv) > 2 else None
    if not path:
        print(__doc__); return
    sc = load_script(path)
    if cmd == "check":
        for level, msg in check(sc):
            print(f"  [{level:<5}] {msg}")
    elif cmd == "scenes":
        print(json.dumps(to_scenes(sc), ensure_ascii=False, indent=2))
    else:
        print(__doc__)


if __name__ == "__main__":
    _cli()
