"""OmniDoc Pro 一键发布脚本

用法（在项目根目录，按需指定子命令）:
    python scripts/release.py build             # 构建 wheel + sdist
    python scripts/release.py tag v0.2.0        # 打 tag 并 push
    python scripts/release.py release v0.2.0    # 创建 GitHub Release（附 exe/wheel/sdist）
    python scripts/release.py pypi              # 上传到正式 PyPI
    python scripts/release.py all v0.2.0        # build + tag + release + pypi 一条龙
    python scripts/release.py exe               # 单独构建 PyInstaller exe（10-30 分钟）

环境变量（按需）:
    GH_TOKEN        release/all 需要（GitHub OAuth token）
    PYPI_TOKEN      pypi/all 需要（PyPI API token，pypi- 开头）
    PYPI_USERNAME   可选，默认 __token__
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
TOOLS = ROOT / ".tools"
SPEC_CLI = ROOT / "omnidoc.spec"
SPEC_WEB = ROOT / "omnidoc-web.spec"
GH_REPO = "leop017/omnidoc-pro"


def sh(args: list[str], check: bool = True, env: dict | None = None) -> int:
    """运行命令并回显，返回退出码。"""
    # 回显时隐藏 token 类敏感参数
    shown = []
    hide_next = False
    for a in args:
        if hide_next:
            shown.append("***")
            hide_next = False
        elif a in ("-p", "--password"):
            shown.append(a)
            hide_next = True
        else:
            shown.append(a)
    print(f"$ {' '.join(shown)}")
    return subprocess.run(args, cwd=ROOT, check=check, env=env).returncode


def require_dist_artifacts() -> list[Path]:
    files = sorted(DIST.glob("omnidoc_pro-*.whl")) + sorted(DIST.glob("omnidoc_pro-*.tar.gz"))
    if not files:
        sys.exit("f: dist/ 下没有 wheel/sdist，先运行 build")
    return files


def collect_assets() -> list[Path]:
    """收集 release 附件：wheel + sdist + exe。"""
    files = require_dist_artifacts()
    files += sorted(DIST.glob("*.exe"))
    return files


def ensure_twine() -> None:
    """把 twine 装到项目本地 .tools/（TRAE sandbox 不允许写全局 site-packages）。"""
    tools_bin = TOOLS / "bin"
    exe = tools_bin / ("twine.exe" if os.name == "nt" else "twine")
    if not exe.exists():
        TOOLS.mkdir(exist_ok=True)
        print("[setup] 安装 twine 到 .tools/ …")
        sh([sys.executable, "-m", "pip", "install", "-t", str(TOOLS), "twine"])
    os.environ["PYTHONPATH"] = str(TOOLS)


# ── 子命令实现 ─────────────────────────────────────────────────────

def cmd_build(_args: argparse.Namespace) -> None:
    """构建 wheel + sdist 到 dist/。"""
    DIST.mkdir(exist_ok=True)
    for f in DIST.iterdir():
        if f.name.startswith("omnidoc_pro") and f.suffix in (".whl", ".tar.gz"):
            f.unlink()
            print(f"[clean] {f.name}")
    print("[build] 构建 sdist + wheel …")
    sh([sys.executable, "-m", "build", "--outdir", str(DIST)])
    for f in require_dist_artifacts():
        print(f"[build] {f.name}  ({f.stat().st_size // 1024} KB)")


def cmd_exe(args: argparse.Namespace) -> None:
    """用 PyInstaller 构建 exe（很慢，仅当需要附 exe 时跑）。"""
    if not args.skip_cli and SPEC_CLI.exists():
        print(f"[exe] 构建 CLI …")
        sh([sys.executable, "-m", "PyInstaller", str(SPEC_CLI), "--clean", "--noconfirm"])
    if not args.skip_web and SPEC_WEB.exists():
        print(f"[exe] 构建 WebUI …")
        sh([sys.executable, "-m", "PyInstaller", str(SPEC_WEB), "--clean", "--noconfirm"])


def cmd_tag(args: argparse.Namespace) -> None:
    """创建 annotated tag 并 push。"""
    tag = args.tag
    if not re.fullmatch(r"v\d+\.\d+\.\d+(-[.\w]+)?", tag):
        sys.exit(f"f: tag 名不合法: {tag}（期望 vX.Y.Z[-suffix]）")
    r = subprocess.run(["git", "rev-parse", "-q", "--verify", f"refs/tags/{tag}"],
                       cwd=ROOT, capture_output=True)
    if r.returncode == 0:
        print(f"[tag] {tag} 已存在，跳过")
        return
    sh(["git", "tag", "-a", tag, "-m", f"Release {tag}"])
    sh(["git", "push", "origin", tag])
    print(f"[tag] {tag} 已推送")


def _find_release_notes(tag: str) -> Path | None:
    """按 tag 查找 RELEASE_NOTES/x.y.z.md（如 v0.2.0 → 0.2.0.md）。"""
    version = tag.lstrip("vV")
    # 去掉可能的预发布后缀（-alpha / -rc1）
    core = re.split(r"[-+]", version)[0]
    candidate = ROOT / "RELEASE_NOTES" / f"{core}.md"
    if candidate.exists():
        return candidate
    return None


def cmd_release(args: argparse.Namespace) -> None:
    """创建 GitHub Release 并上传附件。"""
    token = os.environ.get("GH_TOKEN")
    if not token:
        sys.exit("f: 缺少 GH_TOKEN 环境变量")
    env = dict(os.environ, GH_TOKEN=token)
    assets = collect_assets()
    args_ = ["gh", "release", "create", args.tag,
             "--title", f"{args.tag} - OmniDoc Pro",
             "--target", "main", "--repo", GH_REPO]
    notes = _find_release_notes(args.tag)
    if notes:
        args_ += ["--notes-file", str(notes)]
        print(f"[release] 使用发布说明: {notes.name}")
    else:
        print(f"[release] 未找到 RELEASE_NOTES/{args.tag.lstrip('vV')}.md，将使用空 notes（可稍后用 gh release edit 补）")
    args_ += [str(a) for a in assets]
    print(f"[release] 附件: {[a.name for a in assets]}")
    sh(args_, env=env)
    print(f"[release] {GH_REPO} @ {args.tag} 创建完成")


def cmd_pypi(args: argparse.Namespace) -> None:
    """上传到正式 PyPI。"""
    token = os.environ.get("PYPI_TOKEN")
    if not token:
        sys.exit("f: 缺少 PYPI_TOKEN 环境变量")
    username = os.environ.get("PYPI_USERNAME", "__token__")
    url = "https://upload.pypi.org/legacy/"
    ensure_twine()
    files = require_dist_artifacts()
    args_ = [sys.executable, "-m", "twine", "upload",
             "-u", username, "-p", token,
             "--repository-url", url] + [str(f) for f in files]
    print(f"[pypi] 目标: 正式 PyPI")
    sh(args_)
    print(f"[pypi] 上传完成: {[f.name for f in files]}")


def cmd_all(args: argparse.Namespace) -> None:
    """build + tag + release + pypi 一条龙。"""
    print("===== [1/4] build =====")
    cmd_build(args)
    if getattr(args, "with_exe", False):
        print("===== [1b/4] exe =====")
        cmd_exe(args)
    print(f"===== [2/4] tag {args.tag} =====")
    cmd_tag(args)
    print("===== [3/4] release =====")
    cmd_release(args)
    print("===== [4/4] pypi =====")
    cmd_pypi(args)
    print("\n[all] 全部完成")


# ── CLI 解析 ───────────────────────────────────────────────────────

def main() -> int:
    p = argparse.ArgumentParser(
        description="OmniDoc Pro 一键发布脚本",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("环境变量")[1],
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("build", help="构建 wheel + sdist 到 dist/")

    pe = sub.add_parser("exe", help="PyInstaller 构建 exe（10-30 分钟）")
    pe.add_argument("--skip-cli", action="store_true")
    pe.add_argument("--skip-web", action="store_true")

    pt = sub.add_parser("tag", help="打 tag 并 push 到 origin")
    pt.add_argument("tag")

    pr = sub.add_parser("release", help="创建 GitHub Release")
    pr.add_argument("tag")

    pp = sub.add_parser("pypi", help="上传到正式 PyPI")

    pa = sub.add_parser("all", help="build + tag + release + pypi 一条龙")
    pa.add_argument("tag")
    pa.add_argument("--with-exe", action="store_true", help="同时构建 exe（很慢）")

    args = p.parse_args()
    {"build": cmd_build, "exe": cmd_exe, "tag": cmd_tag,
     "release": cmd_release, "pypi": cmd_pypi, "all": cmd_all}[args.cmd](args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
