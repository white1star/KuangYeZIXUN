import argparse

from crawler.main import run_once
from scripts.publish_data_branch import publish


def run(runner=None, publisher=None, settings=None) -> int:
    runner = runner or run_once
    publisher = publisher or publish
    try:
        if settings is None:
            summary = runner()
        else:
            summary = runner(settings=settings)
    except Exception as e:
        print(f"抓取失败：{e}")
        return 1
    total = int(summary.get("sources_total", 0))
    ok = int(summary.get("sources_ok", 0))
    failed = int(summary.get("sources_error", 0))
    print(f"抓取摘要：源 {ok}/{total} 成功，文章新增 {summary.get('articles_new', 0)} 条，"
          f"价格 {summary.get('prices', 0)} 条")
    for err in summary.get("errors") or []:
        print(f"  失败源：{err}")
    try:
        commit = publisher()
    except Exception as e:
        print(f"发布失败：{e}")
        return 1
    print(f"发布成功：数据提交 {commit}")
    if total == 0 or failed:
        print("抓取未全部成功，退出码 1（数据已尽量发布）")
        return 1
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="抓取一轮并把 data/news.db 发布到 data 分支")
    parser.parse_args(argv)
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
