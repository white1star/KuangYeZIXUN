import argparse
import subprocess
import time
from pathlib import Path

from crawler.report import log as report_log

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MESSAGE = "data: 初始化数据分支（含回填数据）"
WORKFLOW = ROOT / ".github" / "workflows" / "crawl-deploy.yml"
RETRY_WAITS = (15, 45, 90)


class PublishError(RuntimeError):
    pass


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


def _blob(path: Path) -> str:
    return git(["hash-object", "-w", str(path)]).stdout.strip()


def _tree(entries: list) -> str:
    entries = sorted(entries, key=lambda line: line.split("\t", 1)[1])
    return git(["mktree"],
               input_bytes="".join(entries).encode("utf-8")).stdout.strip()


def build_tree(db_path: Path) -> str:
    db_blob = _blob(db_path)
    data_tree = _tree([f"100644 blob {db_blob}\tnews.db\n"])
    entries = [f"040000 tree {data_tree}\tdata\n"]
    if WORKFLOW.exists():
        wf_blob = _blob(WORKFLOW)
        wf_tree = _tree([f"100644 blob {wf_blob}\tcrawl-deploy.yml\n"])
        gh_tree = _tree([f"040000 tree {wf_tree}\tworkflows\n"])
        entries.append(f"040000 tree {gh_tree}\t.github\n")
    return _tree(entries)


def commit_tree(tree: str, message: str) -> str:
    return git(["-c", "user.name=矿news静态发布", "-c", "user.email=noreply@local",
                "commit-tree", tree, "-m", message]).stdout.strip()


def _push_with_retry(remote, commit, branch, attempts=3, sleep=time.sleep):
    last_error = ""
    for i in range(attempts + 1):
        result = git(["push", "-f", remote, f"{commit}:refs/heads/{branch}"], check=False)
        if result.returncode == 0:
            return
        last_error = (result.stderr or result.stdout).strip()
        tail = last_error.splitlines()[-1] if last_error else "未知错误"
        if i < attempts:
            wait = RETRY_WAITS[min(i, len(RETRY_WAITS) - 1)]
            report_log(f"推送失败（{tail}），{wait} 秒后第 {i + 2} 次重试", name="publish")
            print(f"推送失败（{tail}），{wait} 秒后重试…")
            sleep(wait)
    raise PublishError(f"推送到 {remote}/{branch} 失败（重试 {attempts} 次后仍不通）：{last_error}")


def publish(db_path=None, remote="origin", branch="data", message=None, dry_run=False) -> str:
    db = Path(db_path) if db_path else ROOT / "data" / "news.db"
    if not db.exists():
        raise PublishError(f"数据库不存在：{db}")
    inside = git(["rev-parse", "--is-inside-work-tree"], check=False)
    if inside.returncode != 0:
        raise PublishError("当前目录不是 git 仓库")
    remote_url = git(["remote", "get-url", remote], check=False)
    if remote_url.returncode != 0:
        raise PublishError(f"未配置远程仓库 {remote}，请先执行：\n"
                           f"  git remote add {remote} https://github.com/<用户名>/<仓库>.git")
    tree = build_tree(db)
    commit = commit_tree(tree, message or DEFAULT_MESSAGE)
    size_mb = db.stat().st_size / 1048576
    print(f"已生成数据提交 {commit[:12]}（{db}，{size_mb:.1f} MB）")
    if dry_run:
        print("dry-run：不执行推送")
        return commit[:12]
    report_log(f"开始发布数据提交 {commit[:12]}（{size_mb:.1f} MB）", name="publish")
    _push_with_retry(remote, commit, branch)
    report_log(f"已推送 {remote}/{branch}（提交 {commit[:12]}）", name="publish")
    print(f"已强推到 {remote}/{branch}（该分支只保留这一条提交）")
    print("data 分支更新后 GitHub Actions 会自动构建并部署静态站")
    return commit[:12]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="把本地 data/news.db 发布到 data 分支（不占用工作区、不切分支）")
    parser.add_argument("--db", default=str(ROOT / "data" / "news.db"))
    parser.add_argument("--remote", default="origin")
    parser.add_argument("--branch", default="data")
    parser.add_argument("--message", default=DEFAULT_MESSAGE)
    parser.add_argument("--dry-run", action="store_true", help="只生成提交对象，不推送")
    args = parser.parse_args(argv)
    try:
        publish(db_path=args.db, remote=args.remote, branch=args.branch,
                message=args.message, dry_run=args.dry_run)
    except Exception as e:
        print(e)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
