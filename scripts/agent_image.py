#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
LuminaForge · 智能体出图引擎 (Agent Image Engine)
=================================================
「你说一句，它变出不一样的画」——把一句自然语言指令，扩写成一份**每次都不同**的
视觉规格，再交给 ComfyUI 出图。

与管线里固定模板出图的区别
--------------------------
管线出图（main.py STORYBOARD_SYSTEM）为了"同一部小说的画风统一"，会给每个场景
拼上**一模一样的风格标签串**（anime style / manhwa art style / cel shading / 8k uhd /
perfect face / perfect hands / 9:16 vertical），开头也都是 [color][lighting][composition]
[scale] —— 这是"十几张图看着像同一张"的根本原因。

本引擎反其道而行：
  1. **11 个差异维度**（构图/光线/色调/镜头/时代/质感/氛围/天气/时段/细节/环境）
     每次按权重随机抽取，且**只激活其中 4~6 个**，组合空间巨大；
  2. **风格包**可切换（日系动漫 / 电影写实 / 国风水墨 / 赛博朋克 / 油画 / 水彩 / 3D），
     不再是一条写死的标签串；
  3. **创意总监**（DeepSeek）把中文指令扩写成画面规格，用户**明确提到的属性强制保留**，
     没提到的维度自由发挥；DeepSeek 不可用时自动降级为本地启发式，不阻塞出图；
  4. **同指令批量出图时强制互斥**：同一条指令出 N 张，会在关键维度上互相避让，
     保证 N 张之间看得出明显差异；
  5. seed 默认随机，可 --seed 固定复现。

用法（命令行）
--------------
    python scripts/agent_image.py "一只在雨中弹吉他的橘猫"
    python scripts/agent_image.py "赛博都市里的女剑客" --variants 4 --style cyberpunk
    python scripts/agent_image.py "雪山之巅的孤独旅人" --ratio 16:9 --seed 42

用法（作为模块）
----------------
    from agent_image import generate
    results = await generate("一只在雨中弹吉他的橘猫", variants=4)
    # results[i] = {"file","url","prompt","seed","dims":{中文维度},"elapsed",...}
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import shutil
import sys
import time
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

import httpx

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ─── .env 加载（不依赖 python-dotenv）────────────────────────
def _load_dotenv() -> None:
    env_file = PROJECT_ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv()

COMFYUI_URL = os.environ.get("COMFYUI_URL", "http://127.0.0.1:8188").rstrip("/")
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
# 与项目主程序保持一致；可用 AGENT_IMAGE_LLM 覆盖
DEEPSEEK_MODEL = os.environ.get("AGENT_IMAGE_LLM", "deepseek-v4-flash")

AGENT_DIR = PROJECT_ROOT / "output" / "agent"
AGENT_DIR.mkdir(parents=True, exist_ok=True)
HISTORY_FILE = AGENT_DIR / "history.json"
WORKFLOW_DIR = PROJECT_ROOT / "comfyui"
_HISTORY_MAX = 300


# ══════════════════════════════════════════════════════════════
#  1. 差异维度库  (英文提示词, 中文说明, 权重)
# ══════════════════════════════════════════════════════════════
# 权重越高越容易被抽中。同一维度内的选项相互排斥，多张图之间会尽量避开重复。
DIMENSIONS: dict[str, list[tuple[str, str, float]]] = {
    "构图": [
        ("centered symmetrical composition", "居中对称", 1.0),
        ("rule of thirds composition", "三分法", 1.2),
        ("low angle looking up, heroic perspective", "低角度仰拍", 1.3),
        ("high angle looking down, god's eye view", "高角度俯拍", 1.1),
        ("over-the-shoulder shot", "过肩镜头", 1.0),
        ("extreme close-up filling the frame", "极致特写", 1.1),
        ("dutch angle, tilted horizon, uneasy", "荷兰角倾斜", 0.9),
        ("framed through foreground doorway, layered depth", "框架式前景", 1.0),
        ("wide establishing shot, tiny subject in vast space", "大远景", 1.0),
        ("negative space, minimal, subject off-center", "大量留白", 0.9),
        ("diagonal dynamic composition", "对角线动感", 1.0),
    ],
    "光线": [
        ("golden hour backlight, warm rim glow", "黄金逆光", 1.3),
        ("overcast soft diffused light", "阴天柔光", 1.0),
        ("neon reflections, colorful practical lights", "霓虹反射", 1.2),
        ("candlelight, warm flickering shadows", "烛光摇曳", 1.0),
        ("volumetric god rays through dust", "体积光束", 1.2),
        ("hard top light, dramatic shadows", "硬顶光", 0.9),
        ("cold moonlight, blue cast", "清冷月光", 1.1),
        ("harsh fluorescent lighting", "冷白荧光", 0.8),
        ("lightning flash instant, high contrast", "闪电瞬间", 0.9),
        ("studio three-point lighting, clean", "影棚三点布光", 1.0),
        ("sunset gradient sky, long shadows", "黄昏天光", 1.1),
        ("bioluminescent glow, otherworldly", "生物荧光", 0.8),
    ],
    "色调": [
        ("teal and orange cinematic color grading", "青橙电影调", 1.3),
        ("muted morandi palette, low saturation", "莫兰迪低饱和", 1.1),
        ("monochrome black and white, high contrast", "黑白高反差", 1.0),
        ("candy pastel colors, dreamy", "糖果粉彩", 1.0),
        ("cyberpunk purple and cyan", "赛博紫青", 1.1),
        ("earthy warm tones, ochre and brown", "大地暖色", 1.0),
        ("deep jewel tones, emerald and ruby", "宝石浓色", 0.9),
        ("desaturated cold winter palette", "冷冽灰白", 1.0),
        ("vibrant high saturation pop colors", "高饱和波普", 0.9),
        ("sepia nostalgic tone", "怀旧棕调", 0.8),
    ],
    "镜头": [
        ("ultra wide angle lens, exaggerated perspective", "超广角", 1.0),
        ("telephoto compression, shallow depth of field", "长焦压缩虚化", 1.2),
        ("fisheye lens distortion", "鱼眼畸变", 0.7),
        ("macro close-up, extreme detail", "微距", 0.9),
        ("tilt-shift miniature effect", "移轴微缩", 0.8),
        ("aerial drone shot", "航拍视角", 0.9),
        ("handheld documentary, slight motion blur", "手持纪实", 1.0),
        ("85mm portrait lens, creamy bokeh", "85mm 人像镜头", 1.2),
    ],
    "时代": [
        ("ancient eastern dynasty, hanfu and wood architecture", "古代东方", 1.0),
        ("medieval fantasy, stone castles", "中世纪奇幻", 1.0),
        ("1920s vintage roaring twenties", "1920 年代复古", 0.9),
        ("modern contemporary city", "现代都市", 1.1),
        ("near future sci-fi, sleek technology", "近未来科幻", 1.1),
        ("cyberpunk megacity, gritty neon", "赛博朋克都市", 1.1),
        ("steampunk brass and steam machinery", "蒸汽朋克", 0.9),
        ("post-apocalyptic wasteland", "废土末世", 0.9),
        ("prehistoric wild nature", "史前荒野", 0.7),
        ("timeless mythological realm", "神话仙境", 0.9),
    ],
    "质感": [
        ("watercolor washes, paper texture", "水彩纸纹", 1.0),
        ("thick oil painting impasto brushstrokes", "厚涂油画", 1.0),
        ("pencil sketch, crosshatching lines", "铅笔速写", 0.9),
        ("35mm film grain, analog texture", "胶片颗粒", 1.1),
        ("clean digital painting, crisp edges", "数字绘画", 1.0),
        ("chinese ink wash, rice paper bleeding", "水墨晕染", 0.9),
        ("woodblock print, bold outlines", "木刻版画", 0.8),
        ("glass and crystal translucent surface", "玻璃通透", 0.8),
        ("weathered rusty metal texture", "斑驳锈迹", 0.9),
        ("soft velvet and silk sheen", "丝绒柔光", 0.8),
    ],
    "氛围": [
        ("serene and tranquil atmosphere", "静谧安宁", 1.1),
        ("tense suspense, something about to happen", "紧张悬念", 1.1),
        ("lonely solitude, emptiness", "孤独寂寥", 1.0),
        ("joyful and lively energy", "欢快明朗", 1.0),
        ("solemn and sacred reverence", "肃穆庄严", 0.9),
        ("dreamlike surreal haze", "梦幻迷离", 1.1),
        ("oppressive dread, heavy air", "压抑窒息", 0.9),
        ("epic grandeur, awe-inspiring", "史诗壮阔", 1.0),
    ],
    "天气": [
        ("clear sky", "晴朗", 1.0),
        ("heavy rain, wet reflections", "大雨", 1.0),
        ("dense fog, low visibility", "浓雾", 1.0),
        ("falling snow, white blanket", "落雪", 0.9),
        ("sandstorm, dusty haze", "沙尘", 0.7),
        ("gentle drizzle just after rain", "细雨初霁", 0.9),
        ("storm clouds gathering", "积雨云涌", 0.9),
    ],
    "时段": [
        ("dawn, first light", "黎明", 0.9),
        ("bright midday sun", "正午", 0.8),
        ("golden afternoon", "午后", 1.0),
        ("dusk, orange horizon", "黄昏", 1.1),
        ("deep night, starry sky", "深夜星空", 1.0),
        ("blue hour, city lights turning on", "蓝调时刻", 1.0),
    ],
    "细节": [
        ("intricate ornate details, filigree", "繁复纹饰", 0.9),
        ("floating dust particles in air", "空气浮尘", 1.0),
        ("lens flare and light bloom", "镜头光晕", 0.9),
        ("reflections on wet surfaces", "湿面反射", 0.9),
        ("foreground bokeh elements", "前景虚化", 1.0),
        ("fabric folds and garment texture", "衣料褶皱", 0.8),
        ("highly detailed background architecture", "精细背景建筑", 1.0),
        ("subtle chromatic aberration", "轻微色散", 0.7),
    ],
    "环境": [
        ("in a narrow neon-lit back alley", "霓虹小巷", 1.0),
        ("on a windswept mountain ridge", "山脊风口", 1.0),
        ("inside an abandoned cathedral", "废弃教堂", 0.9),
        ("in a sunlit wheat field", "麦田", 0.9),
        ("on a rain-slicked city crossroad", "雨夜路口", 1.0),
        ("in a cluttered tiny art studio", "杂乱画室", 0.8),
        ("on a vast tidal flat at low tide", "退潮滩涂", 0.8),
        ("inside a futuristic space station", "空间站舱内", 0.9),
        ("in a dense bamboo forest", "幽深竹林", 0.9),
        ("on the rooftop of a skyscraper", "摩天楼顶", 0.9),
    ],
}

# 出图时必带的维度；其余维度随机激活 4~6 个
OPTIONAL_DIMS = list(DIMENSIONS.keys())


# ══════════════════════════════════════════════════════════════
#  2. 风格包（取代那条写死的标签串）
# ══════════════════════════════════════════════════════════════
STYLE_PACKS: dict[str, dict[str, Any]] = {
    "anime": {
        "zh": "日系动漫",
        "ckpt": "animagine-xl-4.0.safetensors",
        "tags": "anime style, cel shading, clean lineart, expressive eyes, vivid colors, 8k uhd",
        # 质量锚点：无论维度怎么随机组合，都压住画面下限，防止"抽象噪点图"
        "quality": "masterpiece, best quality, very aesthetic, absurdres, sharp focus, detailed",
        "neg": ("(worst quality:1.4), (low quality:1.4), blurry, bad anatomy, bad hands, "
                "extra fingers, mutated limbs, watermark, jpeg artifacts, signature, "
                "abstract, undefined shapes, noise texture"),
        "steps": 28, "cfg": 6.5, "sampler": "euler_ancestral", "scheduler": "karras",
    },
    "cinematic": {
        "zh": "电影写实",
        "ckpt": "RealVisXL_V4.0.safetensors",
        "tags": "photorealistic, cinematic film still, anamorphic lens flare, film grain, "
                "highly detailed skin and fabric, 8k",
        "quality": "masterpiece, best quality, highly detailed, sharp focus, professional photography",
        "neg": ("(worst quality:1.4), (low quality:1.4), blurry, plastic skin, bad anatomy, "
                "bad hands, extra fingers, watermark, oversaturated, abstract, undefined shapes"),
        "steps": 30, "cfg": 6.0, "sampler": "dpmpp_2m", "scheduler": "karras",
    },
    "ink": {
        "zh": "国风水墨",
        "ckpt": "RealVisXL_V4.0.safetensors",
        "tags": "chinese ink wash painting, xuan rice paper texture, elegant brushwork, "
                "monochrome with subtle accents, generous white space",
        "quality": "masterpiece, best quality, highly detailed, elegant composition",
        "neg": ("(worst quality:1.4), (low quality:1.4), blurry, photorealistic, "
                "garish colors, watermark, clipart, abstract, undefined shapes"),
        "steps": 30, "cfg": 7.0, "sampler": "dpmpp_2m", "scheduler": "karras",
    },
    "cyberpunk": {
        "zh": "赛博朋克",
        "ckpt": "RealVisXL_V4.0.safetensors",
        "tags": "cyberpunk, neon glow, rain-slicked streets, holographic signage, "
                "high contrast purple and cyan, blade runner aesthetic, 8k",
        "quality": "masterpiece, best quality, highly detailed, sharp focus",
        "neg": ("(worst quality:1.4), (low quality:1.4), blurry, daytime, pastel, "
                "watermark, flat lighting, abstract, undefined shapes"),
        "steps": 30, "cfg": 6.5, "sampler": "dpmpp_2m", "scheduler": "karras",
    },
    "oil": {
        "zh": "古典油画",
        "ckpt": "RealVisXL_V4.0.safetensors",
        "tags": "oil painting on canvas, impasto brushstrokes, chiaroscuro, "
                "rembrandt lighting, museum quality",
        "quality": "masterpiece, best quality, highly detailed, fine brushwork",
        "neg": ("(worst quality:1.4), (low quality:1.4), blurry, anime, photorealistic, "
                "watermark, digital art, abstract, undefined shapes"),
        "steps": 32, "cfg": 7.5, "sampler": "dpmpp_2m", "scheduler": "karras",
    },
    "watercolor": {
        "zh": "水彩插画",
        "ckpt": "RealVisXL_V4.0.safetensors",
        "tags": "watercolor illustration, soft pigment bleeding, cold press paper texture, "
                "light and airy, delicate linework",
        "quality": "masterpiece, best quality, delicate detail, clean composition",
        "neg": ("(worst quality:1.4), (low quality:1.4), blurry, photorealistic, "
                "heavy contrast, watermark, abstract, undefined shapes"),
        "steps": 28, "cfg": 7.0, "sampler": "dpmpp_2m", "scheduler": "karras",
    },
    "3d": {
        "zh": "3D 渲染",
        "ckpt": "RealVisXL_V4.0.safetensors",
        "tags": "3d render, octane engine, physically based rendering, soft global "
                "illumination, stylized character design, 8k",
        "quality": "masterpiece, best quality, highly detailed, clean topology",
        "neg": ("(worst quality:1.4), (low quality:1.4), blurry, flat, bad geometry, "
                "watermark, low poly artifacts, abstract, undefined shapes"),
        "steps": 30, "cfg": 6.5, "sampler": "dpmpp_2m", "scheduler": "karras",
    },
}

RATIO_PRESETS: dict[str, tuple[int, int]] = {
    "1:1": (1024, 1024),
    "9:16": (896, 1152),
    "16:9": (1344, 768),
    "3:2": (1152, 768),
    "2:3": (768, 1152),
    "4:3": (1152, 896),
}


# ══════════════════════════════════════════════════════════════
#  3. 数据结构
# ══════════════════════════════════════════════════════════════
@dataclass
class CreativeSpec:
    """一份"画面规格"：主体由用户指令决定，其余维度自由发挥。"""
    instruction: str
    subject: str
    environment: str = ""
    dims: dict[str, str] = field(default_factory=dict)      # 维度名 -> 英文提示词
    dims_zh: dict[str, str] = field(default_factory=dict)   # 维度名 -> 中文说明
    style: str = "anime"
    variation_note: str = ""
    negative: str = ""
    seed: int = 0
    checkpoint: str = ""
    width: int = 1024
    height: int = 1024
    steps: int = 28
    cfg: float = 6.5
    sampler: str = "euler_ancestral"
    scheduler: str = "karras"
    source: str = "heuristic"   # llm | heuristic

    def to_prompt(self) -> str:
        """组装 SDXL 正向提示词。随机给 1~2 个维度加权重，进一步拉开差异。"""
        parts = [self.subject]
        if self.environment:
            parts.append(self.environment)
        rng = random.Random(self.seed)
        keys = list(self.dims.keys())
        emphasise = set(rng.sample(keys, min(len(keys), rng.choice([1, 2])))) if keys else set()
        for k in keys:
            v = self.dims[k]
            # 强调权重压在 1.2：再高容易把画面推向极端（纯黑/纯色块/抽象糊）
            parts.append(f"({v}:1.2)" if k in emphasise and ":" not in v else v)
        pack = STYLE_PACKS.get(self.style, STYLE_PACKS["anime"])
        parts.append(pack.get("quality", ""))   # 质量锚点，压住画面下限
        parts.append(pack["tags"])
        return ", ".join(p for p in parts if p)

    def display_dims(self) -> dict[str, str]:
        d = dict(self.dims_zh)
        if self.environment and "环境" not in d:
            d["环境"] = self.environment
        return d


# ══════════════════════════════════════════════════════════════
#  4. 抽取工具
# ══════════════════════════════════════════════════════════════
def _weighted_pick(rng: random.Random, dim: str, exclude: set[str] | None = None) -> tuple[str, str, float] | None:
    opts = DIMENSIONS.get(dim)
    if not opts:
        return None
    exclude = exclude or set()
    cand = [o for o in opts if o[0] not in exclude]
    if not cand:
        cand = list(opts)
    total = sum(o[2] for o in cand)
    r = rng.uniform(0, total)
    acc = 0.0
    for o in cand:
        acc += o[2]
        if r <= acc:
            return o
    return cand[-1]


def _stable_seed(text: str) -> int:
    """跨进程稳定的哈希（不能用 hash()，PYTHONHASHSEED 会让它每次变）。"""
    return zlib.crc32((text or "").encode("utf-8")) % (2 ** 31)


# ══════════════════════════════════════════════════════════════
#  5. 创意总监：DeepSeek 扩写 / 本地启发式兜底
# ══════════════════════════════════════════════════════════════
AGENT_IMAGE_SYSTEM = """你是资深视觉总监，为文生图模型（SDXL）撰写画面规格。

用户会给你一句自然语言指令。你要输出一个 JSON 对象，把这句指令扩写成具体画面。

【铁律】
1. 用户**明确提到**的属性（主体是什么、颜色、数量、动作、服饰、地点、情绪）必须原样体现，
   绝对不许篡改或替换成你自己想的东西。
2. 用户**没提到**的维度，由你自由发挥，追求视觉冲击力和新鲜感。
3. 所有字段的值必须是**英文短语**（SDXL 提示词），每个 4~14 个单词，不要写完整句子，
   不要出现解释性文字，不要出现引号或换行。
4. 如果某个维度用户已经隐含指定，就贴合它；否则自由创作。
5. 若给了【本张差异要求】，必须严格遵守，让这张图和同批次其他图明显不同。

输出严格是 JSON，键固定为：
subject（主体：含用户指定的外观/动作/服饰/数量）
environment（环境场景）
composition（构图）
lighting（光线）
palette（色调）
camera（镜头）
era（时代背景）
material（画面质感/媒介）
mood（氛围）
weather（天气）
timeofday（时段）
detail（细节增强）
variation_note（中文一句话说明本张的差异化取向）"""


async def _call_llm(instruction: str, style_zh: str, variant_hint: str,
                    avoid: dict[str, list[str]]) -> dict[str, str] | None:
    """调 DeepSeek 拿结构化画面规格。失败返回 None（上层降级为本地启发式）。"""
    if not DEEPSEEK_API_KEY:
        return None
    avoid_txt = ""
    if avoid:
        avoid_txt = "\n【同批次已用过、请避开】\n" + "\n".join(
            f"- {k}: {', '.join(v[:6])}" for k, v in avoid.items() if v)
    user_msg = (
        f"用户指令：{instruction}\n"
        f"目标画风：{style_zh}\n"
        f"【本张差异要求】{variant_hint or '自由发挥，追求最强视觉冲击'}"
        f"{avoid_txt}\n\n只输出 JSON。"
    )
    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": AGENT_IMAGE_SYSTEM},
            {"role": "user", "content": user_msg},
        ],
        "temperature": 1.15,      # 高温 = 更大差异
        "max_tokens": 2400,       # 13 个字段，给足额度避免 JSON 被截断
        "response_format": {"type": "json_object"},
    }
    headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY}",
               "Content-Type": "application/json"}
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(DEEPSEEK_URL, json=payload, headers=headers)
            if resp.status_code == 401:
                print("[agent-image] DeepSeek Key 无效，改用本地启发式", flush=True)
                return None
            if resp.status_code != 200:
                await asyncio.sleep(1.5 * (attempt + 1))
                continue
            content = resp.json()["choices"][0]["message"]["content"].strip()
            data = _parse_llm_json(content)
            if data:
                return data
            print(f"[agent-image] LLM 返回无法解析，重试 ({attempt+1}/3)", flush=True)
        except Exception as e:
            print(f"[agent-image] LLM 第 {attempt+1} 次失败: {str(e)[:80]}", flush=True)
            await asyncio.sleep(1.5 * (attempt + 1))
    return None


def _parse_llm_json(content: str) -> dict | None:
    """解析 LLM 返回的 JSON；被截断时用正则抢救出已完整的键值对。"""
    import re
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    # 抢救：抓 "key": "value" 形式，忽略最后一条残缺的
    pairs = re.findall(r'"(\w+)"\s*:\s*"((?:[^"\\]|\\.)*)"\s*,?', text)
    if not pairs:
        return None
    out: dict[str, str] = {}
    for k, v in pairs:
        try:
            out[k] = json.loads(f'"{v}"')
        except Exception:
            out[k] = v
    print(f"[agent-image] JSON 被截断，已抢救 {len(out)} 个字段", flush=True)
    return out or None


# 常见中文词 → 英文提示词片段（本地兜底时的极简翻译，避免整句中文喂给 SDXL）
_ZH2EN = {
    "猫": "cat", "橘猫": "orange tabby cat", "黑猫": "black cat", "狗": "dog",
    "女孩": "young woman", "少女": "young girl", "男孩": "young boy",
    "男人": "man", "女人": "woman", "老人": "elderly person",
    "剑客": "swordsman", "武士": "samurai", "骑士": "knight", "法师": "mage",
    "机器人": "robot", "龙": "dragon", "狐狸": "fox", "鸟": "bird", "鱼": "fish",
    "雨": "rain", "雪": "snow", "雾": "fog", "海": "ocean", "山": "mountain",
    "森林": "forest", "城市": "city", "沙漠": "desert", "太空": "space",
    "红色": "red", "蓝色": "blue", "绿色": "green", "黑色": "black",
    "白色": "white", "金色": "golden", "紫色": "purple",
    "吉他": "guitar", "书": "book", "伞": "umbrella", "灯": "lantern",
    "咖啡": "coffee", "花": "flowers", "火车": "train", "飞船": "spaceship",
    "城堡": "castle", "桥": "bridge", "街道": "street", "房间": "room",
}


def _heuristic_subject(instruction: str) -> str:
    """本地兜底：中文指令 → 半英文提示词。

    SDXL（尤其 animagine）基本只看得懂英文标签，所以这里做一个轻量词替换 +
    虚词清理，尽量把中文指令压成模型能吃的形式；剩下的中文由风格包标签兜底。
    """
    out = instruction.strip()
    for zh, en in sorted(_ZH2EN.items(), key=lambda kv: -len(kv[0])):
        if zh in out:
            out = out.replace(zh, f" {en} ")
    # 常见虚词 / 量词
    for zh, en in (("一只", "a"), ("一个", "a"), ("一位", "a"), ("一条", "a"),
                   ("在", " in "), ("里", " "), ("中", " "), ("的", " "),
                   ("和", " and "), ("穿着", " wearing "), ("拿着", " holding "),
                   ("手里", " holding "), ("站在", " standing on "),
                   ("坐在", " sitting on "), ("看着", " looking at ")):
        out = out.replace(zh, en)
    out = " ".join(out.split()).strip()
    # 中文占比仍然很高 → 加英文前缀，保证模型至少抓到主体类别
    cjk = sum(1 for c in out if "一" <= c <= "鿿")
    if cjk > 4:
        out = f"illustration of {out}" if not out.lower().startswith("illustration") else out
    return out


async def build_spec(instruction: str, style: str, seed: int, width: int, height: int,
                     variant_hint: str = "", avoid: dict[str, list[str]] | None = None) -> CreativeSpec:
    """一句指令 → 一份差异化画面规格。"""
    avoid = avoid or {}
    rng = random.Random(seed)
    pack = STYLE_PACKS.get(style, STYLE_PACKS["anime"])

    spec = CreativeSpec(
        instruction=instruction, subject=instruction.strip(), style=style,
        negative=pack["neg"], seed=seed, checkpoint=pack["ckpt"],
        width=width, height=height, steps=pack["steps"], cfg=pack["cfg"],
        sampler=pack["sampler"], scheduler=pack["scheduler"],
    )

    llm = await _call_llm(instruction, pack["zh"], variant_hint, avoid)
    if llm:
        spec.source = "llm"
        spec.subject = str(llm.get("subject") or instruction).strip() or instruction
        spec.environment = str(llm.get("environment") or "").strip()
        spec.variation_note = str(llm.get("variation_note") or "").strip()
        # 把 LLM 给的维度值收进来（缺的字段就不激活，天然形成差异）
        for dim, key in (("构图", "composition"), ("光线", "lighting"), ("色调", "palette"),
                         ("镜头", "camera"), ("时代", "era"), ("质感", "material"),
                         ("氛围", "mood"), ("天气", "weather"), ("时段", "timeofday"),
                         ("细节", "detail")):
            v = str(llm.get(key) or "").strip()
            if v:
                spec.dims[dim] = v
                # 展示用：完整英文值（界面上按维度名+取值呈现，用户能直接看出"哪里变了"）
                spec.dims_zh[dim] = v
        if spec.environment:
            spec.dims_zh.setdefault("环境", spec.environment)
        # LLM 偶尔会漏维度或重复旧值 → 补足到至少 5 个维度
        need = 5 - len(spec.dims)
        if need > 0:
            for dim in rng.sample([d for d in OPTIONAL_DIMS if d not in spec.dims],
                                  min(need, len([d for d in OPTIONAL_DIMS if d not in spec.dims]))):
                opt = _weighted_pick(rng, dim, set(avoid.get(dim, [])))
                if opt:
                    spec.dims[dim], spec.dims_zh[dim] = opt[0], opt[1]
    else:
        spec.source = "heuristic"
        spec.subject = _heuristic_subject(instruction)
        # 随机激活 4~6 个维度
        k = rng.randint(4, 6)
        for dim in rng.sample(OPTIONAL_DIMS, min(k, len(OPTIONAL_DIMS))):
            opt = _weighted_pick(rng, dim, set(avoid.get(dim, [])))
            if opt:
                spec.dims[dim], spec.dims_zh[dim] = opt[0], opt[1]
        spec.variation_note = f"本地启发式：激活 {len(spec.dims)} 个维度，seed {seed}"
    return spec


# ══════════════════════════════════════════════════════════════
#  6. ComfyUI 提交 / 轮询 / 落盘
# ══════════════════════════════════════════════════════════════
def load_workflow(name: str) -> dict:
    with open(WORKFLOW_DIR / f"{name}.json", "r", encoding="utf-8") as f:
        return json.load(f)


def fill_workflow(template: dict, replacements: dict) -> dict:
    """替换 {{KEY}} 占位符。值先做 JSON 转义，避免提示词里的引号破坏结构。"""
    s = json.dumps(template, ensure_ascii=False)
    for k, v in replacements.items():
        s = s.replace("{{%s}}" % k, json.dumps(str(v), ensure_ascii=False)[1:-1])
    return json.loads(s)


def patch_nodes(workflow: dict, **kwargs) -> dict:
    """按 class_type 找到 KSampler / SaveImage 节点并覆盖采样参数与文件名前缀。

    不依赖模板里固定的节点编号或占位符，换模板也不会崩。
    """
    for node in workflow.values():
        if not isinstance(node, dict):
            continue
        ct = node.get("class_type")
        inputs = node.get("inputs")
        if not isinstance(inputs, dict):
            continue
        if ct == "KSampler":
            for key in ("steps", "cfg", "sampler_name", "scheduler", "seed", "denoise"):
                if kwargs.get(key) is not None:
                    inputs[key] = kwargs[key]
        elif ct == "SaveImage":
            if kwargs.get("filename_prefix"):
                inputs["filename_prefix"] = kwargs["filename_prefix"]
    return workflow


def build_image_workflow(spec: CreativeSpec, filename_prefix: str,
                         checkpoint: str) -> dict:
    wf = fill_workflow(load_workflow("txt2img"), {
        "POSITIVE_PROMPT": spec.to_prompt(),
        "NEGATIVE_PROMPT": spec.negative,
        "SEED": spec.seed % (2 ** 31),
        "WIDTH": spec.width,
        "HEIGHT": spec.height,
        "CHECKPOINT": checkpoint,
    })
    return patch_nodes(wf, steps=spec.steps, cfg=spec.cfg, sampler_name=spec.sampler,
                       scheduler=spec.scheduler, seed=spec.seed % (2 ** 31),
                       filename_prefix=filename_prefix)


_CHECKPOINT_CACHE: list[str] | None = None


async def available_checkpoints(client: httpx.AsyncClient) -> list[str]:
    """拉取 ComfyUI 实际装了哪些 checkpoint；拿不到就返回空列表（不阻塞出图）。"""
    global _CHECKPOINT_CACHE
    if _CHECKPOINT_CACHE is not None:
        return _CHECKPOINT_CACHE
    try:
        r = await client.get(f"{COMFYUI_URL}/object_info/CheckpointLoaderSimple", timeout=10)
        if r.status_code == 200:
            _CHECKPOINT_CACHE = r.json()["CheckpointLoaderSimple"]["input"]["required"]["ckpt_name"][0]
            return _CHECKPOINT_CACHE
    except Exception:
        pass
    _CHECKPOINT_CACHE = []
    return []


async def _resolve_checkpoint(client: httpx.AsyncClient, wanted: str) -> str:
    """模型不存在时回退到第一个可用模型，避免整张图直接失败。"""
    avail = await available_checkpoints(client)
    if not avail:
        return wanted
    if wanted in avail:
        return wanted
    print(f"[agent-image] 模型 {wanted} 不可用，回退 {avail[0]}", flush=True)
    return avail[0]


async def generate_one(client: httpx.AsyncClient, spec: CreativeSpec,
                       checkpoint: str, filename_prefix: str,
                       timeout: int = 900) -> dict[str, Any]:
    """提交一张图并等它落盘，返回结果字典。"""
    t0 = time.time()
    wf = build_image_workflow(spec, filename_prefix, checkpoint)
    r = await client.post(f"{COMFYUI_URL}/prompt", json={"prompt": wf}, timeout=60)
    if r.status_code != 200:
        raise RuntimeError(f"ComfyUI 提交失败 {r.status_code}: {r.text[:300]}")
    prompt_id = r.json().get("prompt_id")
    if not prompt_id:
        raise RuntimeError("ComfyUI 未返回 prompt_id")

    # 轮询 history（比 websocket 简单，且不依赖额外库）
    entry = None
    while time.time() - t0 < timeout:
        await asyncio.sleep(1.5)
        try:
            h = await client.get(f"{COMFYUI_URL}/history/{prompt_id}", timeout=30)
            if h.status_code != 200:
                continue
            data = h.json()
        except Exception:
            continue
        if prompt_id in data:
            entry = data[prompt_id]
            break
    if entry is None:
        raise TimeoutError(f"出图超时（{timeout}s）")

    status = entry.get("status") or {}
    if status.get("status_str") == "error":
        msgs = status.get("messages") or []
        err = next((m[1].get("exception_message") for m in msgs
                    if isinstance(m, list) and len(m) > 1 and isinstance(m[1], dict)
                    and m[1].get("exception_message")), "未知错误")
        raise RuntimeError(f"ComfyUI 执行失败: {str(err)[:300]}")

    img = None
    for node_out in (entry.get("outputs") or {}).values():
        if isinstance(node_out, dict) and node_out.get("images"):
            img = node_out["images"][0]
            break
    if not img:
        raise RuntimeError("ComfyUI 返回结果中未找到图片")

    view = await client.get(f"{COMFYUI_URL}/view", params={
        "filename": img["filename"], "type": img.get("type", "output"),
        "subfolder": img.get("subfolder", "")}, timeout=180)
    if view.status_code != 200:
        raise RuntimeError(f"下载图片失败 {view.status_code}")

    out_path = AGENT_DIR / f"{filename_prefix}.png"
    out_path.write_bytes(view.content)
    return {
        "file": str(out_path),
        "name": out_path.name,
        "url": f"/output/agent/{out_path.name}",
        "size_bytes": len(view.content),
        "elapsed": round(time.time() - t0, 1),
    }


# ══════════════════════════════════════════════════════════════
#  7. 对外主入口
# ══════════════════════════════════════════════════════════════
async def generate(instruction: str, *, variants: int = 1, style: str = "auto",
                   ratio: str = "1:1", seed: int | None = None,
                   on_progress: Optional[Callable[[str, dict], Any]] = None) -> list[dict]:
    """按指令出图。返回每张图的完整信息（含中文维度说明，方便看出"哪里不一样"）。

    style: auto=每张随机挑风格包 | 或指定 anime/cinematic/ink/cyberpunk/oil/watercolor/3d
    """
    instruction = (instruction or "").strip()
    if not instruction:
        raise ValueError("指令不能为空")
    variants = max(1, min(int(variants or 1), 8))
    width, height = RATIO_PRESETS.get(ratio, RATIO_PRESETS["1:1"])
    base_seed = seed if seed is not None else random.randint(1, 2 ** 31 - 1)

    async def _prog(stage: str, **kw):
        if on_progress:
            try:
                res = on_progress(stage, kw)
                if asyncio.iscoroutine(res):
                    await res
            except Exception:
                pass

    results: list[dict] = []
    used: dict[str, list[str]] = {}       # 维度 -> 已用过的英文值（同批次互斥）
    used_styles: list[str] = []

    async with httpx.AsyncClient(timeout=60) as client:
        for i in range(variants):
            v_seed = (base_seed + i * 7919) % (2 ** 31)
            # 风格包：auto 时尽量不重复
            if style == "auto":
                pool = [s for s in STYLE_PACKS if s not in used_styles] or list(STYLE_PACKS)
                cur_style = random.Random(v_seed).choice(pool)
            else:
                cur_style = style if style in STYLE_PACKS else "anime"
            used_styles.append(cur_style)

            await _prog("spec", index=i + 1, total=variants, style=cur_style)
            hint = ""
            if i > 0:
                hint = (f"这是同一条指令的第 {i+1} 张。务必与前面的图在【构图/光线/色调/镜头】"
                        f"至少三个维度上明显不同，追求完全不同的观感。")
            spec = await build_spec(instruction, cur_style, v_seed, width, height,
                                    variant_hint=hint, avoid=used)

            # 记录已用取值，供后续张避让
            for k, v in spec.dims.items():
                used.setdefault(k, []).append(v)

            await _prog("submit", index=i + 1, total=variants, prompt=spec.to_prompt())
            ckpt = await _resolve_checkpoint(client, spec.checkpoint)
            prefix = f"agent_{int(time.time())}_{v_seed}"
            info = await generate_one(client, spec, ckpt, prefix)
            record = {
                "id": prefix,
                "instruction": instruction,
                "style": cur_style,
                "style_zh": STYLE_PACKS[cur_style]["zh"],
                "ratio": ratio,
                "width": width, "height": height,
                "seed": v_seed,
                "prompt": spec.to_prompt(),
                "negative": spec.negative,
                "subject": spec.subject,
                "environment": spec.environment,
                "dims": spec.display_dims(),
                "variation_note": spec.variation_note,
                "source": spec.source,
                "checkpoint": ckpt,
                "steps": spec.steps, "cfg": spec.cfg,
                "sampler": spec.sampler, "scheduler": spec.scheduler,
                "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                **info,
            }
            results.append(record)
            # 带上完整 record，方便流式接口逐张推送给前端
            await _prog("done", index=i + 1, total=variants, url=info["url"], record=record)

    _append_history(results)
    return results
    return results


def _append_history(records: list[dict]) -> None:
    try:
        hist = load_history()
        hist = records + hist
        HISTORY_FILE.write_text(
            json.dumps(hist[:_HISTORY_MAX], ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"[agent-image] 历史写入失败: {str(e)[:100]}", flush=True)


def load_history(limit: int = 60) -> list[dict]:
    if not HISTORY_FILE.exists():
        return []
    try:
        return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))[:limit]
    except Exception:
        return []


def list_styles() -> list[dict]:
    return [{"key": k, "zh": v["zh"], "ckpt": v["ckpt"]} for k, v in STYLE_PACKS.items()]


# ══════════════════════════════════════════════════════════════
#  8. 图生视频：wan5b 真视频 → 失败降级 ffmpeg 推拉
# ══════════════════════════════════════════════════════════════
# Wan 2.2 TI2V-5B 在 8G 显存下的安全分辨率（均为 32 的倍数）
VIDEO_SIZE_PRESETS: dict[str, tuple[int, int]] = {
    "1:1": (704, 704),
    "9:16": (704, 1280),
    "16:9": (1280, 704),
    "3:2": (960, 640),
    "2:3": (640, 960),
    "4:3": (960, 704),
}

_FFMPEG_HINT = r"C:\Users\Mr.Wang\ffmpeg-shared\ffmpeg-master-latest-win64-gpl\bin"


def _find_ffmpeg() -> str:
    """定位 ffmpeg：优先 PATH，其次项目已知安装路径。"""
    import shutil
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    for cand in (_FFMPEG_HINT, r"C:\ffmpeg\bin", r"C:\ProgramData\chocolatey\bin"):
        for name in ("ffmpeg.exe", "ffmpeg"):
            p = Path(cand) / name
            if p.exists():
                return str(p)
    return "ffmpeg"


def _ken_burns(image_path: str, out_path: Path, width: int, height: int,
               duration: float = 4.0, fps: int = 24) -> bool:
    """降级方案：静态图 + 缓慢推拉。画面内容本身不动，但至少有镜头运动。"""
    import subprocess as sp
    ff = _find_ffmpeg()
    frames = int(round(duration * fps))
    # 先放大到 2 倍再 zoompan 裁回目标尺寸，避免推拉时露黑边
    vf = (f"scale={width*2}:{height*2},"
          f"zoompan=z='min(zoom+0.0012,1.20)':d={frames}:s={width}x{height}:fps={fps}")
    cmd = [ff, "-y", "-loop", "1", "-i", str(image_path),
           "-vf", vf, "-t", str(duration),
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast",
           "-crf", "20", str(out_path)]
    try:
        r = sp.run(cmd, capture_output=True, timeout=300)
        return r.returncode == 0 and out_path.exists() and out_path.stat().st_size > 10000
    except Exception as e:
        print(f"[agent-image] ken_burns 失败: {str(e)[:120]}", flush=True)
        return False


async def image_to_video(image_path: str, prompt: str, ratio: str = "9:16",
                         duration: float = 3.0, seed: int | None = None,
                         negative: str = "", end_image: str = "", output_name: str = "",
                         fast: bool = False,
                         on_progress: Optional[Callable[[str, dict], Any]] = None) -> dict:
    """把一张图变成一段短视频。优先 wan5b 真视频，失败降级 ffmpeg 推拉。

    fast=True 时只跑第一段（采样+解码），跳过第二段的 RIFE 补帧 + 4x 超分：
    分辨率从 2560x1408 退回原生 1280x704、帧率 48fps 退回 24fps，但耗时可省一半以上。
    8G 显存下完整模式实测约 18 分钟，快速模式明显更快。

    返回 {"file","url","mode","engine","elapsed","size_bytes"}
    """
    src = Path(image_path)
    if not src.exists():
        raise FileNotFoundError(f"图片不存在: {image_path}")

    async def _prog(event: str, **kw):
        if on_progress:
            try:
                res = on_progress(event, kw)
                if asyncio.iscoroutine(res):
                    await res
            except Exception:
                pass

    width, height = VIDEO_SIZE_PRESETS.get(ratio, VIDEO_SIZE_PRESETS["9:16"])
    name = output_name or f"agentvid_{int(time.time())}_{seed or 0}"
    out_dir = AGENT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / f"{name}.mp4"
    t0 = time.time()

    # ── 1) wan5b 真视频 ──
    try:
        from engines.base import GenerateRequest
        from engines.wan5b import Wan5BEngine
        await _prog("video", stage="wan5b",
                    detail=("提交 I2V（快速模式，跳过超分）" if fast else "提交 I2V（完整两段式）")
                           + f" {width}x{height}")
        seed = seed if seed is not None else random.randint(0, 2 ** 32 - 1)
        req = GenerateRequest(
            prompt=(prompt or "")[:900],
            first_frame=src,
            width=width, height=height,
            duration_seconds=min(max(duration, 1.0), 4.0),
            fps=24,
            seed=seed,
            negative_prompt=negative or "",
            output_dir=out_dir,
            output_name=name,
            timeout_seconds=7200,
        )
        if fast:
            # 只跑第一段：采样 + 解码，直接产出原生分辨率视频
            engine = Wan5BEngine()
            frames = int(min(max(duration, 1.0), 4.0) * 24)
            frames = max(33, min(frames, 97))
            uploaded = await engine._upload_image(src)
            wf = engine._build_workflow(req, seed, frames, width, height, uploaded)
            pid = await engine._submit(wf)
            print(f"[agent-image] 快速模式已提交 {str(pid)[:12]}… ({frames}f)", flush=True)
            entry = await engine._wait_result(pid, timeout=7200)
            found = engine.find_output(entry.get("outputs", {}))
            if not found:
                raise RuntimeError("Wan 5B 快速模式无输出")
            await engine._download(found[0], found[1], found[2], dest)
        else:
            res = await Wan5BEngine().generate(req)
            vp = Path(res.video_path)
            if vp.exists() and vp.stat().st_size > 10000:
                if vp.resolve() != dest.resolve():
                    shutil.copyfile(vp, dest)
        if not (dest.exists() and dest.stat().st_size > 10000):
            raise RuntimeError("wan5b 输出为空")
        return {"file": str(dest), "url": f"/output/agent/{dest.name}",
                "mode": "wan5b_fast" if fast else "wan5b",
                "engine": ("Wan 2.2 TI2V-5B（快速，原生分辨率跳过超分）" if fast
                           else "Wan 2.2 TI2V-5B（完整：补帧+4x超分）"),
                "elapsed": round(time.time() - t0, 1),
                "size_bytes": dest.stat().st_size}
    except Exception as e:
        print(f"[agent-image] wan5b 失败，降级推拉: {str(e)[:160]}", flush=True)
        await _prog("video", stage="ken_burns", detail=str(e)[:160])

    # ── 2) 降级：ffmpeg 推拉 ──
    if not _ken_burns(str(src), dest, width, height, duration=max(duration, 4.0)):
        raise RuntimeError("视频生成失败：wan5b 与推拉降级均未产出文件")
    return {"file": str(dest), "url": f"/output/agent/{dest.name}",
            "mode": "ken_burns", "engine": "ffmpeg zoompan（画面内容不动，仅镜头推拉）",
            "elapsed": round(time.time() - t0, 1),
            "size_bytes": dest.stat().st_size}


def update_history_video(record_id: str, video: dict) -> bool:
    """把视频信息回写到对应历史记录。"""
    try:
        hist = load_history(limit=_HISTORY_MAX)
        hit = False
        for h in hist:
            if h.get("id") == record_id or h.get("name", "").startswith(record_id):
                h["video_url"] = video.get("url", "")
                h["video_mode"] = video.get("mode", "")
                h["video_engine"] = video.get("engine", "")
                hit = True
                break
        if hit:
            HISTORY_FILE.write_text(
                json.dumps(hist, ensure_ascii=False, indent=2), encoding="utf-8")
        return hit
    except Exception as e:
        print(f"[agent-image] 视频信息回写失败: {str(e)[:100]}", flush=True)
        return False


# ══════════════════════════════════════════════════════════════
#  9. CLI
# ══════════════════════════════════════════════════════════════
def _cli() -> int:
    ap = argparse.ArgumentParser(
        description="LuminaForge 智能体出图：一句指令，变出不一样的画")
    ap.add_argument("instruction", nargs="?", help="自然语言画面指令，用引号包起来")
    ap.add_argument("-n", "--variants", type=int, default=1, help="一次出几张（1~8，默认 1）")
    ap.add_argument("-s", "--style", default="auto",
                    choices=["auto"] + list(STYLE_PACKS), help="风格包，auto=每张随机")
    ap.add_argument("-r", "--ratio", default="1:1", choices=list(RATIO_PRESETS))
    ap.add_argument("--seed", type=int, default=None, help="固定种子以复现")
    ap.add_argument("--video", action="store_true", help="出图后继续把每张图转成短视频")
    ap.add_argument("--styles", action="store_true", help="只列出可用风格包")
    args = ap.parse_args()

    if args.styles:
        for s in list_styles():
            print(f"  {s['key']:<12} {s['zh']:<8} {s['ckpt']}")
        return 0
    if not args.instruction:
        ap.error("请给出画面指令，或用 --styles 查看风格包")

    def _prog(stage: str, payload: dict):
        if stage == "submit":
            print(f"\n[{payload['index']}/{payload['total']}] 提示词: {payload['prompt'][:150]}…", flush=True)
        elif stage == "done":
            print(f"[{payload['index']}/{payload['total']}] 完成 {payload['url']}", flush=True)

    results = asyncio.run(generate(args.instruction, variants=args.variants, style=args.style,
                                   ratio=args.ratio, seed=args.seed, on_progress=_prog))
    if args.video:
        async def _run_videos(results: list[dict]):
            print("\n" + "-" * 60 + "\n开始图生视频…")

            async def _vprog(stage, payload):
                print(f"  · {payload.get('stage')}: {str(payload.get('detail',''))[:80]}", flush=True)

            for r in results:
                try:
                    v = await image_to_video(r["file"], r["prompt"], ratio=r["ratio"], seed=r["seed"],
                                             negative=r.get("negative", ""), output_name=r["id"],
                                             on_progress=_vprog)
                    r["video_url"] = v["url"]
                    r["video_mode"] = v["mode"]
                    r["video_engine"] = v["engine"]
                    update_history_video(r["id"], v)
                    print(f"  [OK] {v['mode']} · {v['url']} · {v['elapsed']}s · "
                          f"{v['size_bytes']//1024}KB · {v['engine']}")
                except Exception as e:
                    print(f"  [ERR] 视频失败: {str(e)[:160]}")
            try:
                HISTORY_FILE.write_text(
                    json.dumps(load_history(_HISTORY_MAX), ensure_ascii=False, indent=2),
                    encoding="utf-8")
            except Exception:
                pass

        asyncio.run(_run_videos(results))

    print("\n" + "=" * 60)
    for r in results:
        print(f"\n■ {r['name']}  [{r['style_zh']}] seed={r['seed']} {r['width']}x{r['height']} "
              f"{r['elapsed']}s {r['size_bytes']//1024}KB")
        print(f"  维度: " + " · ".join(f"{k}={v}" for k, v in r["dims"].items()))
        print(f"  文件: {r['file']}")
    print(f"\n共 {len(results)} 张，已记录到 {HISTORY_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
