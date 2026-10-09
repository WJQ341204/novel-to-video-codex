"""MiniMax H3 自托管引擎（昇腾 910B 服务器）。

与 engines/cloud.py 里的 `minimax` 云端 API 不同：本引擎对接**你自己的**
Ascend 910B 服务器上跑的 vLLM-Omni / SGLang H3 服务（OpenAI 兼容 /v1/videos）。
权重免费、算力在你自己硬件上，cost_usd 恒为 0。

接入方式（settings.yaml / 代码）：
    engines:
      video_mode: local
      local:
        local_kind: h3_ascend

环境变量：
    H3_ASCEND_URL   服务地址，默认 http://127.0.0.1:9098
    H3_ASCEND_TOKEN 可选 Bearer token（若服务加了鉴权）
    H3_ASCEND_MODEL  模型名，默认 MiniMax-H3

实现用标准库 urllib（无额外依赖）；HTTP 阻塞调用经 asyncio.to_thread 异步化。

未来接口（H3 omni 特性，本次已接上，待真机 schema 校准）：
  - task_type 路由：t2va（纯文生视频）/ fl2va（首帧生视频）/ ref2va（参考图生视频），
    未显式指定时由首帧/参考图自动推断。
  - 原生同步音频：generate_audio=True 时请求 H3 原生音频，抽取后落盘到 <name>_h3audio.<ext>，
    并通过 ClipResult.audio_path 暴露给下游（默认 False，与既有「视频+外部TTS」管线解耦）。
  - ref2va 参考图：req.reference_images 以 base64 内联传给 H3。

⚠️ 部署与接口字段需按你的服务器实际 OpenAPI schema 校验一次：
   见 docs/H3_ASCEND_DEPLOY.md 与 scripts/deploy_h3_ascend.sh。
   响应解析对常见字段名（video/audio/url/b64_json…）做了宽松兼容，真机返回形状可能略有差异。
"""
from __future__ import annotations

import asyncio
import base64
import binascii
import json
import mimetypes
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional

from .base import (
    BaseEngine,
    ClipResult,
    EngineError,
    GenerateRequest,
    ProviderUnavailable,
)


def _b64_data_uri(path: Path) -> str:
    """把图片读成 data URI，vLLM-Omni 多数接受 base64 内联。"""
    mime = mimetypes.guess_type(str(path))[0] or "image/png"
    raw = path.read_bytes()
    return f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"


def _extract_video_url(payload: dict) -> Optional[str]:
    """从常见 OpenAI 兼容响应形状里抠出视频 URL / data URI。"""
    data = payload.get("data")
    if isinstance(data, list) and data:
        item = data[0]
        if isinstance(item, dict):
            v = item.get("video") or item.get("b64_json") or item.get("url")
            if isinstance(v, dict):
                v = v.get("url")
            if v:
                return v
    for key in ("video_url", "video", "url"):
        v = payload.get(key)
        if isinstance(v, str):
            return v
        if isinstance(v, dict) and v.get("url"):
            return v["url"]
    return None


def _extract_audio_url(payload: dict) -> Optional[str]:
    """从 H3 omni 响应里抠出原生音频 URL / data URI（宽松兼容多种字段名）。"""
    data = payload.get("data")
    if isinstance(data, list) and data:
        item = data[0]
        if isinstance(item, dict):
            a = item.get("audio") or item.get("audio_url") or item.get("audio_base64")
            if isinstance(a, dict):
                a = a.get("url") or a.get("b64")
            if isinstance(a, str):
                return a
    for key in ("audio_url", "audio", "audio_base64"):
        v = payload.get(key)
        if isinstance(v, str):
            return v
        if isinstance(v, dict) and (v.get("url") or v.get("b64")):
            return v.get("url") or v.get("b64")
    return None


class H3AscendEngine(BaseEngine):
    """自托管 MiniMax H3（昇腾 910B）引擎。kind=hybrid：算力在你自己硬件，经 HTTP 调用。"""

    name = "h3_ascend"
    kind = "hybrid"          # 自托管远程服务
    capability = "both"      # t2va / fl2va / ref2va 均支持

    def __init__(
        self,
        url: Optional[str] = None,
        token: Optional[str] = None,
        model: Optional[str] = None,
        timeout: float = 900.0,
    ):
        self.url = (url or os.environ.get("H3_ASCEND_URL", "http://127.0.0.1:9098")).rstrip("/")
        self.token = token or os.environ.get("H3_ASCEND_TOKEN")
        self.model = model or os.environ.get("H3_ASCEND_MODEL", "MiniMax-H3")
        self.timeout = timeout

    # ─── 可用性 ────────────────────────────────────────────────
    def is_available(self) -> bool:
        # 标准库 urllib 必然可用；只需 URL 已配置
        return bool(self.url)

    def estimate_cost(self, req: GenerateRequest) -> float:
        return 0.0  # 自托管，自有算力，不计费

    def describe(self) -> str:
        return f"MiniMax H3 @ {self.url} (self-hosted Ascend 910B, 不计费)"

    # ─── HTTP 底层（同步 + to_thread 异步化）──────────────────
    def _request(self, method: str, path: str, body: Optional[dict] = None) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(
            f"{self.url}{path}", data=data, method=method, headers=headers
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "ignore")[:500] if exc.fp else ""
            raise EngineError(f"H3 服务返回 {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise EngineError(f"H3 服务通信失败：{exc.reason}") from exc
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise EngineError(f"H3 响应非 JSON：{raw[:200]}") from exc

    def _get_bytes(self, url: str) -> bytes:
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {self.token}"} if self.token else {})
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return resp.read()

    # ─── 生成 ──────────────────────────────────────────────────
    async def generate(self, req: GenerateRequest) -> ClipResult:
        if not self.url:
            raise ProviderUnavailable("未配置 H3_ASCEND_URL（自托管 H3 服务地址）")

        body: dict[str, Any] = {
            "model": self.model,
            "prompt": req.prompt,
            "width": req.width,
            "height": req.height,
            "duration": req.duration_seconds,
            "fps": req.fps,
        }
        if req.seed is not None:
            body["seed"] = req.seed
        if req.negative_prompt:
            body["negative_prompt"] = req.negative_prompt
        if req.first_frame and Path(req.first_frame).exists():
            body["first_frame"] = _b64_data_uri(Path(req.first_frame))
        if req.last_frame and Path(req.last_frame).exists():
            body["last_frame"] = _b64_data_uri(Path(req.last_frame))

        # ── 未来接口 1：task_type 路由（t2va / fl2va / ref2va）──
        has_first = bool(req.first_frame and Path(req.first_frame).exists())
        has_refs = any(Path(p).exists() for p in req.reference_images)
        if req.task_type:
            body["task_type"] = req.task_type
        elif has_first:
            body["task_type"] = "fl2va"
        elif has_refs:
            body["task_type"] = "ref2va"
        else:
            body["task_type"] = "t2va"

        # ── 未来接口 2：ref2va 参考图（角色一致性）──
        if has_refs:
            refs = [_b64_data_uri(Path(p)) for p in req.reference_images if Path(p).exists()]
            if refs:
                body["reference_images"] = refs

        # ── 未来接口 3：原生同步音频（omni 核心）──
        if req.generate_audio:
            body["generate_audio"] = True
            if req.audio_prompt:
                body["audio_prompt"] = req.audio_prompt

        out_dir = Path(req.output_dir) if req.output_dir else Path.cwd()
        out_dir.mkdir(parents=True, exist_ok=True)
        out_name = req.output_name or f"h3_{req.task_id or 'clip'}"
        out_path = out_dir / f"{out_name}.mp4"

        # 1) 提交生成
        payload = await asyncio.to_thread(self._request, "POST", "/v1/videos", body)

        # 2) 同步返回视频（+可选音频）→ 直接取 URL
        video_ref = _extract_video_url(payload)
        if video_ref:
            await self._save_video(video_ref, out_path)
            audio_path = await self._save_audio(
                _extract_audio_url(payload) if req.generate_audio else None,
                out_dir, out_name,
            )
            return self._result(out_path, req, body.get("seed"), audio_path)

        # 3) 异步任务 → 轮询 task_id
        task_id = payload.get("id") or payload.get("task_id") or (
            payload.get("data", [{}])[0].get("id") if isinstance(payload.get("data"), list) else None
        )
        if task_id:
            done = await self._poll_task(task_id)
            video_ref = _extract_video_url(done)
            audio_ref = _extract_audio_url(done) if req.generate_audio else None
            if not video_ref:
                raise EngineError(f"H3 任务完成但无视频：{str(done)[:300]}")
            await self._save_video(video_ref, out_path)
            audio_path = await self._save_audio(audio_ref, out_dir, out_name)
            return self._result(out_path, req, body.get("seed"), audio_path)

        raise EngineError(f"无法从 H3 响应解析视频：{str(payload)[:500]}")

    # ─── 内部工具 ──────────────────────────────────────────────
    async def _poll_task(self, task_id: str) -> dict:
        """轮询异步任务，返回最终完整 payload（含视频与音频引用）。"""
        steps = max(1, int(self.timeout) // 5)
        for _ in range(steps):
            await asyncio.sleep(5)
            p = await asyncio.to_thread(self._request, "GET", f"/v1/videos/{task_id}")
            if p.get("status") in ("succeeded", "completed", "success"):
                return p
            if p.get("status") in ("failed", "error"):
                raise EngineError(f"H3 任务失败：{str(p)[:300]}")
        raise EngineError("H3 任务轮询超时")

    async def _save_video(self, video_ref: str, out_path: Path) -> None:
        if video_ref.startswith("data:"):
            try:
                b64 = video_ref.split(",", 1)[1]
                out_path.write_bytes(base64.b64decode(b64))
            except (IndexError, binascii.Error) as exc:
                raise EngineError(f"视频 data URI 解码失败：{exc}") from exc
            return
        raw = await asyncio.to_thread(self._get_bytes, video_ref)
        out_path.write_bytes(raw)

    async def _save_audio(self, audio_ref: Optional[str], out_dir: Path, out_name: str) -> Optional[Path]:
        """保存 H3 原生音频；无引用则返回 None。扩展名按 data URI mime 推断。"""
        if not audio_ref:
            return None
        if audio_ref.startswith("data:"):
            try:
                mime = audio_ref.split(";")[0].split("/")[-1].lower()
                ext = "." + mime if mime in ("wav", "mp3", "ogg", "m4a", "aac") else ".wav"
                b64 = audio_ref.split(",", 1)[1]
                ap = out_dir / f"{out_name}_h3audio{ext}"
                ap.write_bytes(base64.b64decode(b64))
                return ap
            except (IndexError, binascii.Error) as exc:
                raise EngineError(f"音频 data URI 解码失败：{exc}") from exc
        ap = out_dir / f"{out_name}_h3audio.wav"
        raw = await asyncio.to_thread(self._get_bytes, audio_ref)
        ap.write_bytes(raw)
        return ap

    def _result(self, out_path: Path, req: GenerateRequest, seed, audio_path: Optional[Path] = None) -> ClipResult:
        return ClipResult(
            video_path=out_path,
            engine=self.name,
            cost_usd=0.0,
            duration_seconds=req.duration_seconds,
            seed=seed,
            model=self.model,
            audio_path=audio_path,
        )


if __name__ == "__main__":
    # 自检：需先启动 H3 服务并设置 H3_ASCEND_URL
    async def _self_test():
        eng = H3AscendEngine()
        print("available:", eng.is_available(), "|", eng.describe())
        if not eng.is_available():
            print("跳过：未配置 H3_ASCEND_URL")
            return
        req = GenerateRequest(
            prompt="雨夜，青石板上积水倒映灯笼，缓慢推镜",
            width=960, height=1728, duration_seconds=5, fps=24,
            output_dir=Path("."), output_name="h3_selftest",
        )
        clip = await eng.generate(req)
        print("OK ->", clip.video_path, f"({clip.video_path.stat().st_size} bytes)")

    asyncio.run(_self_test())
