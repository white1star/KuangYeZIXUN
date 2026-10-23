# -*- coding: utf-8 -*-
"""问答评测：跑 config/ask_eval.yaml，对比模型意图与期望。

用法：
  python -m tools.eval_ask                # 本地直连模型（需要 config/ask.local.yaml 里的 key）
  python -m tools.eval_ask --http URL     # 打线上接口，只比对返回的 intent
  python -m tools.eval_ask -v             # 打印每条结果

只校验语义（动作/品种/地区/天数），不校验数字。
"""
import argparse
import json
import sys
from pathlib import Path

import requests
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from site_build.search import province_of

ROOT = Path(__file__).resolve().parent.parent
EVAL_FILE = ROOT / "config" / "ask_eval.yaml"


def load_cases() -> list:
    return yaml.safe_load(EVAL_FILE.read_text(encoding="utf-8")) or []


def run_local(cases: list) -> list:
    sys.path.insert(0, str(ROOT))
    from web import ask_api

    conn, _ = ask_api.connect()
    try:
        commodities, provinces, markets, categories = ask_api.catalog(conn)
        aliases = ask_api.load_aliases()
        conf = ask_api.load_ask_config()
        results = []
        for case in cases:
            q = str(case.get("q") or "")
            try:
                raw = ask_api.llm_parse(conf, q, [], commodities, provinces, categories, markets)
                intent, notes, problems = ask_api.normalize_intent(
                    raw, commodities, provinces, markets, categories, aliases)
            except Exception as exc:
                results.append({"q": q, "want": case, "got": None, "error": str(exc)[:120]})
                continue
            results.append({"q": q, "want": case, "got": intent, "notes": notes})
        return results
    finally:
        conn.close()


def run_http(cases: list, base: str) -> list:
    results = []
    for case in cases:
        q = str(case.get("q") or "")
        try:
            resp = requests.post(base.rstrip("/") + "/ask",
                                 json={"question": q, "history": []}, timeout=40)
            data = resp.json()
        except Exception as exc:
            results.append({"q": q, "want": case, "got": None, "error": str(exc)[:120]})
            continue
        results.append({"q": q, "want": case, "got": data.get("intent"),
                        "error": "" if data.get("ok") else data.get("error", "")})
    return results


def check(want: dict, got: dict) -> tuple:
    """返回 (是否通过, 差异说明)。"""
    if not got:
        return False, "无返回"
    want_action = (want.get("action") or "price").strip()
    got_action = (got.get("action") or "").strip()
    if want_action != got_action:
        return False, f"action {got_action} != {want_action}"
    if want.get("commodity") is not None:
        if (want.get("commodity") or "") != (got.get("commodity") or ""):
            return False, f"commodity {got.get('commodity')} != {want.get('commodity')}"
    if want.get("category") is not None:
        if (want.get("category") or "") != (got.get("category") or ""):
            return False, f"category {got.get('category')} != {want.get('category')}"
    if want.get("regions") is not None:
        # 地区按"省"归一比较：唐山（市场）与河北（省）视为同一地区
        def keys(items):
            out = set()
            for r in items or []:
                prov = province_of(r)
                out.add(prov or str(r))
            return out
        if keys(want.get("regions")) != keys(got.get("regions")):
            return False, f"regions {got.get('regions')} != {want.get('regions')}"
    if want.get("days") is not None:
        if int(want["days"]) != int(got.get("days") or 0):
            return False, f"days {got.get('days')} != {want.get('days')}"
    return True, ""


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="问答评测")
    parser.add_argument("--http", default="", help="打线上接口，如 http://127.0.0.1/KuangYeZIXUN/api")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    cases = load_cases()
    if not cases:
        print("评测集为空")
        return 2
    results = run_http(cases, args.http) if args.http else run_local(cases)

    passed = 0
    failures = []
    for item in results:
        ok, why = check(item["want"], item.get("got"))
        if item.get("error"):
            ok, why = False, item["error"]
        if ok:
            passed += 1
        else:
            failures.append((item["q"], why, item.get("got")))
        if args.verbose or not ok:
            mark = "[OK]" if ok else "[XX]"
            print(f"{mark} {item['q']}")
            if not ok:
                print(f"    {why}")
                if item.get("got"):
                    print(f"    实际: {json.dumps(item['got'], ensure_ascii=False)}")

    total = len(results)
    rate = passed / total * 100
    print(f"\n通过 {passed}/{total}（{rate:.1f}%）")
    if failures:
        print("失败清单:")
        for q, why, _ in failures:
            print(f"  - {q} → {why}")
    return 0 if rate >= 90 else 1


if __name__ == "__main__":
    sys.exit(main())
