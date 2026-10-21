# -*- coding: utf-8 -*-
"""矿价数据源口径调研探针：逐源实抓原始载荷，dump 结构与可得字段。"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, r'E:\矿_news')
sys.stdout.reconfigure(encoding='utf-8')

import yaml
import requests
from bs4 import BeautifulSoup

from crawler.fetch import fetch

SRC = Path(r'E:\矿_news\config\sources')
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


def get(cfg):
    urls = cfg.get('urls') or [cfg['url']]
    url = urls[0]
    headers = {'User-Agent': UA}
    if cfg.get('referer'):
        headers['Referer'] = cfg['referer']
    headers.update(cfg.get('headers') or {})
    sess = requests.Session()
    try:
        if (cfg.get('method') or 'GET').upper() == 'POST':
            r = sess.post(url, headers=headers, data=cfg.get('post_data'), timeout=25)
        else:
            r = sess.get(url, headers=headers, timeout=25)
        enc = cfg.get('encoding')
        text = r.content.decode(enc, errors='replace') if enc else r.text
        return r.status_code, text
    except Exception as e:
        return 0, f'__ERROR__ {type(e).__name__}: {e}'


def probe_table(cfg, text):
    t = cfg['table']
    soup = BeautifulSoup(text, 'lxml')
    tbls = soup.select('table')
    print(f'  table 数量={len(tbls)}')
    for ti, tbl in enumerate(tbls[:2]):
        rows = tbl.select(t.get('row', 'tr'))
        print(f'  [table{ti}] 行数={len(rows)}')
        for ri, tr in enumerate(rows[:4]):
            cells = [c.get_text(' ', strip=True) for c in tr.select(t.get('cell', 'td'))]
            print(f'    row{ri}: {cells}')


def probe_regex(cfg, text):
    pat = cfg['regex']['pattern']
    flat = re.sub(r'\s+', ' ', BeautifulSoup(text, 'lxml').get_text(' ', strip=True))
    ms = list(re.finditer(pat, flat))
    print(f'  正则命中 {len(ms)} 处；样例上下文：')
    for m in ms[:6]:
        s = max(0, m.start() - 60)
        e = min(len(flat), m.end() + 60)
        print(f'    …{flat[s:e]}…')


def probe_ccmn(cfg, text):
    try:
        data = json.loads(text)
    except Exception as e:
        print('  非JSON:', e, text[:200])
        return
    items = ((data.get('body') or {}).get(cfg.get('items', 'quotaVoList'))) or []
    print(f'  body 顶层键={list((data.get("body") or {}).keys())}  条目={len(items)}')
    if items:
        print(f'  条目字段={list(items[0].keys())}')
        for it in items[:8]:
            print('   ', json.dumps(it, ensure_ascii=False)[:260])


def probe_json_list(cfg, text):
    data = json.loads(text)
    diff = ((data.get('data') or {}).get('diff')) or []
    print(f'  diff 条目={len(diff)}')
    if diff:
        print(f'  条目字段={list(diff[0].keys())}')
        for it in diff[:4]:
            print('   ', json.dumps(it, ensure_ascii=False)[:200])


def probe_sina(cfg, text):
    ms = re.findall(r'var\s+hq_str_nf_([A-Za-z0-9]+)="([^"]*)"', text)
    print(f'  合约数={len(ms)}')
    for code, payload in ms[:3]:
        parts = payload.split(',')
        print(f'    {code}: 字段数={len(parts)}')
        print('      ', parts)
    print('  字段名参考: 新浪 nf_ = 名称,?,时间,开盘,最高,最低,昨收,买价,卖价,最新价,?,结算价,昨结算,...')


def probe_shfe(cfg, text):
    try:
        data = json.loads(text)
    except Exception as e:
        print('  非JSON:', e, text[:200])
        return
    rows = data.get('o_curinstrument') or data.get('o_curinstrumentList') or []
    print(f'  合约条数={len(rows)}')
    if rows:
        print(f'  字段={list(rows[0].keys())}')
        print('   ', json.dumps(rows[0], ensure_ascii=False)[:400])


PROBES = {'table': probe_table, 'regex': probe_regex, 'ccmn_quota': probe_ccmn,
          'eastmoney_futures': probe_json_list, 'sina_futures': probe_sina,
          'shfe_daily': probe_shfe}

targets = sys.argv[1:] or ['ccmn', 'ccmn_sn', 'cctd', 'mysteel', 'pp100', 'sxcoal',
                            'sina_futures', 'eastmoney_futures', 'shfe']
for key in targets:
    f = SRC / f'{key}.yaml'
    if not f.exists():
        print(f'== {key}: 配置文件不存在')
        continue
    cfg = yaml.safe_load(f.read_text(encoding='utf-8'))
    print('=' * 90)
    print(f'== {key}  name={cfg.get("name")}  parser={cfg.get("parser")}  '
          f'price_type={cfg.get("price_type")}  unit={cfg.get("unit")}  enabled={cfg.get("enabled", True)}')
    print(f'   url={(cfg.get("urls") or [cfg.get("url")])[0]}')
    status, text = get(cfg)
    print(f'   HTTP={status} 长度={len(text)}')
    if status == 0 or text.startswith('__ERROR__'):
        print('  ', text[:200])
        continue
    print(f'   载荷开头: {text[:160]!r}')
    probe = PROBES.get(cfg.get('parser'))
    if probe:
        try:
            probe(cfg, text)
        except Exception as e:
            print('  probe 出错:', type(e).__name__, e)
    print()
