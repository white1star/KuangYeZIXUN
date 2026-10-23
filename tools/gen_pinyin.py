# -*- coding: utf-8 -*-
"""生成拼音首字母表（config/price_pinyin.json），构建时不依赖 pypinyin。

只收录实际会用到的字（品种名/别名/市场名 + 常用省份），表很小；
新增品种后重跑一次即可，缺字会退化成原字符（搜拼音搜不到，但不影响中文搜索）。
"""
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, r'E:\矿_news')

import yaml
from pypinyin import lazy_pinyin

ROOT = Path(r'E:\矿_news')


def chars_of(text):
    return [c for c in text if '\u4e00' <= c <= '\u9fff']


def main():
    texts = set()
    # 品种名与别名
    aliases = yaml.safe_load((ROOT / 'config' / 'price_aliases.yaml').read_text(encoding='utf-8')) or {}
    for name, items in aliases.items():
        texts.add(name)
        texts.update(str(x) for x in (items or []))
    # 配置里的品种名（页面级 commodity / covered_commodities）
    for f in (ROOT / 'config' / 'sources').glob('*.yaml'):
        cfg = yaml.safe_load(f.read_text(encoding='utf-8')) or {}
        for name in cfg.get('covered_commodities') or []:
            texts.add(str(name))
        for spec in cfg.get('urls') or []:
            if isinstance(spec, dict) and spec.get('commodity'):
                texts.add(str(spec['commodity']))
    # 常用省份 + 市场里的常见字
    texts.update(['河北', '山西', '内蒙古', '辽宁', '吉林', '黑龙江', '江苏', '浙江',
                  '安徽', '福建', '江西', '山东', '河南', '湖北', '湖南', '广东',
                  '广西', '海南', '四川', '贵州', '云南', '西藏', '陕西', '甘肃',
                  '青海', '宁夏', '新疆', '北京', '天津', '上海', '重庆',
                  '唐山', '港口', '矿区', '现货', '综合'])
    # 库里已有的市场名（保证拼音能搜到地区）
    db = ROOT / 'data' / 'news.db'
    if db.exists():
        import sqlite3
        conn = sqlite3.connect(str(db))
        try:
            for (market,) in conn.execute("SELECT DISTINCT market FROM prices WHERE market<>''"):
                texts.add(market)
            for (commodity,) in conn.execute("SELECT DISTINCT commodity FROM prices"):
                texts.add(commodity)
        finally:
            conn.close()

    chars = set()
    for t in texts:
        chars.update(chars_of(t))

    table = {}
    for c in sorted(chars):
        py = lazy_pinyin(c)[0]
        table[c] = py[0].lower() if py and py[0].isalpha() else ''

    out = ROOT / 'config' / 'price_pinyin.json'
    out.write_text(json.dumps(table, ensure_ascii=False, sort_keys=True, indent=0),
                   encoding='utf-8')
    print(f'写入 {out}：{len(table)} 个汉字')

    # 整词全拼（供 'ying shi' / 'yingshi' 命中）；运行时不依赖 pypinyin
    words = set()
    for t in texts:
        t = str(t).strip()
        if t:
            words.add(t)
    full = {}
    for w in sorted(words):
        py = ''.join(lazy_pinyin(w)).lower()
        if py and py != w.lower():
            full[w] = py
    full_out = ROOT / 'config' / 'price_pinyin_full.json'
    full_out.write_text(json.dumps(full, ensure_ascii=False, sort_keys=True, indent=0),
                        encoding='utf-8')
    print(f'写入 {full_out}：{len(full)} 个词')


if __name__ == '__main__':
    main()
