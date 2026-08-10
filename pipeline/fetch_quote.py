# -*- coding: utf-8 -*-
"""基金行情详情采集：净值K线、阶段收益、风险指标、重仓股穿透估值(PE/PB)。

数据源：
  - 天天基金 pingzhongdata：净值全历史、同类排名、规模、资产配置、基金经理
  - 天天基金 F10 jjcc：前十大重仓股及占净值比例
  - 东方财富 push2：重仓个股实时行情与 PE(f9)/PB(f23)

基金本身没有市盈率，此处的 PE/PB 通过前十大重仓股按权重穿透计算得出，
采用调和加权（等价于组合总市值 / 组合总盈利），比算术平均更贴近真实估值。
"""
import os, sys, re, json, math, time, requests, datetime as dt
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from concurrent.futures import ThreadPoolExecutor

from common import UA, log, safe_float

PZ_URL = 'https://fund.eastmoney.com/pingzhongdata/{code}.js'
F10_URL = 'https://fundf10.eastmoney.com/FundArchivesDatas.aspx'
F10_JBGK = 'https://fundf10.eastmoney.com/jbgk_{code}.html'
PUSH2_UL = 'https://push2.eastmoney.com/api/qt/ulist.np/get'
PUSH2_CL = 'https://push2.eastmoney.com/api/qt/clist/get'

TRADE_DAYS = 244  # 年化换算用交易日数
RF = 0.02         # 无风险利率，用于夏普比率

_SESSION = requests.Session()
_SESSION.headers.update({'User-Agent': UA, 'Accept': '*/*',
                         'Accept-Language': 'zh-CN,zh;q=0.9',
                         'Connection': 'keep-alive'})


def _get(url, retries=3, **kw):
    """带重试的 GET。东财 push2 对密集请求会直接断连，需要退避重试。"""
    kw.setdefault('timeout', 25)
    last = None
    for i in range(retries):
        try:
            r = _SESSION.get(url, **kw)
            if r.status_code == 200:
                return r
            last = RuntimeError(f'HTTP {r.status_code}')
        except Exception as e:
            last = e
        time.sleep(0.6 * (i + 1))
    raise last


def _jsvar(text, name):
    """从 pingzhongdata 里抠出一个 JS 变量的原始字面量。"""
    m = re.search(re.escape(name) + r'\s*=\s*(.*?);\s*(?:/\*|var\s|\Z)', text, re.S)
    return m.group(1).strip() if m else None


def _jsjson(text, name, default=None):
    raw = _jsvar(text, name)
    if not raw:
        return default
    try:
        return json.loads(raw)
    except Exception:
        return default


# ---------------------------------------------------------------- 净值与档案

def fetch_pingzhong(code):
    """基金档案 + 净值全历史。"""
    r = _get(PZ_URL.format(code=code), headers={'Referer': 'https://fund.eastmoney.com/'})
    r.encoding = 'utf-8'
    t = r.text
    if len(t) < 500:
        raise RuntimeError('pingzhongdata 返回异常')

    nav = _jsjson(t, 'Data_netWorthTrend', []) or []
    acc = _jsjson(t, 'Data_ACWorthTrend', []) or []
    rank_pct = _jsjson(t, 'Data_rateInSimilarPersent', []) or []
    scale = _jsjson(t, 'Data_fluctuationScale', {}) or {}
    alloc = _jsjson(t, 'Data_assetAllocation', {}) or {}
    perf = _jsjson(t, 'Data_performanceEvaluation', {}) or {}
    mgr = _jsjson(t, 'Data_currentFundManager', []) or []
    codes_new = _jsjson(t, 'stockCodesNew', []) or []
    codes_old = _jsjson(t, 'stockCodes', []) or []

    name = (_jsvar(t, 'fS_name') or '""').strip('"')
    rate = (_jsvar(t, 'fund_Rate') or '""').strip('"')
    src_rate = (_jsvar(t, 'fund_sourceRate') or '""').strip('"')
    minsg = (_jsvar(t, 'fund_minsg') or '""').strip('"')

    # 净值序列 -> [{date, nav, pct}]
    series = []
    for it in nav:
        try:
            d = dt.datetime.fromtimestamp(it['x'] / 1000).strftime('%Y-%m-%d')
            series.append({'d': d, 'v': round(float(it['y']), 4),
                           'p': safe_float(it.get('equityReturn'))})
        except Exception:
            continue
    series.sort(key=lambda x: x['d'])

    # 累计净值
    acc_map = {}
    for it in acc:
        try:
            acc_map[dt.datetime.fromtimestamp(it[0] / 1000).strftime('%Y-%m-%d')] = round(float(it[1]), 4)
        except Exception:
            continue

    # 同类排名百分位（越小越靠前）
    rank_series = []
    for it in rank_pct:
        try:
            rank_series.append({'d': dt.datetime.fromtimestamp(it[0] / 1000).strftime('%Y-%m-%d'),
                                'v': round(float(it[1]), 2)})
        except Exception:
            continue

    # 重仓股 secid：优先 stockCodesNew（已是 market.code 格式）
    secids = []
    if codes_new:
        secids = [str(c) for c in codes_new if isinstance(c, str) and '.' in str(c)]
    if not secids and codes_old:
        for c in codes_old:
            c = str(c)
            if len(c) >= 7 and c[:6].isdigit():          # A股：6位代码 + 市场位(1沪/0深)
                secids.append(f'{"1" if c[6] == "1" else "0"}.{c[:6]}')
            elif re.match(r'^[A-Z]+\d{3}$', c):          # 美股：代码 + 市场号
                secids.append(f'{c[-3:]}.{c[:-3]}')
            elif len(c) >= 5 and c[:5].isdigit():        # 港股
                secids.append(f'116.{c[:5]}')

    return {
        'name': name, 'rate': rate, 'source_rate': src_rate, 'min_buy': minsg,
        'series': series, 'acc': acc_map, 'rank_series': rank_series,
        'scale': scale, 'alloc': alloc, 'perf': perf,
        'managers': [{'name': m.get('name'), 'star': m.get('star'),
                      'work': m.get('workTime'), 'scale': m.get('fundSize'),
                      'pic': m.get('pic')} for m in mgr[:3]],
        'secids': secids[:10],
    }


# ---------------------------------------------------------------- 重仓股与估值

def fetch_top_holdings(code):
    """F10 前十大重仓股（含占净值比例）。按表头定位「占净值比例」列，避免错取涨跌幅。"""
    out, season = [], ''
    try:
        r = _get(F10_URL, params={'type': 'jjcc', 'code': code, 'topline': 10,
                                  'year': '', 'month': '', 'rt': '0.1'},
                 headers={'Referer': f'https://fundf10.eastmoney.com/ccmx_{code}.html'})
        r.encoding = 'utf-8'
        t = r.text
        m = re.search(r'(\d{4}\s*年\s*\d\s*季度股票投资明细)', t)
        if m:
            season = re.sub(r'\s+', '', m.group(1))

        rows = re.findall(r'<tr>(.*?)</tr>', t, re.S)
        wcol = None
        for row in rows:
            cells = [re.sub(r'<[^>]+>', '', c).replace('&nbsp;', ' ').strip()
                     for c in re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', row, re.S)]
            if not cells:
                continue
            if wcol is None and '占净值比例' in cells:
                wcol = cells.index('占净值比例')
                continue
            if len(cells) < 3 or not re.match(r'^[A-Z0-9]{4,6}$', cells[1] if len(cells) > 1 else ''):
                continue
            if wcol is not None and len(cells) > wcol:
                w = safe_float(cells[wcol].rstrip('%'))
            else:
                w = safe_float(next((c for c in cells if c.endswith('%')), '0').rstrip('%'))
            out.append({'code': cells[1], 'name': cells[2], 'weight': w})
            if len(out) >= 10:
                break
    except Exception as e:
        log(f'    重仓股抓取失败 {code}: {e}')
    return out, season


# ---- ETF 联接基金：穿透到母 ETF ----------------------------------------

_ETF_CACHE = {'ts': 0, 'list': []}
_ETF_CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               '..', 'tmp', 'etf_list.json')
_ETF_TTL = 7 * 86400  # ETF 名录变动缓慢，缓存一周


def load_etf_list():
    """全市场场内 ETF 名录（分页，服务端单页上限 100）。内存 + 磁盘双缓存。"""
    if _ETF_CACHE['list'] and time.time() - _ETF_CACHE['ts'] < 3600:
        return _ETF_CACHE['list']

    # 磁盘缓存
    try:
        if os.path.exists(_ETF_CACHE_FILE) and time.time() - os.path.getmtime(_ETF_CACHE_FILE) < _ETF_TTL:
            with open(_ETF_CACHE_FILE, encoding='utf-8') as f:
                lst = json.load(f)
            if lst:
                _ETF_CACHE.update(ts=time.time(), list=lst)
                return lst
    except Exception:
        pass

    # ETF 联接基金的母基金都是场内 ETF。场内 ETF 分布在两个板块：
    #   b:MK0021  A股 ETF（宽基/行业/策略/主题），约 1290 只
    #   b:MK0023  跨境/港股 ETF（纳指/标普/恒生/港股创新药等），约 237 只
    # 缺了 MK0023 会导致港股/跨境 ETF 联接找不到母基金（如 019671 港股创新药）。
    ETF_BOARDS = ['b:MK0021', 'b:MK0023']
    hosts = ['push2delay.eastmoney.com', 'push2.eastmoney.com',
             '1.push2.eastmoney.com', '82.push2.eastmoney.com']
    out = []
    for host in hosts:
        out = []
        try:
            for board in ETF_BOARDS:
                board_cnt = 0
                for pn in range(1, 20):
                    r = _SESSION.get(f'https://{host}/api/qt/clist/get',
                                     params={'pn': pn, 'pz': 100, 'fs': board,
                                             'fields': 'f12,f14', 'fltt': 1, 'invt': 2},
                                     headers={'Referer': 'https://quote.eastmoney.com/'}, timeout=20)
                    d = (r.json() or {}).get('data') or {}
                    diff = d.get('diff') or []
                    if isinstance(diff, dict):
                        diff = list(diff.values())
                    if not diff:
                        break
                    out.extend({'code': str(x.get('f12')), 'name': x.get('f14') or ''} for x in diff)
                    board_cnt += len(diff)
                    total = d.get('total') or 0
                    # 以本板块累计数为准判定翻页结束，避免跨板块误判
                    if total and board_cnt >= total:
                        break
                    time.sleep(0.12)
        except Exception:
            out = []
        if len(out) > 600:   # 两板块合计约 1500+，过界说明拉取成功
            break
        time.sleep(0.5)

    if out:
        _ETF_CACHE.update(ts=time.time(), list=out)
        try:
            os.makedirs(os.path.dirname(_ETF_CACHE_FILE), exist_ok=True)
            with open(_ETF_CACHE_FILE, 'w', encoding='utf-8') as f:
                json.dump(out, f, ensure_ascii=False)
        except Exception:
            pass
    else:
        log('    ETF 名录拉取失败，母基金穿透本次跳过')
        # 过期缓存也比没有强
        try:
            with open(_ETF_CACHE_FILE, encoding='utf-8') as f:
                out = json.load(f)
        except Exception:
            out = []
    return out


def find_parent_etf(fund_name):
    """由 ETF 联接基金名反查母 ETF 代码。

    东财 ETF 命名为「指数简称 + ETF + 基金公司」，如「红利低波ETF华泰柏瑞」；
    联接基金名为「基金公司 + 指数全称 + ETF联接 + 份额」。
    以「公司名是联接基金名前缀」且「指数简称字符全部出现在联接基金名中」判定匹配。
    """
    if 'ETF' not in fund_name or '联接' not in fund_name:
        return None
    base = re.sub(r'\(QDII\)|（QDII）', '', fund_name)
    base = re.sub(r'ETF联接.*$', '', base)          # 「华泰柏瑞中证红利低波」
    core = re.sub(r'^[\u4e00-\u9fa5]{2,4}', '', base)  # 去掉公司名 -> 「中证红利低波」

    # 东财对部分 ETF 用缩写命名（如「纳指ETF」而非「纳斯达克100ETF」），
    # 统一还原成完整写法，否则联接基金名里的「纳斯达克」匹配不到「纳指」。
    def norm(s):
        return s.replace('纳指', '纳斯达克')

    def region(s):
        """地域标签：港股基金不能匹配到 A 股同名指数，反之亦然。"""
        if re.search(r'港股|香港|恒生|H股', s):
            return 'hk'
        if re.search(r'纳斯达克|标普|美国|道琼斯', s):
            return 'us'
        if re.search(r'日经|德国|法国|东南亚|沙特|越南|印度', s):
            return 'other'
        return 'cn'

    want = region(norm(base))
    best, best_len = None, 0
    for etf in load_etf_list():
        n = etf['name']
        if 'ETF' not in n:
            continue
        short, _, comp = n.partition('ETF')
        if not short:
            continue
        # 公司名必须对得上（ETF 名尾部公司 是 联接基金名的前缀）
        if comp and not base.startswith(comp[:2]):
            continue
        if region(norm(n)) != want:
            continue
        key = re.sub(r'^\d+', '', norm(short))  # 「300红利低波」-> 「红利低波」
        if not key:
            continue
        for hay in (norm(base), norm(core)):
            i = hay.find(key)
            # 右边界必须不是数字，否则「中证A50」会错配「中证A500」
            if i >= 0 and not (i + len(key) < len(hay) and hay[i + len(key)].isdigit()):
                if len(key) > best_len:
                    best, best_len = etf, len(key)
                break
    return best


def fetch_stock_quotes(secids):
    """批量个股行情：最新价/涨跌幅/PE(f9)/PB(f23)/总市值(f20)。

    东财主站 push2 对密集调用会直接断连，延时行情节点更宽松，
    且 PE/PB 本就基于收盘价，延时不影响估值判断，故优先走 delay 节点。
    """
    if not secids:
        return {}
    hosts = ['push2delay.eastmoney.com', 'push2.eastmoney.com',
             '1.push2.eastmoney.com', '82.push2.eastmoney.com']
    params = {'secids': ','.join(secids), 'fltt': '2',
              'fields': 'f12,f14,f2,f3,f9,f23,f20'}
    for host in hosts:
        try:
            r = _SESSION.get(f'https://{host}/api/qt/ulist.np/get', params=params,
                             headers={'Referer': 'https://quote.eastmoney.com/'}, timeout=20)
            data = (r.json() or {}).get('data') or {}
            diff = data.get('diff') or []
            if isinstance(diff, dict):
                diff = list(diff.values())
            if not diff:
                continue
            out = {}
            for it in diff:
                out[str(it.get('f12'))] = {
                    'code': str(it.get('f12')), 'name': it.get('f14'),
                    'price': safe_float(it.get('f2')), 'pct': safe_float(it.get('f3')),
                    'pe': safe_float(it.get('f9')), 'pb': safe_float(it.get('f23')),
                    'mcap': safe_float(it.get('f20')),
                }
            return out
        except Exception:
            time.sleep(0.4)
            continue
    log('    个股行情：全部节点不可用，本次跳过估值')
    return {}


def blend_valuation(holdings):
    """按权重穿透计算组合 PE / PB。

    调和加权：PE_组合 = Σw / Σ(w/PE)，等价于总市值除以总盈利，
    避免个别高 PE 个股把算术均值拉爆。亏损股(PE<=0)不计入，单独统计覆盖率。
    """
    def harmonic(key):
        wsum = num = 0.0
        for h in holdings:
            w, v = safe_float(h.get('weight')), safe_float(h.get(key))
            if w > 0 and v and v > 0:
                wsum += w
                num += w / v
        if num <= 0 or wsum <= 0:
            return None, 0.0
        return round(wsum / num, 2), round(wsum, 2)

    pe, pe_cov = harmonic('pe')
    pb, pb_cov = harmonic('pb')
    total_w = sum(safe_float(h.get('weight')) for h in holdings) or 1
    return {
        'pe': pe, 'pb': pb,
        'pe_coverage': round(pe_cov / total_w * 100, 1) if pe else 0,
        'pb_coverage': round(pb_cov / total_w * 100, 1) if pb else 0,
        'top_weight': round(total_w, 2),
        'stock_count': len(holdings),
    }


# ---------------------------------------------------------------- 指标计算

def _nav_at_or_before(series, target):
    """取 target 日期当天或之前最近一个净值点。"""
    lo, hi, ans = 0, len(series) - 1, None
    while lo <= hi:
        mid = (lo + hi) // 2
        if series[mid]['d'] <= target:
            ans = series[mid]
            lo = mid + 1
        else:
            hi = mid - 1
    return ans


def stage_returns(series):
    """阶段收益率。"""
    if len(series) < 2:
        return {}
    last = series[-1]
    end = dt.date.fromisoformat(last['d'])
    spans = {'1w': 7, '1m': 30, '3m': 91, '6m': 182, '1y': 365, '3y': 1095}
    out = {}
    for k, days in spans.items():
        base = _nav_at_or_before(series, (end - dt.timedelta(days=days)).isoformat())
        if base and base['v'] > 0 and base['d'] != last['d']:
            out[k] = round((last['v'] / base['v'] - 1) * 100, 2)
    ytd_base = _nav_at_or_before(series, f'{end.year - 1}-12-31')
    if ytd_base and ytd_base['v'] > 0:
        out['ytd'] = round((last['v'] / ytd_base['v'] - 1) * 100, 2)
    if series[0]['v'] > 0:
        out['all'] = round((last['v'] / series[0]['v'] - 1) * 100, 2)
    return out


def risk_metrics(series, window=TRADE_DAYS):
    """最大回撤、年化波动率、夏普比率、上涨天数占比。"""
    if len(series) < 20:
        return {}
    seg = series[-window:] if len(series) > window else series
    vals = [x['v'] for x in seg]

    peak, mdd, mdd_from, mdd_to, cur_peak_d = vals[0], 0.0, '', '', seg[0]['d']
    for i, v in enumerate(vals):
        if v > peak:
            peak, cur_peak_d = v, seg[i]['d']
        dd = (peak - v) / peak if peak else 0
        if dd > mdd:
            mdd, mdd_from, mdd_to = dd, cur_peak_d, seg[i]['d']

    rets = [(vals[i] / vals[i - 1] - 1) for i in range(1, len(vals)) if vals[i - 1]]
    if not rets:
        return {}
    mean = sum(rets) / len(rets)
    var = sum((x - mean) ** 2 for x in rets) / max(1, len(rets) - 1)
    vol = math.sqrt(var) * math.sqrt(TRADE_DAYS)
    ann = (vals[-1] / vals[0]) ** (TRADE_DAYS / len(vals)) - 1 if vals[0] > 0 else 0
    sharpe = (ann - RF) / vol if vol > 0 else 0
    win = sum(1 for x in rets if x > 0) / len(rets) * 100

    # 下行波动率 / 索提诺
    downs = [x for x in rets if x < 0]
    dvol = (math.sqrt(sum(x * x for x in downs) / len(downs)) * math.sqrt(TRADE_DAYS)) if downs else 0

    return {
        'max_drawdown': round(mdd * 100, 2),
        'mdd_from': mdd_from, 'mdd_to': mdd_to,
        'volatility': round(vol * 100, 2),
        'downside_vol': round(dvol * 100, 2),
        'annualized': round(ann * 100, 2),
        'sharpe': round(sharpe, 2),
        'sortino': round((ann - RF) / dvol, 2) if dvol > 0 else None,
        'win_rate': round(win, 1),
        'window_days': len(vals),
    }


def build_kline(series, period):
    """把净值点序列聚合成 OHLC K 线。

    净值是单点数据，按周/月分组后取组内 首/最高/最低/末 即为该周期的开高低收。
    日线不聚合，直接用当日净值（O=前收，H=L=C=当日净值）。
    """
    if not series:
        return []
    if period == 'day':
        out = []
        for i, x in enumerate(series):
            prev = series[i - 1]['v'] if i else x['v']
            out.append({'d': x['d'], 'o': prev, 'h': max(prev, x['v']),
                        'l': min(prev, x['v']), 'c': x['v'], 'p': x['p']})
        return out

    def key(dstr):
        d = dt.date.fromisoformat(dstr)
        if period == 'week':
            y, w, _ = d.isocalendar()
            return f'{y}-W{w:02d}'
        return f'{d.year}-{d.month:02d}'

    buckets = {}
    order = []
    for x in series:
        k = key(x['d'])
        if k not in buckets:
            buckets[k] = []
            order.append(k)
        buckets[k].append(x)

    out = []
    prev_close = None
    for k in order:
        grp = buckets[k]
        vals = [g['v'] for g in grp]
        o = prev_close if prev_close is not None else vals[0]
        c = vals[-1]
        out.append({'d': grp[-1]['d'], 'k': k, 'o': round(o, 4),
                    'h': round(max(max(vals), o), 4), 'l': round(min(min(vals), o), 4),
                    'c': round(c, 4),
                    'p': round((c / o - 1) * 100, 2) if o else 0})
        prev_close = c
    return out


# ---------------------------------------------------------------- 主流程

def collect_fund(code, sector='', market_type='ch'):
    """采集单只基金的完整行情档案。"""
    pz = fetch_pingzhong(code)
    series = pz['series']

    tops, season = fetch_top_holdings(code)
    secids = list(pz['secids'])
    val_from = '本基金披露持仓'
    parent = None

    # ETF 联接基金只直接持有零星股票（主仓是母 ETF），穿透到母 ETF 才有估值意义
    direct_w = sum(safe_float(h.get('weight')) for h in tops)
    if direct_w < 20 and 'ETF联接' in (pz['name'] or ''):
        parent = find_parent_etf(pz['name'])
        if parent:
            p_tops, p_season = fetch_top_holdings(parent['code'])
            if p_tops and sum(safe_float(h.get('weight')) for h in p_tops) > direct_w:
                tops, season = p_tops, p_season
                secids = []
                for h in p_tops:
                    c = h['code']
                    if c.isdigit() and len(c) == 6:
                        secids.append(f'{"1" if c[0] in "56896" else "0"}.{c}')
                    elif c.isdigit() and len(c) == 5:
                        secids.append(f'116.{c}')
                val_from = f'穿透母基金 {parent["name"]}({parent["code"]})'
            time.sleep(0.2)

    # 用 secid 拿实时行情与 PE/PB，再按代码回填到重仓股
    quotes = fetch_stock_quotes(secids)
    for h in tops:
        q = quotes.get(h['code'])
        if q:
            h.update({'price': q['price'], 'pct': q['pct'], 'pe': q['pe'],
                      'pb': q['pb'], 'mcap': q['mcap']})
    # F10 没解析出权重时，退化为按 secid 等权，至少 PE 可算
    if not tops and quotes:
        tops = [{'code': q['code'], 'name': q['name'], 'weight': round(100 / len(quotes), 2),
                 'price': q['price'], 'pct': q['pct'], 'pe': q['pe'], 'pb': q['pb'],
                 'mcap': q['mcap']} for q in quotes.values()]
        season = '权重未披露·等权估算'

    val = blend_valuation(tops)
    val['source'] = val_from
    val['parent_etf'] = parent
    last = series[-1] if series else {}

    doc = {
        'code': code,
        'name': pz['name'],
        'sector': sector,
        'market_type': market_type,
        'updated_at': dt.datetime.now().isoformat(timespec='seconds'),
        'nav': last.get('v'),
        'nav_date': last.get('d'),
        'nav_pct': last.get('p'),
        'acc_nav': pz['acc'].get(last.get('d')),
        'rate': pz['rate'], 'source_rate': pz['source_rate'], 'min_buy': pz['min_buy'],
        'managers': pz['managers'],
        'stage': stage_returns(series),
        'risk': risk_metrics(series),
        'valuation': val,
        'top_holdings': tops,
        'holding_season': season,
        'alloc': pz['alloc'],
        'scale': pz['scale'],
        'perf': pz['perf'],
        'rank_series': pz['rank_series'][-120:],
        'rank_latest': pz['rank_series'][-1]['v'] if pz['rank_series'] else None,
        'kline': {
            'day': build_kline(series[-500:], 'day'),
            'week': build_kline(series[-1300:], 'week'),
            'month': build_kline(series, 'month'),
        },
        'series_len': len(series),
        'inception': series[0]['d'] if series else '',
    }
    return doc


def collect_all(holdings, out_dir, max_workers=4):
    """按持仓批量采集，返回 {code: doc}。"""
    import os
    os.makedirs(out_dir, exist_ok=True)
    targets = [(h.get('code'), h.get('sector', ''), h.get('market_type', 'ch'))
               for h in holdings if h.get('code')]
    # 同一基金多份额只拉一次
    seen, uniq = set(), []
    for c, s, mt in targets:
        if c in seen:
            continue
        seen.add(c)
        uniq.append((c, s, mt))

    results = {}

    def one(args):
        c, s, mt = args
        try:
            d = collect_fund(c, s, mt)
            with open(os.path.join(out_dir, f'{c}.json'), 'w', encoding='utf-8') as f:
                json.dump(d, f, ensure_ascii=False, separators=(',', ':'))
            v = d['valuation']
            log(f'    {c} {d["name"][:16]} 净值{d["nav"]} '
                f'PE{v["pe"] or "-"} PB{v["pb"] or "-"} 回撤{d["risk"].get("max_drawdown", "-")}%')
            return c, d
        except Exception as e:
            log(f'    {c} 行情采集失败: {e}')
            return c, None

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        for c, d in ex.map(one, uniq):
            if d:
                results[c] = d

    # 汇总索引，供前端判断哪些基金有详情
    idx = {c: {'name': d['name'], 'nav': d['nav'], 'nav_date': d['nav_date'],
               'pe': d['valuation']['pe'], 'pb': d['valuation']['pb'],
               'mdd': d['risk'].get('max_drawdown'),
               'updated_at': d['updated_at']} for c, d in results.items()}
    with open(os.path.join(out_dir, 'index.json'), 'w', encoding='utf-8') as f:
        json.dump({'funds': idx, 'updated_at': dt.datetime.now().isoformat(timespec='seconds')},
                  f, ensure_ascii=False)
    log(f'  基金行情档案完成：{len(results)}/{len(uniq)} 只')
    return results


if __name__ == '__main__':
    import sys
    code = sys.argv[1] if len(sys.argv) > 1 else '720001'
    d = collect_fund(code)
    print(json.dumps({
        'name': d['name'], 'nav': d['nav'], 'nav_date': d['nav_date'],
        'stage': d['stage'], 'risk': d['risk'], 'valuation': d['valuation'],
        'kline_counts': {k: len(v) for k, v in d['kline'].items()},
        'tops': [(h['name'], h['weight'], h.get('pe')) for h in d['top_holdings'][:5]],
    }, ensure_ascii=False, indent=1))
