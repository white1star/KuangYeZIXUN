import time
from dataclasses import dataclass

import requests

DEFAULT_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
RETRY_STATUS = (429, 500, 502, 503, 504)


@dataclass
class FetchResult:
    ok: bool
    status: int = 0
    text: str = ""
    final_url: str = ""
    error: str = ""
    elapsed: float = 0.0


def fetch(url, referer="", encoding=None, timeout=15, retries=2, session=None, sleep=time.sleep):
    sess = session or requests.Session()
    headers = {"User-Agent": DEFAULT_UA}
    if referer:
        headers["Referer"] = referer
    result = FetchResult(ok=False, final_url=url)
    for attempt in range(retries + 1):
        started = time.time()
        try:
            resp = sess.get(url, headers=headers, timeout=timeout, allow_redirects=True)
            result.status = resp.status_code
            result.final_url = resp.url
            if encoding:
                result.text = resp.content.decode(encoding, errors="replace")
            else:
                result.text = resp.text
            result.elapsed = round(time.time() - started, 3)
            if resp.status_code in RETRY_STATUS and attempt < retries:
                result.error = f"HTTP {resp.status_code}"
                sleep(2 ** attempt)
                continue
            result.ok = resp.status_code < 400
            if not result.ok:
                result.error = f"HTTP {resp.status_code}"
            return result
        except (requests.RequestException, ConnectionError) as e:
            result.error = f"{type(e).__name__}: {e}"
            result.elapsed = round(time.time() - started, 3)
            if attempt < retries:
                sleep(2 ** attempt)
                continue
            return result
    return result
