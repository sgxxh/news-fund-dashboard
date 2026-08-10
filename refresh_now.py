# -*- coding: utf-8 -*-
"""一键刷新脚本：从养基宝重新拉取持仓 + 生成基金行情详情，并重建 dist 数据。

用法（需 venv python）：
  python refresh_now.py            # 刷新今天
  python refresh_now.py 2026-08-10 # 指定日期

本脚本与 server.py 的 /api/refresh/funds 逻辑一致，便于定时任务 / 手动触发。
养基宝登录态在 ~/.yjb_token.json，仅本机可用。
"""
import os, sys, json

HERE = os.path.dirname(os.path.abspath(__file__))
PIPE = os.path.join(HERE, 'pipeline')
if PIPE not in sys.path:
    sys.path.insert(0, PIPE)

import common, fetch_funds, fetch_quote, run_daily


def refresh(date_str=None):
    date_str = date_str or common.today_str()
    token = common.load_yjb_token()
    if not token:
        print('NO_TOKEN: 养基宝未登录，无法刷新。请先在电脑端扫码登录。')
        return False
    print(f'[{date_str}] 调用养基宝拉取持仓…')
    fp = fetch_funds.collect(date_str)
    if not fp.get('ok'):
        print('FAIL:', fp.get('reason', '未知'))
        return False
    hs = [h for h in fp.get('holdings', []) if h.get('code') and h.get('money', 0) >= 50]
    print(f'  持仓 {len(hs)} 只，生成 K线/估值…')
    fetch_quote.collect_all(hs, common.DIST_FUNDS)
    path = os.path.join(common.DAILY_DIR, f'{date_str}.json')
    doc = common.read_json(path, {}) or {}
    doc['funds'] = {
        'ok': True, 'reason': '', 'summary': fp.get('summary', {}),
        'holdings': fp.get('holdings', []), 'index': fp.get('index', []),
    }
    common.write_json(path, doc)
    print('  重建 dist 数据…')
    run_daily.build_dist(date_str)
    print(f'OK 刷新完成：{len(hs)} 只基金，合计 ¥{(fp.get("summary") or {}).get("total_money")}')
    return True


if __name__ == '__main__':
    d = sys.argv[1] if len(sys.argv) > 1 else None
    ok = refresh(d)
    sys.exit(0 if ok else 1)
