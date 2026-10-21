# -*- coding: utf-8 -*-
"""深挖：生意社8个品类页的地区/规格分布 + 长江有色6张表的板块归属 + 东财合约月解析"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, r'E:\矿_news')
sys.stdout.reconfigure(encoding='utf-8')

import requests
import yaml
from bs4 import BeautifulSoup

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
OUT = Path(r'C:\Users\Lenovo\AppData\Local\Temp\opencode')


def sess_get(url, referer='', enc=None, headers=None):
    h = {'User-Agent': UA}
    if referer:
        h['Referer'] = referer
    h.update(headers or {})
    r = requests.get(url, headers=h, timeout=25)
    return r.content.decode(enc, errors='replace') if enc else r.text


# ---------- 1. 生意社 8 个品类页 ----------
cfg = yaml.safe_load(Path(r'E:\矿_news\config\sources\pp100.yaml').read_text(encoding='utf-8'))
print('########## 生意社 8 个品类页 ##########')
rows_all = []
for url in cfg['urls']:
    html = sess_get(url, referer='https://www.100ppi.com/mprice/')
    soup = BeautifulSoup(html, 'lxml')
    tbl = soup.select('table')[0] if soup.select('table') else None
    if not tbl:
        print(f'{url}  -> 无表格')
        continue
    trs = tbl.select('tr')
    rows = []
    for tr in trs:
        cells = [c.get_text(' ', strip=True) for c in tr.select('td')]
        if len(cells) >= 6:
            rows.append(cells)
    names = {}
    for c in rows:
        names.setdefault(c[0], []).append(c)
    print(f'\n{url}')
    print(f'   报价行数={len(rows)}  品种数={len(names)}')
    for nm, lst in list(names.items())[:6]:
        regions = sorted({r[5] for r in lst})
        specs = sorted({r[1] for r in lst})
        pt = sorted({r[4] for r in lst})
        print(f'   - {nm}: {len(lst)}行 地区={regions[:8]} 规格={specs[:5]} 价格类型={pt}')
        rows_all.extend(lst)

Path(OUT / 'pp100_rows.json').write_text(json.dumps(rows_all, ensure_ascii=False, indent=1), encoding='utf-8')
print(f'\n生意社总行数={len(rows_all)} 全部地区取值={sorted({r[5] for r in rows_all})}')

# ---------- 2. 长江有色 6 张表 ----------
print('\n\n########## 长江有色 6 张表 ##########')
html = sess_get('https://www.ccmn.cn/priceinfo/')
soup = BeautifulSoup(html, 'lxml')
for ti, tbl in enumerate(soup.select('table')):
    trs = tbl.select('tr')
    # 找表前最近的标题文字
    title = ''
    node = tbl
    for _ in range(6):
        node = node.find_previous(string=True)
        if node and node.strip():
            title = node.strip()
            break
    print(f'\n[table{ti}] 标题≈"{title[:40]}" 行数={len(trs)}')
    for tr in trs[1:6]:
        cells = [c.get_text(' ', strip=True) for c in tr.select('td')]
        if cells:
            print('    ', cells)

# ---------- 3. 东财 合约名 ----------
print('\n\n########## 东方财富期货：合约名与合约月 ##########')
ej = json.loads(sess_get(cfg and 'http://62.234.24.246/x' if False else
                         'https://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=300&po=1&np=1&fltt=2&invt=2&fid=f3&fs=m:113&fields=f2,f3,f4,f12,f14'))
diff = ((ej.get('data') or {}).get('diff')) or []
print('总条目=', len(diff), ' total字段=', (ej.get('data') or {}).get('total'))
tgt = ['铜', '铝', '锌', '铅', '锡', '铁矿', '焦煤', '焦炭', '锰硅', '硅铁', '黄金', '白银']
for t in tgt:
    hits = [d for d in diff if t in str(d.get('f14'))]
    if hits:
        print(f'  {t}: {len(hits)}个合约 -> ', [(d['f14'], d['f12'], d['f2']) for d in hits[:4]])
