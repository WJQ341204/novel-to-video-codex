"""H3 自托管服务 schema 探针。

用途
----
昇腾 910B 上的 H3 服务起来后，先跑本脚本抓一次**真实**接口 schema / 响应形状，
据此校准 engines/h3_ascend.py 里的 _extract_video_url / _extract_audio_url 解析。

默认只探 schema（GET 健康检查 + openapi + 模型列表），**不生成视频、零推理成本**；
加 --generate 才发一次最小生成请求，用来抓真实响应字段名（会消耗一次推理）。

用法
----
    export H3_ASCEND_URL=http://<服务器IP>:9098      # 必填
    export H3_ASCEND_TOKEN=...                       # 可选（服务有鉴权时）

    python scripts/h3_schema_probe.py                # 只探 schema
    python scripts/h3_schema_probe.py --generate     # 额外发一次最小生成
    python scripts/h3_schema_probe.py --out my.json  # 指定输出文件

输出：终端摘要 + JSON 落盘（默认 output/h3_schema_probe.json）。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional

# 常见的 OpenAPI schema 挂载点（不同版本 vLLM / FastAPI 挂载位置可能不同）
SCHEMA_PATHS = [
    "/openapi.json",
    "/docs/oas.json",
    "/v1/openapi.json",
    "/api/openapi.json",
]
HEALTH_PATHS = ["/health", "/v1/health", "/ping"]
MODELS_PATHS = ["/v1/models", "/models"]


def _http(
    base: str, path: str, token: Optional[str], timeout: float
) -> tuple[int, str]:
    """GET 一个路径，返回 (状态码, 响应文本)。失败返回 (0, 原因)。"""
    url = base.rstrip("/") + path
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "ignore")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "ignore") if exc.fp else ""
        return exc.code, body
    except urllib.error.URLError as exc:
        return 0, f"UNREACHABLE: {exc.reason}"
    except Exception as exc:  # noqa: BLE001
        return 0, f"ERROR: {exc}"


def _try_first_ok(
    base: str, paths: list[str], token: Optional[str], timeout: float
) -> dict:
    """依次尝试候选路径，返回首个 200 的结果及尝试记录。"""
    attempts: list[dict] = []
    for p in paths:
        code, text = _http(base, p, token, timeout)
        rec = {"path": p, "status": code, "bytes": len(text)}
        if code == 200 and text.strip():
            rec["ok"] = True
            try:
                rec["json"] = json.loads(text)
            except json.JSONDecodeError:
                rec["text_head"] = text[:400]
            attempts.append(rec)
            return {"hit_path": p, "attempts": attempts, "ok": True}
        attempts.append(rec)
    return {"hit_path": None, "attempts": attempts, "ok": False}


def probe_schema(base: str, token: Optional[str], timeout: float) -> dict:
    print(f"[1/3] 探测 schema … {base}")
    res = _try_first_ok(base, SCHEMA_PATHS, token, timeout)
    print(f"      {'命中 ' + res['hit_path'] if res['ok'] else '未命中任何 schema 路径'}")
    return res


def probe_health(base: str, token: Optional[str], timeout: float) -> dict:
    print("[2/3] 探测健康检查 …")
    res = _try_first_ok(base, HEALTH_PATHS, token, timeout)
    print(f"      {'命中 ' + str(res['hit_path']) if res['ok'] else '未命中（服务可能未提供 health 端点）'}")
    return res


def probe_models(base: str, token: Optional[str], timeout: float) -> dict:
    print("[3/3] 探测模型列表 …")
    res = _try_first_ok(base, MODELS_PATHS, token, timeout)
    if res["ok"]:
        for a in res["attempts"]:
            if isinstance(a.get("json"), dict) and "data" in a["json"]:
                ids = [d.get("id") for d in a["json"]["data"] if isinstance(d, dict)]
                print(f"      models: {ids}")
                break
    else:
        print("      未命中模型列表端点")
    return res


def probe_generate(base: str, token: Optional[str], timeout: float) -> dict:
    """发一次最小生成请求，抓真实响应形状（会消耗一次推理）。"""
    print("[extra] 发送最小生成请求（会消耗一次推理）…")
    body = {
        "model": os.environ.get("H3_ASCEND_MODEL", "MiniMax-H3"),
        "prompt": "a lantern reflected on wet stone, slow push in",
        "width": 672,
        "height": 1152,
        "duration": 2,
        "fps": 24,
        "task_type": "t2va",
    }
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        base.rstrip("/") + "/v1/videos", data=data, method="POST", headers=headers
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode("utf-8", "ignore")
            print(f"      status={resp.status} bytes={len(text)}")
            try:
                return {"status": resp.status, "json": json.loads(text)}
            except json.JSONDecodeError:
                return {"status": resp.status, "text_head": text[:800]}
    except urllib.error.HTTPError as exc:
        b = exc.read().decode("utf-8", "ignore") if exc.fp else ""
        print(f"      HTTP {exc.code}: {b[:300]}")
        return {"status": exc.code, "text_head": b[:800]}
    except urllib.error.URLError as exc:
        print(f"      UNREACHABLE: {exc.reason}")
        return {"status": 0, "error": str(exc.reason)}


def summarize(report: dict) -> None:
    """终端打印关键结论：schema 里与视频/音频解析相关的字段。"""
    print("\n===== 摘要 =====")
    sch = report.get("schema", {})
    if sch.get("ok"):
        for a in sch["attempts"]:
            js = a.get("json")
            if isinstance(js, dict) and "paths" in js:
                paths = js["paths"]
                hits = [p for p in paths if "video" in p.lower()]
                print(f"schema 来源: {a['path']}")
                print(f"  含 video 的路径: {hits[:10]}")
                for p in hits[:3]:
                    for method, spec in paths[p].items():
                        if not isinstance(spec, dict):
                            continue
                        schema = (
                            spec.get("requestBody", {})
                            .get("content", {})
                            .get("application/json", {})
                            .get("schema", {})
                        )
                        if schema:
                            print(f"  {method.upper()} {p} 请求字段: {list(_refs(schema, js))[:20]}")
                break
    else:
        print("未抓到 openapi schema —— 请把下面 JSON 里 generate 的实际返回发给维护者校准")

    gen = report.get("generate")
    if gen:
        print(f"生成响应 status={gen.get('status')}")
        if "json" in gen:
            print("  顶层字段:", list(gen["json"].keys())[:20])
    print("================")


def _refs(schema: dict, root: dict) -> list[str]:
    """从 schema 里尽量解析出字段名（处理 $ref 到 components.schemas）。"""
    if "$ref" in schema:
        name = schema["$ref"].split("/")[-1]
        target = root.get("components", {}).get("schemas", {}).get(name, {})
        return list(target.get("properties", {}).keys())
    return list(schema.get("properties", {}).keys())


def main() -> int:
    ap = argparse.ArgumentParser(description="H3 自托管服务 schema 探针")
    ap.add_argument("--url", default=os.environ.get("H3_ASCEND_URL", ""),
                    help="H3 服务地址，默认读 H3_ASCEND_URL")
    ap.add_argument("--token", default=os.environ.get("H3_ASCEND_TOKEN"),
                    help="Bearer token，默认读 H3_ASCEND_TOKEN")
    ap.add_argument("--timeout", type=float, default=30.0, help="单次请求超时秒数")
    ap.add_argument("--generate", action="store_true",
                    help="额外发一次最小生成请求（消耗一次推理）")
    ap.add_argument("--out", default="", help="输出 JSON 路径")
    args = ap.parse_args()

    if not args.url:
        print("错误：未配置 H3 服务地址。请先 export H3_ASCEND_URL=http://<服务器IP>:9098",
              file=sys.stderr)
        return 2

    report: dict[str, Any] = {
        "url": args.url,
        "schema": probe_schema(args.url, args.token, args.timeout),
        "health": probe_health(args.url, args.token, args.timeout),
        "models": probe_models(args.url, args.token, args.timeout),
    }
    if args.generate:
        report["generate"] = probe_generate(args.url, args.token, args.timeout)

    out = Path(args.out) if args.out else Path("output/h3_schema_probe.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n已落盘: {out.resolve()}")

    summarize(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
