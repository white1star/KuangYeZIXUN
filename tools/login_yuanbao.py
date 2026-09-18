import json
import sys
import time

from playwright.sync_api import sync_playwright

PROFILE = r"C:\Users\Lenovo\AppData\Local\Temp\opencode\yuanbao_edge_profile"
OUT_PATH = r"E:\software\wx-channels-download\cookies.json"
HEADER_PATH = r"E:\矿_news\config\yuanbao_cookie.txt"
LOGIN_HINTS = ("hy", "user", "token", "session", "uid", "ticket", "skey", "login")


def dump(context, logged):
    cookies = [c for c in context.cookies() if "yuanbao" in c.get("domain", "")]
    out = []
    for c in cookies:
        same_site = c.get("sameSite")
        if same_site in ("Lax", "Strict", "None"):
            same_site_out = same_site
        else:
            same_site_out = ""
        out.append({
            "name": c["name"],
            "value": c["value"],
            "domain": c["domain"],
            "path": c.get("path", "/"),
            "secure": bool(c.get("secure")),
            "httpOnly": bool(c.get("httpOnly")),
            "sameSite": same_site_out,
            "expires": int(c.get("expires") or -1),
        })
    with open(OUT_PATH, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)
    header = "; ".join(f"{c['name']}={c['value']}" for c in out)
    with open(HEADER_PATH, "w", encoding="utf-8") as fh:
        fh.write(header)
    print(f"已写入 {OUT_PATH}，共 {len(out)} 条 Cookie，登录检测：{'成功' if logged else '超时未确认'}", flush=True)
    print(f"Cookie 头已备份到 {HEADER_PATH}", flush=True)
    for item in out:
        print("  -", item["name"], f"(域名 {item['domain']}，长度 {len(item['value'])})", flush=True)


def main():
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            channel="msedge",
            user_data_dir=PROFILE,
            headless=False,
            args=["--start-maximized", "--no-first-run", "--no-default-browser-check"],
            no_viewport=True,
        )
        page = context.pages[0] if context.pages else context.new_page()
        try:
            page.goto("https://yuanbao.tencent.com/", timeout=90000, wait_until="domcontentloaded")
        except Exception as exc:
            print("打开页面出错:", exc, flush=True)

        seen = set()
        logged = False
        deadline_seconds = int(sys.argv[1]) if len(sys.argv) > 1 else 420
        deadline = time.time() + deadline_seconds
        while time.time() < deadline:
            cookies = context.cookies()
            names = sorted({c["name"] for c in cookies if "yuanbao" in c.get("domain", "")})
            new_names = [n for n in names if n not in seen]
            if new_names:
                print("新出现的 Cookie:", new_names, flush=True)
                seen.update(names)
            for c in cookies:
                if "yuanbao" in c.get("domain", ""):
                    name = c["name"].lower()
                    if any(hint in name for hint in LOGIN_HINTS) and len(c.get("value", "")) > 12:
                        logged = True
                        break
            if logged:
                print("检测到登录成功!", flush=True)
                break
            time.sleep(3)

        dump(context, logged)
        context.close()


if __name__ == "__main__":
    main()
