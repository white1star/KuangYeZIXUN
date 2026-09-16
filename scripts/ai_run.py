from crawler.config import load_settings
from crawler.main import run_once
from scripts import ai_check


def _default_runner(settings):
    return run_once(settings=settings)


def run(runner=None, settings=None) -> int:
    settings = settings or load_settings()
    runner = runner or _default_runner
    print("=" * 46)
    print("AI 巡检开始：第一步 启动爬虫抓取一轮")
    print("=" * 46)
    summary = runner(settings)
    print("各源摘要：")
    print(f"- 信息源：{summary.get('sources_ok', 0)}/{summary.get('sources_total', 0)} 成功，"
          f"{summary.get('sources_error', 0)} 失败")
    print(f"- 文章：抓到 {summary.get('articles_found', 0)} 条，新增 {summary.get('articles_new', 0)} 条")
    print(f"- 价格：{summary.get('prices', 0)} 条")
    for err in summary.get("errors", []):
        print(f"- 失败：{err}")

    print()
    print("第二步 体检并生成报告")
    text, issues, code = ai_check.generate_report(settings)
    print(text)
    path = ai_check.write_report(text, settings)
    print(f"报告已写入：{path}")

    print()
    print("第三步 下一步建议")
    failed = bool(summary.get("sources_error")) or bool(code)
    if failed:
        print("- 存在失败源或体检异常：按 docs/ai-maintenance.md 的「修源四步法」修复，"
              "再运行 python -m scripts.ai_run 复跑验证")
    else:
        print("- 一切正常，无需处理；建议每天定时运行 python -m scripts.ai_run 保持巡检")
    return 1 if failed else 0


def main():
    raise SystemExit(run())


if __name__ == "__main__":
    main()
