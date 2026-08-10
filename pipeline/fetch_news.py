# -*- coding: utf-8 -*-
"""新闻采集：日知录每日要闻（含正文/影响分析） + 央视新闻联播条目。"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import re, json, requests
from concurrent.futures import ThreadPoolExecutor
from common import NEWS_API, UA, log, safe_float

CATEGORY = {1: '娱乐', 2: '时政', 3: '社会', 4: '财经', 5: '科技', 7: '体育'}
XWLB_COLUMN = 'TOPC1451528971114112'  # 央视新闻联播栏目 ID


def strip_html(s):
    if not s:
        return ''
    s = re.sub(r'<(script|style)[^>]*>.*?</\1>', '', s, flags=re.S | re.I)
    s = re.sub(r'<br\s*/?>|</p>', '\n', s, flags=re.I)
    s = re.sub(r'<[^>]+>', '', s)
    s = s.replace('&nbsp;', ' ').replace('&amp;', '&').replace('&quot;', '"')
    s = re.sub(r'\n{3,}', '\n\n', s)
    return s.strip()


def _get(url, **kw):
    kw.setdefault('timeout', 25)
    kw.setdefault('headers', {'User-Agent': UA})
    return requests.get(url, **kw)


def fetch_article(aid):
    """取单条新闻详情。"""
    try:
        r = _get(f'{NEWS_API}/articles/{aid}')
        d = (r.json() or {}).get('data') or {}
        c = d.get('content') or {}
        return {
            'id': aid,
            'story': strip_html(c.get('story', ''))[:6000],
            'impact': strip_html(c.get('impact', ''))[:2000],
            'publish_time': d.get('publish_time', ''),
            'category_name': d.get('category_name', ''),
        }
    except Exception as e:
        log(f'  详情失败 {aid}: {e}')
        return {'id': aid, 'story': '', 'impact': '', 'publish_time': '', 'category_name': ''}


def fetch_daily_news(date_str):
    """日知录当日新闻列表 + 并发拉详情。"""
    out = []
    try:
        r = _get(f'{NEWS_API}/daily', params={'date': date_str})
        data = (r.json() or {}).get('data') or {}
        arts = data.get('articles') or []
        log(f'  日知录 {date_str}: {len(arts)} 条')
        if not arts:
            return [], data.get('title', '')

        with ThreadPoolExecutor(max_workers=6) as ex:
            details = list(ex.map(fetch_article, [a['article_id'] for a in arts]))
        dmap = {d['id']: d for d in details}

        for a in arts:
            aid = a['article_id']
            d = dmap.get(aid, {})
            out.append({
                'id': aid,
                'title': strip_html(a.get('title', '')),
                'summary': strip_html(a.get('summary', '')),
                'heat': safe_float(a.get('heat')),
                'category': CATEGORY.get(a.get('category_id'), d.get('category_name') or '综合'),
                'story': d.get('story', ''),
                'impact': d.get('impact', ''),
                'publish_time': d.get('publish_time', ''),
                'cover': a.get('cover_image', ''),
                'source': '日知录',
            })
        out.sort(key=lambda x: -x['heat'])
        return out, data.get('title', '')
    except Exception as e:
        log(f'  日知录抓取失败: {e}')
        return [], ''


def parse_xwlb_brief(brief):
    """把新闻联播节目单 brief 拆成逐条标题。

    原文形如：本期节目主要内容：1.xxx；2.yyy；（1）zzz；（《新闻联播》 20260809 19:00）
    """
    if not brief:
        return []
    txt = brief.replace('\r', '\n')
    txt = re.sub(r'^本期节目主要内容[：:]\s*', '', txt.strip())
    txt = re.sub(r'（《新闻联播》[^）]*）\s*$', '', txt).strip()

    parts = re.split(r'[；;\n]+', txt)
    items = []
    for p in parts:
        p = p.strip().strip('。').strip()
        # 去掉前导编号：1. / （1） / 9： 等
        p = re.sub(r'^[（(]?\d{1,2}[）)]?\s*[.、：:]?\s*', '', p)
        p = p.strip('：:').strip()
        if len(p) >= 5 and not p.startswith('《新闻联播》'):
            items.append(p)
    return items


def fetch_xwlb(date_str):
    """央视新闻联播当日节目单，拆解为逐条要目。失败返回空列表，不阻断主流程。"""
    ymd = date_str.replace('-', '')
    items = []
    try:
        r = _get('https://api.cntv.cn/NewVideo/getVideoListByColumn',
                 params={'id': XWLB_COLUMN, 'n': 60, 'sort': 'desc',
                         'p': 1, 'mode': 0, 'serviceId': 'tvcctv'})
        txt = r.text.strip()
        if txt.startswith('('):
            txt = txt[1:-1]
        js = json.loads(txt)
        lst = (js.get('data') or {}).get('list') or []
        for it in lst:
            brief = strip_html(it.get('brief', '') or it.get('description', ''))
            # 日期匹配：优先用 brief 尾部标注，其次用 focus_date 毫秒时间戳
            m = re.search(r'《新闻联播》\s*(\d{8})', brief)
            hit = False
            if m:
                hit = (m.group(1) == ymd)
            else:
                fd = it.get('focus_date')
                if isinstance(fd, (int, float)) and fd > 0:
                    import datetime as _dt
                    ts = fd / 1000 if fd > 1e11 else fd
                    hit = _dt.datetime.fromtimestamp(ts).strftime('%Y%m%d') == ymd
                elif isinstance(fd, str):
                    hit = ymd in fd.replace('-', '')
            if not hit:
                continue
            for t in parse_xwlb_brief(brief):
                items.append({'id': f'xwlb-{len(items)}', 'title': t,
                              'source': '新闻联播', 'date': date_str})
            break
        log(f'  新闻联播 {date_str}: {len(items)} 条要目')
    except Exception as e:
        log(f'  新闻联播抓取失败（不影响主流程）: {e}')
    return items


def collect(date_str):
    news, title = fetch_daily_news(date_str)
    xwlb = fetch_xwlb(date_str)
    return {'date': date_str, 'digest_title': title, 'news': news, 'xwlb': xwlb}


if __name__ == '__main__':
    import sys
    from common import today_str
    d = sys.argv[1] if len(sys.argv) > 1 else today_str()
    res = collect(d)
    print(json.dumps({'date': d, 'news': len(res['news']), 'xwlb': len(res['xwlb'])},
                     ensure_ascii=False))
    if res['xwlb'][:2]:
        print(json.dumps(res['xwlb'][:2], ensure_ascii=False, indent=1))
