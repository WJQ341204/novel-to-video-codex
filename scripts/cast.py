"""全片资产表加载器（对应 DramaClaw「虾塘」的四类资产：角色 / 场景 / 道具 / 声线）。

单一数据源 = assets/cast.json。新增角色、改声线、调 IPAdapter 权重都只改那个文件，
脚本不再硬编码任何角色配置。

常用：
    from cast import voice_for, cast_of_shot, enrich_prompt, anchor_tokens

    voice_for("司马谷岩", 101)   -> {"engine":"stepfun","voice":"cixingnansheng","mood":"得意","intensity":7}
    cast_of_shot(101)            -> ["司马谷岩"]
    enrich_prompt(101, prompt)   -> prompt + 角色/场景锚点 token（一致性文本层锁定）

命令行：
    python scripts/cast.py show            # 打印四类资产
    python scripts/cast.py voice 司马谷岩 101
"""
from __future__ import annotations
import json, hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CAST_PATH = ROOT / "assets" / "cast.json"

_CACHE = {"mtime": None, "data": None}


def load(reload: bool = False) -> dict:
    """读资产表（按 mtime 缓存，改 json 立即生效）。"""
    if not CAST_PATH.exists():
        return {"characters": {}, "scenes": {}, "props": {}, "voices": {},
                "shot_cast": {}, "shot_overrides": {}, "defaults": {}}
    mt = CAST_PATH.stat().st_mtime
    if reload or _CACHE["data"] is None or _CACHE["mtime"] != mt:
        _CACHE["data"] = json.loads(CAST_PATH.read_text(encoding="utf-8"))
        _CACHE["mtime"] = mt
    return _CACHE["data"]


def defaults() -> dict:
    return load().get("defaults", {})


def characters() -> dict:
    return load().get("characters", {})


def scenes() -> dict:
    return load().get("scenes", {})


def props() -> dict:
    return load().get("props", {})


def char(name: str) -> dict:
    return characters().get(name, {})


def resolve_speaker(name: str) -> str:
    """按别名把「老者」「young man」之类的叫法归一到正式角色名。"""
    if not name:
        return ""
    for canon, cfg in characters().items():
        if name == canon or name in (cfg.get("alias") or []):
            return canon
    return name


def shot_overrides() -> dict:
    return load().get("shot_overrides", {})


def voice_for(speaker: str = "", sid: int | None = None) -> dict:
    """查声线：优先 shot_overrides[sid]，其次角色自带 voice，最后 defaults。

    返回 {"engine","voice","mood","intensity","speaker"}。
    """
    d = defaults()
    out = {
        "engine": d.get("engine", "stepfun"),
        "voice": d.get("voice", "cixingnansheng"),
        "mood": d.get("mood", "平静"),
        "intensity": d.get("intensity", 5),
        "speaker": speaker,
    }
    ov = shot_overrides().get(str(sid), {}) if sid is not None else {}
    if ov.get("speaker"):
        speaker = ov["speaker"]
    canon = resolve_speaker(speaker)
    cfg = char(canon) or load().get("voices", {}).get(canon, {})
    out["speaker"] = canon
    for k in ("engine", "voice", "mood", "intensity"):
        if cfg.get(k) is not None:
            out[k] = cfg[k]
    # 单镜覆写最高优先级（同一角色在不同镜可以有不同情绪）
    for k in ("voice", "mood", "intensity"):
        if ov.get(k) is not None:
            out[k] = ov[k]
    return out


def cast_of_shot(sid: int) -> list:
    return (load().get("shot_cast") or {}).get(str(sid), [])


def anchor_tokens(sid: int, include=("characters", "scenes")) -> str:
    """拼出该镜的锚点文本（角色外貌 + 场景），用于追加到 prompt 尾部做一致性锁定。"""
    parts = []
    if "characters" in include:
        for name in cast_of_shot(sid):
            a = char(name).get("anchor")
            if a:
                parts.append(a)
    if "scenes" in include:
        for cfg in scenes().values():
            if cfg.get("anchor"):
                parts.append(cfg["anchor"])
                break
    return ", ".join(parts)


# ---------- 人物小传与外貌 ----------

def bio(name: str) -> dict:
    """中文人物小传：年龄/身份/性格/背景/服装/习惯动作/声线风格。"""
    return char(name).get("bio", {})


def look(name: str) -> str:
    """英文外貌描述（给 SDXL 用）。优先 look（详细），回落 anchor（精简）。"""
    c = char(name)
    return c.get("look") or c.get("anchor", "")


def look_tokens(sid: int) -> str:
    """该镜出场角色的详细外貌描述，拼成一段。"""
    return ", ".join(x for x in (look(n) for n in cast_of_shot(sid)) if x)


# ---------- 风格模板（对应 DramaClaw「虾格」） ----------

def style_names() -> list:
    return list((load().get("styles") or {}).keys())


def style(name: str = None) -> dict:
    c = load()
    name = name or c.get("active_style")
    return (c.get("styles") or {}).get(name, {})


def style_prompt(name: str = None) -> str:
    return style(name).get("prompt_add", "")


def style_neg(name: str = None) -> str:
    return style(name).get("neg_add", "")


def build_prompt(sid: int, base: str, with_cast: bool = False,
                 with_style: bool = False) -> str:
    """按开关组装 prompt：底稿 + 角色外貌 + 全片风格。

    三层都是可选的——默认全关，保证既有产物的参数指纹不受影响；
    要用时通过 novel_video.py 的 --cast / --style 显式打开。
    """
    parts = [base]
    if with_cast:
        t = look_tokens(sid)
        if t:
            parts.append(t)
    if with_style:
        t = style_prompt()
        if t:
            parts.append(t)
    return ", ".join(p for p in parts if p)


def enrich_prompt(sid: int, prompt: str, with_cast: bool = True) -> str:
    """把锚点 token 追加到 prompt。默认开启但由调用方决定是否使用（--cast 开关）。

    注意：锚点是【文本层】锁定，与 IPAdapter 的【图像层】锁定互补；
    两者都开时 IPAdapter 权重应压低（见 defaults.ipadapter_weight）。
    """
    if not with_cast:
        return prompt
    extra = anchor_tokens(sid, include=("characters",))
    if not extra:
        return prompt
    return f"{prompt}, {extra}" if prompt else extra


def sig(obj) -> str:
    """参数指纹：用于断点续跑判断"参数变了要重做"。"""
    return hashlib.sha1(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:12]


def _cli():
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "show"
    if cmd == "show":
        c = load()
        print(f"资产表 {CAST_PATH}  v{c.get('version')}  ({c.get('updated')})")
        for kind in ("characters", "scenes", "props", "voices"):
            items = c.get(kind) or {}
            print(f"\n[{kind}] {len(items)}")
            for k, v in items.items():
                if kind == "characters":
                    print(f"  {k}: voice={v.get('voice')} mood={v.get('mood')} "
                          f"intensity={v.get('intensity')} ref={v.get('ref') or '-'}")
                else:
                    print(f"  {k}: {v}")
        print(f"\n[shot_cast] {c.get('shot_cast')}")
        print(f"[shot_overrides] {c.get('shot_overrides')}")
    elif cmd == "voice":
        sp = sys.argv[2] if len(sys.argv) > 2 else ""
        sid = int(sys.argv[3]) if len(sys.argv) > 3 else None
        print(voice_for(sp, sid))
    else:
        print(__doc__)


if __name__ == "__main__":
    _cli()
