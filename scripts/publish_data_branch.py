import argparse
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class GitResult:
    def __init__(self, completed):
        self.returncode = completed.returncode
        self.stdout = completed.stdout.decode("utf-8", "replace")
        self.stderr = completed.stderr.decode("utf-8", "replace")


def git(args, input_bytes=None, check=True):
    completed = subprocess.run(
        ["git", *args], cwd=str(ROOT), input=input_bytes, capture_output=True)
    result = GitResult(completed)
    if check and result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout).strip())
    return result


def build_tree(db_path: Path) -> str:
    blob = git(["hash-object", "-w", str(db_path)]).stdout.strip()
    subtree = git(["mktree"],
                  input_bytes=f"100644 blob {blob}\tnews.db\n".encode("utf-8")).stdout.strip()
    return git(["mktree"],
               input_bytes=f"040000 tree {subtree}\tdata\n".encode("utf-8")).stdout.strip()


def commit_tree(tree: str, message: str) -> str:
    return git(["-c", "user.name=矿news静态发布", "-c", "user.email=noreply@local",
                "commit-tree", tree, "-m", message]).stdout.strip()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="把本地 data/news.db 发布到 data 分支（不占用工作区、不切分支）")
    parser.add_argument("--db", default=str(ROOT / "data" / "news.db"))
    parser.add_argument("--remote", default="origin")
    parser.add_argument("--branch", default="data")
    parser.add_argument("--message", default="data: 初始化数据分支（含回填数据）")
    parser.add_argument("--dry-run", action="store_true", help="只生成提交对象，不推送")
    args = parser.parse_args(argv)
    db = Path(args.db)
    if not db.exists():
        print(f"数据库不存在：{db}")
        return 1
    inside = git(["rev-parse", "--is-inside-work-tree"], check=False)
    if inside.returncode != 0:
        print("当前目录不是 git 仓库")
        return 1
    remote = git(["remote", "get-url", args.remote], check=False)
    if remote.returncode != 0:
        print(f"未配置远程仓库 {args.remote}，请先执行：")
        print(f"  git remote add {args.remote} https://github.com/<用户名>/<仓库>.git")
        return 1
    tree = build_tree(db)
    commit = commit_tree(tree, args.message)
    size_mb = db.stat().st_size / 1048576
    print(f"已生成数据提交 {commit[:12]}（{db}，{size_mb:.1f} MB）")
    if args.dry_run:
        print("dry-run：不执行推送")
        return 0
    git(["push", "-f", args.remote, f"{commit}:refs/heads/{args.branch}"])
    print(f"已强推到 {args.remote}/{args.branch}（该分支只保留这一条提交）")
    print("之后在 GitHub Actions 页手动 Run 一次『抓取并部署静态站』即可验证")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
