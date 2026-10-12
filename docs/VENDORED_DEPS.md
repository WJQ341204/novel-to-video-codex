# Vendored Dependencies（手动管理的第三方依赖）

> 2026-10-12 仓库整理时建立。本文档记录"哪些第三方代码被排除出 git、为什么、怎么恢复"。

## OpenMontage

| 项 | 内容 |
|---|---|
| 上游仓库 | `https://github.com/calesthio/OpenMontage.git` |
| 本地路径 | `OpenMontage/` |
| 体积 | 90 MB / 2104 个文件 |
| 当前 git 状态 | **已 `git rm --cached` 取消跟踪 + 加入 `.gitignore`**（磁盘文件保留，功能不受影响） |

### 它是什么，为什么不能删

OpenMontage 是开源的多智能体视频生产系统（"agentic video production system"）。
在本项目里它是**云端视频引擎的底层工具来源**，不是无关的第三方杂物：

- **`engines/cloud.py`** —— 云端视频引擎本体，靠 `sys.path` 注入 `OpenMontage/` 目录 +
  懒加载封装它的 provider 工具。`settings.yaml` 里 `cloud.priority` 那 10 个云端引擎
  （`seedance_ark` / `kling_official` / `minimax` / `jimeng` / `grok` / `fal_*` / `runway` / `veo`）
  **全部靠它实现**。
- **`engines/cli.py`** —— 从 `OpenMontage/.env` 读取各云端 provider 的 API key。
- **`scheduler/cost.py`** —— 成本治理借鉴其 `tools/cost_tracker.py` 思路。
- **`tests/`** 4 个测试 —— 用 `OpenMontage/projects/overtime-cat/renders/final.mp4` 当测试素材。

### 为什么取消跟踪

它是在 `32c544e`（LuminaForge v12.3）时**整目录快照导入**的，之后本仓只有这 1 个 commit
碰过它，从未跟随上游更新。它占主仓 90MB，是 GitHub 仓库体积（235MB）的最大单一来源之一。

取消跟踪后主仓体积从 **235MB 降到约 145MB**，且磁盘上的文件原样保留，
本地运行（含云端引擎，若启用）完全不受影响。

### 为什么没做成 git submodule

理论上更"正规"的做法是 `git submodule add`，但有个现实障碍：
本地这份是 v12.3 时打的**快照**，无法确定它对应上游哪个 commit。
若 submodule 指向上游 HEAD，`git submodule update` 会用一个**不同版本**覆盖这份已验证可用的快照，
可能破坏 `engines/cloud.py` 依赖的 provider 接口。因此在没有确定可锁定的 commit 之前，
选择"取消跟踪 + 手动管理"这一更稳的方案。

**后续若要升级为 submodule**，需先确定要锁定的上游 commit（对比本地快照与上游历史），
再执行：
```bash
git rm -r --cached OpenMontage
git submodule add <locked-commit-url> OpenMontage
```

### 怎么恢复（换机器 / 重新 clone 后）

```powershell
# 在仓库根执行
powershell -ExecutionPolicy Bypass -File scripts\fetch_openmontage.ps1
```

脚本会 `git clone --depth 1` 上游到 `OpenMontage/`，并从 `.env.example` 复制出 `.env`
（需手动填入真实 API key）。

### 影响面说明

- 当前 `settings.yaml` 为 `video_mode: local`、`local_kind: wan5b`，
  **云端链路未启用**，所以缺失 OpenMontage 时本地出片主链完全正常。
- 只有切到 `video_mode: cloud` / `hybrid`，或运行 `tests/` 下那 4 个依赖它的测试时，
  才需要 OpenMontage 在位。
