"""deploy.sh rsync 排除规则的回归守卫。

2026-09-30 第 5 次部署事故的根因:根级运行时排除 `--exclude 'data/'` 未加锚定,
命中任意深度同名目录,把代码目录 app/tools/data/(fetcher 拆分模块、consensus、
option_signals、qvix_store)整体冻结在服务器旧快照——新镜像缺模块启动即崩,
健康检查门自动回滚。该 bug 还以沉默症状存在了数日(smoke 的 option 检查一直
ImportError SKIP)。

两条规则把这类 bug 钉死在 CI 层:
1. 根级运行时排除必须带前导 '/' 锚定(只匹配传输根);
2. 未锚定的目录排除不得遮蔽代码根(app/、frontend/src)下的任何真实目录
   ——缓存/状态产物(__pycache__、.omc 等)除外,它们任意深度排除是正确行为。
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DEPLOY_SH = REPO_ROOT / "deploy" / "deploy.sh"

# 根级运行时排除:必须以锚定形式出现,且不得残留未锚定变体。
ANCHORED_RUNTIME_EXCLUDES = ("/.env", "/.env.*", "/data/", "/logs/")
BANNED_UNANCHORED_VARIANTS = (".env", ".env.*", "data/", "logs/")

# 未锚定排除的合法名单:缓存/状态产物,任意深度排除正确。
# app/、frontend/src 下真实存在的此类目录(如 __pycache__、.omc)不构成遮蔽。
UNANCHORED_ARTIFACT_ALLOWLIST = frozenset(
    {
        "__pycache__",
        ".omc",
        ".claude",
        ".git",
        "node_modules",
    }
)

# 未锚定排除若遮蔽这些代码根下的目录即为 bug。
CODE_ROOTS = ("app", "frontend/src")


def _rsync_exclude_patterns() -> list[str]:
    """提取 deploy.sh rsync 命令里的全部 --exclude 模式。"""
    text = DEPLOY_SH.read_text(encoding="utf-8")
    # rsync 块从 "rsync -avz" 起到行尾续行符结束的命令序列
    match = re.search(r"rsync\s+-avz.*?(?=\n\S|\Z)", text, re.DOTALL)
    assert match is not None, "deploy.sh 未找到 rsync 命令块"
    return re.findall(r"--exclude\s+'([^']+)'", match.group(0))


def _is_anchored(pattern: str) -> bool:
    return pattern.startswith("/")


class TestRootRuntimeExcludesAnchored:
    def test_root_runtime_excludes_present_and_anchored(self):
        patterns = _rsync_exclude_patterns()
        for required in ANCHORED_RUNTIME_EXCLUDES:
            assert required in patterns, (
                f"deploy.sh 缺少锚定的根级运行时排除 '{required}' —— 未锚定版本会"
                "命中任意深度同名目录(见 2026-09-30 部署回滚事故)"
            )

    def test_unanchored_runtime_variants_absent(self):
        patterns = _rsync_exclude_patterns()
        for banned in BANNED_UNANCHORED_VARIANTS:
            assert banned not in patterns, (
                f"deploy.sh 存在未锚定排除 '{banned}' —— 请改为前导 '/' 锚定,"
                "否则嵌套同名代码目录会被冻结在服务器旧快照"
            )


class TestUnanchoredExcludesDoNotShadowCodeDirs:
    def test_no_unanchored_exclude_matches_code_root_directory(self):
        patterns = _rsync_exclude_patterns()
        # 目录名型未锚定模式(无 '/',非锚定)
        dir_patterns = {
            p.rstrip("/"): p
            for p in patterns
            if not _is_anchored(p) and "/" not in p and "*" not in p
        }

        shadowed: list[str] = []
        for code_root in CODE_ROOTS:
            root = REPO_ROOT / code_root
            if not root.is_dir():
                continue
            for directory in root.rglob("*"):
                if not directory.is_dir() or directory.name in UNANCHORED_ARTIFACT_ALLOWLIST:
                    continue
                if directory.name in dir_patterns:
                    shadowed.append(
                        f"排除 '{dir_patterns[directory.name]}' 遮蔽代码目录 {directory}"
                    )

        assert not shadowed, (
            "未锚定目录排除遮蔽了代码根下的真实目录(rsync 会静默跳过传输,"
            "服务器旧快照残留、镜像缺文件):\n" + "\n".join(shadowed)
        )
