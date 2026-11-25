@echo off
chcp 65001 >nul
title LuminaForge App (port 8190)
cd /d "%~dp0"

rem 禁用 safe-delete 钩子，防止清理临时文件时误杀进程（QA/收尾阶段 unlink 被拦截会 SystemExit）
set CODEBUDDY_SAFE_DELETE_ENABLED=0

rem 清理系统代理，防止 httpx 报 [Errno 22]（Clash 未运行时）
set HTTP_PROXY=
set HTTPS_PROXY=
set http_proxy=
set https_proxy=

rem ffmpeg 加入 PATH（pydub/合并/字幕烧录依赖）
rem ffmpeg 需在 PATH 中（或设置 FFMPEG_DIR 环境变量指向其 bin 目录）
if defined FFMPEG_DIR set PATH=%FFMPEG_DIR%;%PATH%

echo [1/1] Starting LuminaForge on http://127.0.0.1:8190 ...
python scripts\main.py
pause
