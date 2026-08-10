# -*- coding: utf-8 -*-
"""基金采集：养基宝个人持仓 + 公网净值/估值/板块/重仓信息 + 指数行情。"""
import requests, json
from common import (YJB_PLUG, YJB_APP, UA, log, safe_float,
                    load_yjb_token, yjb_headers)


class TokenExpired(Exception):
    pass


def plug_get(path, token):
    r = requests.get(YJB_PLUG + path, headers=yjb_headers(path, token), timeout=20)
    if r.status_code in (401, 403):
        raise TokenExpired('养基宝 Token 已失效')
    r.raise_for_status()
    d = r.json()
    if d.get('code') != 200:
        if d.get('code') in (401, 403, 1000):
            raise TokenExpired('养基宝 Token 已失效')
        raise Exception(d.get('message', 'API error'))
    return d.get('data', {})


def fetch_market_batch(fund_ids):
    """公网批量净值/估值/板块。无需登录。"""
    if not fund_ids:
        return {}
    try:
        body = {'funds': [{'fund_id': int(i), 'data_source': '1'} for i in fund_ids]}
        r = requests.post(f'{YJB_APP}/market/v1/fund/batch', json=body,
                          headers={'User-Agent': 'YJB/2.0.4',
                                   'Content-Type': 'application/json'}, timeout=25)
        d = r.json()
        items = d.get('data') or d.get('list') or []
        if isinstance(items, dict):
            items = items.get('list') or list(items.values())
        out = {}
        for it in items:
            if not isinstance(it, dict):
                continue
            fid = str(it.get('fund_id') or it.get('id') or '')
            nv = it.get('nv_info') or {}
            sector = it.get('sector_info') or {}
            out[fid] = {
                'nav': safe_float(nv.get('dwjz')),
                'day_pct': safe_float(nv.get('rzzl')),
                'nav_date': nv.get('jzrq', ''),
                'est_pct': safe_float(nv.get('vgszzl')),
                'est_date': nv.get('true_valuation_date', ''),
                'year_pct': safe_float(it.get('year_increase_rate')),
                'sector': sector.get('name', '') if isinstance(sector, dict) else '',
                'sector_pct': safe_float(sector.get('ratio')) if isinstance(sector, dict) else 0,
                'category': it.get('category', ''),
                'market_type': it.get('market_type', ''),
            }
        log(f'  公网行情: {len(out)} 只匹配')
        return out
    except Exception as e:
        log(f'  公网行情失败（降级）: {e}')
        return {}


def collect(date_str):
    token = load_yjb_token()
    result = {'date': date_str, 'ok': False, 'reason': '', 'holdings': [],
              'index': [], 'summary': {}}
    if not token:
        result['reason'] = 'NO_TOKEN'
        log('  养基宝未登录，跳过基金采集')
        return result

    try:
        # 账户汇总
        try:
            coll = plug_get('/account_collect', token)
            accs = coll.get('account_data', []) or []
            if accs:
                a = accs[0]
                result['summary'] = {
                    'hold_cost': safe_float(a.get('hold_cost')),
                    'today_income': safe_float(a.get('today_income')),
                    'today_income_rate': safe_float(a.get('today_income_rate')),
                }
        except TokenExpired:
            raise
        except Exception as e:
            log(f'  账户汇总跳过: {e}')

        # 指数行情
        try:
            idx = plug_get('/index_data', token)
            items = idx if isinstance(idx, list) else idx.get('list', [])
            result['index'] = [{
                'name': i.get('name') or i.get('show_name', ''),
                'value': safe_float(i.get('v') or i.get('price')),
                'pct': safe_float(i.get('dir') or i.get('change')),
            } for i in (items or [])[:12]]
        except Exception as e:
            log(f'  指数跳过: {e}')

        # 持仓
        accounts = plug_get('/user_account', token).get('list', []) or []
        holdings = []
        for acc in accounts:
            data = plug_get(f"/fund_hold?account_id={acc['id']}", token)
            items = data if isinstance(data, list) else data.get('list', [])
            for it in (items or []):
                money = safe_float(it.get('money') or it.get('market_value'))
                earn = safe_float(it.get('earn') or it.get('hold_earn'))
                base = money - earn
                holdings.append({
                    'account': acc.get('title', ''),
                    'fund_id': str(it.get('fund_id') or ''),
                    'code': it.get('code', ''),
                    'name': it.get('name') or it.get('short_name') or '',
                    'money': round(money, 2),
                    'earn': round(earn, 2),
                    'earn_pct': round(earn / base * 100, 2) if base > 0 else 0.0,
                    'share': safe_float(it.get('share') or it.get('hold_share')),
                    'cost': safe_float(it.get('cost') or it.get('hold_cost')),
                    'category': it.get('category', ''),
                })

        # 合并公网行情
        mk = fetch_market_batch([h['fund_id'] for h in holdings if h['fund_id']])
        for h in holdings:
            h.update(mk.get(h['fund_id'], {}))

        total = sum(h['money'] for h in holdings)
        for h in holdings:
            h['weight'] = round(h['money'] / total * 100, 2) if total > 0 else 0.0
        holdings.sort(key=lambda x: -x['money'])

        result['holdings'] = holdings
        result['summary'].update({
            'total_money': round(total, 2),
            'total_earn': round(sum(h['earn'] for h in holdings), 2),
            'count': len(holdings),
        })
        te = result['summary']['total_earn']
        base = total - te
        result['summary']['total_earn_pct'] = round(te / base * 100, 2) if base > 0 else 0.0
        result['ok'] = True
        log(f"  持仓 {len(holdings)} 只，合计 {total:.2f}")
    except TokenExpired as e:
        result['reason'] = 'TOKEN_EXPIRED'
        log(f'  {e} —— 需重新扫码登录')
    except Exception as e:
        result['reason'] = f'ERROR: {e}'
        log(f'  基金采集失败: {e}')
    return result


if __name__ == '__main__':
    import sys
    from common import today_str
    d = sys.argv[1] if len(sys.argv) > 1 else today_str()
    r = collect(d)
    print(json.dumps(r['summary'], ensure_ascii=False))
    for h in r['holdings']:
        print(f"{h['name'][:22]:24} {h['code']} w={h['weight']}% day={h.get('day_pct')} "
              f"sector={h.get('sector')} year={h.get('year_pct')}")
