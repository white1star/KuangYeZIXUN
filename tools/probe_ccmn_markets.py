# -*- coding: utf-8 -*-
"""1) 从 ccmn 价格频道页发现全部 colName  2) 测分页  3) 导出铜的21市场当日区域价差"""
import json
import re
import sys

sys.stdout.reconfigure(encoding='utf-8')

import requests
from bs4 import BeautifulSoup

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
S = requests.Session()
S.headers.update({'User-Agent': UA, 'X-Requested-With': 'XMLHttpRequest'})
URL = 'https://mall.ccmn.cn/shop/quotaData/getQuotaData'

# ---------- 1) 发现 colName ----------
print('########## 1. ccmn 价格频道页里的品类页 ##########')
html = S.get('https://www.ccmn.cn/priceinfo/', timeout=25).text
soup = BeautifulSoup(html, 'lxml')
codes = []
for a in soup.select('a[href*="priceinfo/"]'):
    m = re.search(r'priceinfo/([a-z0-9\-_]+)', a.get('href', ''))
    if m and m.group(1) not in codes:
        codes.append(m.group(1))
print('页面中的品类:', codes)

# 反查哪些 colName 接口有数据
live = []
for c in codes:
    try:
        r = S.post(URL, data={'colName': c, 'pageNo': 1, 'pageSize': 100}, timeout=20)
        js = r.json()
        items = ((js.get('body') or {}).get('quotaVoList')) or []
        if items:
            live.append(c)
            print(f'  [有数据] {c:12} 条数={len(items):3} 品种={sorted({i["productSortName"] for i in items})[:3]}')
        else:
            print(f'  [空]     {c:12}')
    except Exception as e:
        print(f'  [ERR]    {c:12} {e}')

# ---------- 2) 分页 ----------
print('\n########## 2. 分页测试 (sn / cu) ##########')
for c in ['sn', 'cu']:
    for pno, psize in [(1, 100), (2, 100), (1, 20), (2, 20)]:
        r = S.post(URL, data={'colName': c, 'pageNo': pno, 'pageSize': psize}, timeout=20)
        js = r.json()
        items = ((js.get('body') or {}).get('quotaVoList')) or []
        mk = [i.get('marketName') for i in items]
        print(f'  {c} pageNo={pno} pageSize={psize} -> {len(items)}条  markets={mk[:6]}{"..." if len(mk)>6 else ""}')

# ---------- 3) 铜的当日区域价差 ----------
print('\n########## 3. 铜 1# 各市场当日价 ##########')
r = S.post(URL, data={'colName': 'cu', 'pageNo': 1, 'pageSize': 100}, timeout=20)
items = r.json()['body']['quotaVoList']
rows = []
for i in items:
    rows.append((i['marketName'], i['placeOrTrademark'], i['productSortName'],
                 i['avgPrice'], i['minPrice'], i['maxPrice'], i['unit'], i['publishDateTime']))
for x in sorted(rows, key=lambda t: -t[3]):
    print(f'  {x[0]:10} 产地/牌号={x[1]:8} {x[2]:10} 均价={x[3]:>10} ({x[4]}~{x[5]}) {x[6]} {x[7]}')
vals = [x[3] for x in rows]
print(f'\n  最高={max(vals)} 最低={min(vals)} 价差={max(vals)-min(vals)} 元/吨 ({(max(vals)-min(vals))/min(vals)*100:.2f}%)')
