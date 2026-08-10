# -*- coding: utf-8 -*-
"""主管道：采集 -> 分析 -> 落地日档案 -> 生成聚合报告 -> 同步到 dist/data。"""
import os, sys, json, shutil, datetime as dt

from common import (DAILY_DIR, DIST_DATA, DIST_FUNDS, log, today_str, read_json, write_json)
import fetch_news, fetch_funds, analyze as ana
import aggregate
import fetch_quote


def build_day(date_str, session='auto', with_funds=None):
    """with_funds=None 时自动判定：仅当天才采集持仓。

    养基宝接口只返回「当前」持仓快照，把它贴到历史日期会让市值变化失真，
    因此历史回补只补新闻，基金部分标记为未采集。
    """
    if with_funds is None:
        with_funds = (date_str == today_str())
    log(f'=== 采集 {date_str} ({session}{"" if with_funds else " · 仅新闻"}) ===')
    news_pack = fetch_news.collect(date_str)
    if with_funds:
        fund_pack = fetch_funds.collect(date_str)
    else:
        fund_pack = {'date': date_str, 'ok': False, 'reason': 'HISTORICAL_NO_SNAPSHOT',
                     'holdings': [], 'index': [], 'summary': {}}

    log('=== 分析 ===')
    result = ana.analyze(news_pack, fund_pack)

    # 基金行情详情（K线/估值/重仓）独立成档，供前端弹层按需读取
    if fund_pack.get('ok'):
        hs = [h for h in fund_pack.get('holdings', []) if h.get('code') and h.get('money', 0) >= 50]
        try:
            fetch_quote.collect_all(hs, DIST_FUNDS)
        except Exception as e:
            log(f'  基金行情详情生成失败（不影响主流程）: {e}')

    doc = {
        'date': date_str,
        'generated_at': dt.datetime.now().isoformat(timespec='seconds'),
        'session': session,
        'digest_title': news_pack.get('digest_title', ''),
        'funds': {
            'ok': fund_pack.get('ok'),
            'reason': fund_pack.get('reason', ''),
            'summary': fund_pack.get('summary', {}),
            'holdings': fund_pack.get('holdings', []),
            'index': fund_pack.get('index', []),
        },
        'analysis': result,
        # 原文单独存，避免看板首屏过大
        'news_raw': news_pack.get('news', []),
        'xwlb_raw': news_pack.get('xwlb', []),
    }
    path = os.path.join(DAILY_DIR, f'{date_str}.json')
    write_json(path, doc)
    log(f'日档案已写入 {path}')
    return doc


def build_dist(latest_date):
    """生成前端所需的数据文件。"""
    dates = sorted(f[:-5] for f in os.listdir(DAILY_DIR) if f.endswith('.json'))
    index = []
    for d in dates:
        doc = read_json(os.path.join(DAILY_DIR, f'{d}.json'), {})
        a = doc.get('analysis', {}) or {}
        fs = (doc.get('funds', {}) or {}).get('summary', {}) or {}
        index.append({
            'date': d,
            'title': doc.get('digest_title', ''),
            'mood': a.get('market_mood', 0),
            'mood_level': a.get('market_mood_level', '中性'),
            'news_total': (a.get('stats', {}) or {}).get('news_total', 0),
            'xwlb_total': (a.get('stats', {}) or {}).get('xwlb_total', 0),
            'total_money': fs.get('total_money', 0),
            'total_earn': fs.get('total_earn', 0),
            'today_income': fs.get('today_income', 0),
            'today_income_rate': fs.get('today_income_rate', 0),
            'generated_at': doc.get('generated_at', ''),
        })
    index.sort(key=lambda x: x['date'], reverse=True)
    write_json(os.path.join(DIST_DATA, 'index.json'),
               {'dates': index, 'latest': latest_date,
                'updated_at': dt.datetime.now().isoformat(timespec='seconds')})

    # 逐日文件复制到 dist
    os.makedirs(os.path.join(DIST_DATA, 'daily'), exist_ok=True)
    for d in dates:
        src = os.path.join(DAILY_DIR, f'{d}.json')
        dst = os.path.join(DIST_DATA, 'daily', f'{d}.json')
        if (not os.path.exists(dst)) or os.path.getmtime(src) > os.path.getmtime(dst):
            shutil.copy2(src, dst)
    log(f'dist 数据同步完成：{len(dates)} 天')
    return dates


def main():
    args = sys.argv[1:]
    session = 'auto'
    date_str = today_str()
    for a in args:
        if a.startswith('--session='):
            session = a.split('=', 1)[1]
        elif a.startswith('--date='):
            date_str = a.split('=', 1)[1]
        elif a == '--backfill':
            # 回补最近 7 天新闻（基金只有当日快照，历史不回补）
            for i in range(7, 0, -1):
                d = (dt.date.today() - dt.timedelta(days=i)).isoformat()
                p = os.path.join(DAILY_DIR, f'{d}.json')
                if os.path.exists(p):
                    continue
                try:
                    build_day(d, session='backfill')
                except Exception as e:
                    log(f'回补 {d} 失败: {e}')

    # 昨日一并刷新：早间时段当日新闻尚未铺开，且昨日晚间可能有增量
    y = (dt.date.fromisoformat(date_str) - dt.timedelta(days=1)).isoformat()
    try:
        build_day(y, session=session)
    except Exception as e:
        log(f'刷新昨日 {y} 失败（忽略）: {e}')

    doc = build_day(date_str, session=session)
    aggregate.build_all()
    build_dist(date_str)

    # 结果摘要，便于自动化任务回报
    a = doc.get('analysis', {}) or {}
    f = doc.get('funds', {}) or {}
    st = a.get('stats', {}) or {}
    log('=== 全部完成 ===')
    print('---SUMMARY---')
    print(json.dumps({
        'date': date_str, 'session': session,
        'news': st.get('news_total', 0), 'xwlb': st.get('xwlb_total', 0),
        'mood': a.get('market_mood'), 'mood_level': a.get('market_mood_level'),
        'fund_ok': f.get('ok'), 'fund_reason': f.get('reason', ''),
        'total_money': (f.get('summary') or {}).get('total_money'),
        'today_income': (f.get('summary') or {}).get('today_income'),
        'top_actions': [{'name': x['name'], 'action': x['action'], 'score': x['total_score']}
                        for x in (a.get('advices') or [])[:3]],
    }, ensure_ascii=False))


if __name__ == '__main__':
    main()
