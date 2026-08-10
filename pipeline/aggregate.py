# -*- coding: utf-8 -*-
"""周期聚合：把日档案汇总为周报 / 月报 / 季报。"""
import os, sys, datetime as dt
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from collections import Counter, defaultdict

from common import DAILY_DIR, DIST_DATA, REPORT_DIR, read_json, write_json, log, safe_float


def period_keys(date_str):
    d = dt.date.fromisoformat(date_str)
    iso = d.isocalendar()
    q = (d.month - 1) // 3 + 1
    return {
        'week': f'{iso[0]}-W{iso[1]:02d}',
        'month': f'{d.year}-{d.month:02d}',
        'quarter': f'{d.year}-Q{q}',
    }


def load_all_days():
    out = []
    for f in sorted(os.listdir(DAILY_DIR)):
        if not f.endswith('.json'):
            continue
        doc = read_json(os.path.join(DAILY_DIR, f))
        if doc:
            out.append(doc)
    return out


def summarize(docs, key, label):
    """把一组日档案汇总成一份周期报告。"""
    if not docs:
        return None
    docs = sorted(docs, key=lambda d: d['date'])
    dates = [d['date'] for d in docs]

    # --- 情绪走势 ---
    mood_series = [{'date': d['date'],
                    'mood': (d.get('analysis', {}) or {}).get('market_mood', 0)}
                   for d in docs]
    moods = [m['mood'] for m in mood_series]
    avg_mood = round(sum(moods) / len(moods), 1) if moods else 0

    # --- 高频词累加 ---
    kw = Counter()
    for d in docs:
        for k in (d.get('analysis', {}) or {}).get('keywords', []):
            kw[k['word']] += k['count']
    kw_top = kw.most_common(50)
    mx = kw_top[0][1] if kw_top else 1
    keywords = [{'word': w, 'count': c, 'weight': round(c / mx, 3)} for w, c in kw_top]

    # --- 板块影响均值 ---
    sec_scores = defaultdict(list)
    sec_news = Counter()
    for d in docs:
        for sec, imp in ((d.get('analysis', {}) or {}).get('sector_impacts', {}) or {}).items():
            sec_scores[sec].append(imp.get('score', 0))
            sec_news[sec] += imp.get('news_count', 0)
    sectors = [{
        'sector': s,
        'avg_score': round(sum(v) / len(v), 1),
        'max_score': round(max(v), 1),
        'min_score': round(min(v), 1),
        'news_count': sec_news[s],
    } for s, v in sec_scores.items()]
    sectors.sort(key=lambda x: -x['avg_score'])

    # --- 持仓变化 ---
    fund_docs = [d for d in docs if (d.get('funds', {}) or {}).get('ok')]
    nav_series, holding_change = [], []
    if fund_docs:
        for d in fund_docs:
            s = (d['funds'].get('summary') or {})
            nav_series.append({
                'date': d['date'],
                'total': s.get('total_money', 0),
                'earn': s.get('total_earn', 0),
                'today_income': s.get('today_income', 0),
            })
        first, last = fund_docs[0]['funds'], fund_docs[-1]['funds']
        fmap = {h['code']: h for h in (first.get('holdings') or [])}
        for h in (last.get('holdings') or []):
            f0 = fmap.get(h['code'])
            holding_change.append({
                'code': h['code'], 'name': h['name'], 'sector': h.get('sector', ''),
                'money': h.get('money', 0), 'weight': h.get('weight', 0),
                'earn_pct': h.get('earn_pct', 0),
                'money_delta': round(h.get('money', 0) - (f0.get('money', 0) if f0 else 0), 2),
                'earn_pct_delta': round(h.get('earn_pct', 0) - (f0.get('earn_pct', 0) if f0 else 0), 2),
            })
        holding_change.sort(key=lambda x: -x['money'])

    # --- 建议一致性 ---
    act_cnt = defaultdict(Counter)
    for d in docs:
        for a in (d.get('analysis', {}) or {}).get('advices', []):
            act_cnt[a['name']][a['action']] += 1
    advice_consistency = []
    for name, c in act_cnt.items():
        top, n = c.most_common(1)[0]
        advice_consistency.append({
            'name': name, 'dominant': top, 'days': n, 'total_days': sum(c.values()),
            'ratio': round(n / sum(c.values()) * 100),
            'detail': dict(c),
        })
    advice_consistency.sort(key=lambda x: -x['days'])

    # --- 高热度事件 ---
    events = []
    for d in docs:
        for n in ((d.get('analysis', {}) or {}).get('top_news') or [])[:4]:
            events.append({'date': d['date'], 'title': n['title'],
                           'heat': n['heat'], 'sentiment': n['sentiment'],
                           'category': n.get('category', '')})
    events.sort(key=lambda x: -(x['heat'] + abs(x['sentiment']) * 3))

    total_news = sum((d.get('analysis', {}) or {}).get('stats', {}).get('news_total', 0) for d in docs)
    total_xwlb = sum((d.get('analysis', {}) or {}).get('stats', {}).get('xwlb_total', 0) for d in docs)

    return {
        'key': key, 'label': label, 'type': label,
        'date_from': dates[0], 'date_to': dates[-1], 'days': len(dates),
        'dates': dates,
        'avg_mood': avg_mood,
        'mood_series': mood_series,
        'keywords': keywords,
        'sectors': sectors,
        'nav_series': nav_series,
        'holding_change': holding_change,
        'advice_consistency': advice_consistency,
        'top_events': events[:20],
        'stats': {'news_total': total_news, 'xwlb_total': total_xwlb},
        'generated_at': dt.datetime.now().isoformat(timespec='seconds'),
    }


def build_all():
    docs = load_all_days()
    if not docs:
        log('无日档案，跳过聚合')
        return {}

    buckets = {'week': defaultdict(list), 'month': defaultdict(list), 'quarter': defaultdict(list)}
    for d in docs:
        pk = period_keys(d['date'])
        for t in buckets:
            buckets[t][pk[t]].append(d)

    label = {'week': '周报', 'month': '月报', 'quarter': '季报'}
    out = {'week': [], 'month': [], 'quarter': []}
    for t, groups in buckets.items():
        for key, ds in groups.items():
            rep = summarize(ds, key, label[t])
            if not rep:
                continue
            rep['type'] = t
            rep['type_label'] = label[t]
            write_json(os.path.join(REPORT_DIR, f'{t}-{key}.json'), rep)
            write_json(os.path.join(DIST_DATA, 'reports', f'{t}-{key}.json'), rep)
            out[t].append({'key': key, 'label': label[t],
                           'date_from': rep['date_from'], 'date_to': rep['date_to'],
                           'days': rep['days'], 'avg_mood': rep['avg_mood'],
                           'news_total': rep['stats']['news_total']})
    for t in out:
        out[t].sort(key=lambda x: x['key'], reverse=True)
    write_json(os.path.join(DIST_DATA, 'reports', 'index.json'), out)
    log(f"聚合完成：周报 {len(out['week'])} / 月报 {len(out['month'])} / 季报 {len(out['quarter'])}")
    return out


if __name__ == '__main__':
    build_all()
