import json
import sys

from playwright.sync_api import sync_playwright

PROFILE = r"C:\Users\Lenovo\AppData\Local\Temp\opencode\yuanbao_edge_profile"
OUT_JSON = r"E:\software\wx-channels-download\cookies.json"
OUT_HEADER = r"E:\矿_news\config\yuanbao_cookie.txt"


def main():
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            channel="msedge",
            user_data_dir=PROFILE,
            headless=True,
            args=["--no-first-run", "--no-default-browser-check"],
        )
        cookies = [c for c in context.cookies() if "tencent" in c.get("domain", "") or "yuanbao" in c.get("domain", "")]
        print(f"共 {len(cookies)} 条腾讯系 Cookie:")
        for c in cookies:
            print(" -", c["name"], "|", c["domain"], "| 长度", len(c["value"]))

        names = {c["name"] for c in cookies}
        logged = "hy_user" in names and "hy_token" in names and len(next(c["value"] for c in cookies if c["name"] == "hy_token")) > 50
        print("登录态完整:", logged)

        out = []
        for c in cookies:
            same_site = c.get("sameSite")
            if same_site not in ("Lax", "Strict", "None"):
                same_site = ""
            out.append({
                "name": c["name"],
                "value": c["value"],
                "domain": c["domain"],
                "path": c.get("path", "/"),
                "secure": bool(c.get("secure")),
                "httpOnly": bool(c.get("httpOnly")),
                "sameSite": same_site,
                "expires": int(c.get("expires") or -1),
            })
        with open(OUT_JSON, "w", encoding="utf-8") as fh:
            json.dump(out, fh, ensure_ascii=False, indent=2)
        header = "; ".join(f"{c['name']}={c['value']}" for c in out)
        with open(OUT_HEADER, "w", encoding="utf-8") as fh:
            fh.write(header)
        print("已写入:", OUT_JSON)
        print("已写入:", OUT_HEADER)
        context.close()


if __name__ == "__main__":
    main()
