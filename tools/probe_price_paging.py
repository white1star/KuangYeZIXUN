# -*- coding: utf-8 -*-
"""收尾：生意社分页 / 东财合约月 / 长江升贴水表 / cctd 全部规格与口径"""
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

# 1) 生意社分页
print('########## 生意社分页 ##########')
for cat in [300, 318, 870, 712]:
    for p in [1, 2, 3]:
        h = S.get(f'https://www.100ppi.com/mprice/plist-1-{cat}-{p}.html',
                  headers={'Referer': 'https://www.100ppi.com/mprice/'}, timeout=25).text
        s = BeautifulSoup(h, 'lxml')
        ts = s.select('table')
        rows = []
        if ts:
            for tr in ts[0].select('tr'):
                cs = [c.get_text(' ', strip=True) for c in tr.select('td')]
                if len(cs) >= 6:
                    rows.append(cs)
        regs = sorted({r[5] for r in rows})
        print(f'  品类{cat} 第{p}页: {len(rows)}行 地区={regs}')
        if not rows:
            break

# 2) 东财期货 合约月
print('\n########## 东方财富期货 合约月 ##########')
try:
    j = S.get('https://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=200&po=1&np=1&fltt=2&invt=2&fid=f3&fs=m:113&fields=f2,f3,f4,f12,f14',
              headers={'Referer': 'https://quote.eastmoney.com/'}, timeout=25).json()
    diff = j['data']['diff']
    print('total=', j['data']['total'], '本页=', len(diff))
    for t in ['铜', '铝', '锌', '铅', '锡', '铁矿', '焦煤', '焦炭', '锰硅', '硅铁', '黄金', '白银']:
        hits = [d for d in diff if t in str(d.get('f14'))]
        if hits:
            print(f'  {t}: {len(hits)}个 -> {[(d["f14"], d["f12"]) for d in hits[:5]]}')
except Exception as e:
    print('  失败:', e)

# 3) 长江有色 升贴水表
print('\n########## 长江有色 升贴水表（地区价差最直接的一手） ##########')
h = S.get('https://www.ccmn.cn/priceinfo/', timeout=25).text
soup = BeautifulSoup(h, 'lxml')
tbls = soup.select('table')
for tr in tbls[2].select('tr'):
    cs = [c.get_text(' ', strip=True) for c in tr.select('td')]
    if cs:
        print('   ', cs)

# 4) cctd 全部煤价口径
print('\n########## cctd 全部煤价（名称/价/涨跌/日期） ##########')
h = S.get('https://www.cctd.com.cn/', timeout=25).content.decode('gb18030', 'replace')
flat = re.sub(r'\s+', ' ', BeautifulSoup(h, 'lxml').get_text(' ', strip=True))
pat = re.compile(r'(秦皇岛\s*动力煤|(?:综合交易|年度长协)(?:5500|5000|4500))\s*(\d{3,4})[^率]*?变化：\s*(-?\d+)\s*(-?[\d.]+)%\s*日期：\s*([\d\-]+)')
for m in pat.finditer(flat):
    print(f'   名称={m.group(1):18} 价={m.group(2):>5} 涨跌={m.group(3):>4} 涨跌幅={m.group(4):>6}% 报价日={m.group(5)}')
