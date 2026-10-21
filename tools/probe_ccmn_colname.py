# -*- coding: utf-8 -*-
"""探测长江有色 mall.ccmn.cn 报价接口能否按 colName 取多个金属的【地区价】"""
import json
import sys

sys.stdout.reconfigure(encoding='utf-8')

import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
S = requests.Session()
S.headers.update({'User-Agent': UA, 'X-Requested-With': 'XMLHttpRequest',
                  'Referer': 'https://www.ccmn.cn/priceinfo/sn'})

URL = 'https://mall.ccmn.cn/shop/quotaData/getQuotaData'
codes = ['sn', 'cu', 'al', 'zn', 'pb', 'ni', 'si', 'mg', 'mo', 'w', 'sb', 'hg',
         'ag', 'au', 'pt', 'pd', 'ss', 'fe', 'coal', 'coke', 'mns', 'lithium',
         'lith', 're', 'nio', 'indium', 'germanium', 'selenium', 'tellurium',
         'chrome', 'molybdenum', 'tungsten', 'antimony', 'manganese', 'ferro',
         'ferrosilicon', 'fmn', 'femo', 'ti', 'zr', 'v', 'cr', 'mn', 'k']

ok = []
for c in codes:
    try:
        r = S.post(URL, data={'colName': c, 'pageNo': 1, 'pageSize': 50}, timeout=20)
        js = r.json()
        items = ((js.get('body') or {}).get('quotaVoList')) or []
        if items:
            ok.append((c, items))
            names = sorted({i.get('productSortName') for i in items})
            mkts = sorted({i.get('marketName') for i in items})
            places = sorted({i.get('placeOrTrademark') for i in items})
            print(f'[OK] colName={c:10} 条数={len(items):3} 品种={names[:4]}')
            print(f'        marketName={mkts}')
            print(f'        placeOrTrademark={places}')
            s = items[0]
            print(f'        样例: {json.dumps(s, ensure_ascii=False)[:300]}')
        else:
            print(f'[--] colName={c:10} 空 (body={json.dumps(js.get("body"), ensure_ascii=False)[:80]})')
    except Exception as e:
        print(f'[ERR] colName={c:10} {type(e).__name__}: {e}')

print('\n\n===== 命中汇总 =====')
for c, items in ok:
    mkts = sorted({i.get('marketName') for i in items if i.get('marketName')})
    print(f'{c:10} 条数={len(items):3} 地区/市场数={len(mkts):2} {mkts}')
