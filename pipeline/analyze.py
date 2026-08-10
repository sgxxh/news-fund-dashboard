# -*- coding: utf-8 -*-
"""分析引擎：高频词、情绪打分、新闻→板块传导、仓位建议、走势预判。

方法说明（透明可复核，非黑箱）：
  1. 分词后按词性与停用词过滤，得到高频词与话题热度
  2. 情绪分 = Σ(命中正面词 - 命中负面词) × 新闻热度权重，归一化到 [-100, 100]
  3. 板块传导 = 该板块关键词命中的新闻集合的加权情绪
  4. 仓位建议 = 消息面(50%) + 动量(30%) + 持仓偏离(20%) 的综合分
所有结论均为规则推理结果，不构成投资建议。
"""
import re, math, json
from collections import Counter, defaultdict

import jieba
import jieba.posseg as pseg

from common import log, safe_float

jieba.setLogLevel(20)

# ---------- 词表 ----------
STOPWORDS = set('''
的 了 和 是 在 有 也 就 都 而 及 与 着 或 一个 我们 你们 他们 这个 那个 什么 怎么 为了 因为
所以 但是 如果 可以 应该 已经 表示 认为 指出 记者 报道 消息 目前 今天 昨天 今年 去年 上午
下午 晚上 方面 情况 问题 工作 进行 通过 实现 提供 相关 主要 重要 有关 以及 其中 对于 关于
一直 继续 不断 更加 非常 十分 比较 仍然 依然 还是 只是 不是 没有 不会 可能 需要 出现 达到
新闻 联播 本期 节目 内容 快讯 国内 国际 央视 总台 举行 召开 发布 介绍 强调 要求 推进 加强
一些 这些 那些 各地 各类 全国 我国 中国 有关部门 记者从 获悉 显示 数据 报告 消息面 时间
点击 查看 原文 来源 编辑 责任 声明 图片 视频 万元 亿元 公司 企业 市场 行业 项目 建设 发展
东西 事情 时候 地方 大家 自己 他人 别人 上面 下面 里面 外面 之后 之前 当中 期间 左右
方式 方法 过程 结果 原因 内部 外部 整体 部分 状态 水平 程度 阶段 领域 环节 层面 角度
'''.split())

POS_WORDS = {
    '增长': 2, '上涨': 2, '涨幅': 1, '突破': 2, '利好': 3, '复苏': 2, '新高': 3, '超预期': 3,
    '扩大': 1, '加快': 1, '支持': 1, '降准': 3, '降息': 3, '量产': 2, '投产': 2, '签约': 1,
    '中标': 2, '盈利': 2, '回暖': 2, '提振': 2, '稳增长': 2, '刺激': 2, '宽松': 2, '减税': 2,
    '创新': 1, '合作': 1, '开放': 1, '获批': 2, '上市': 1, '扭亏': 3, '回购': 2, '增持': 2,
    '首个': 1, '领先': 1, '稳居': 1, '提升': 1, '优化': 1, '繁荣': 2, '景气': 2, '订单': 1,
    '充足': 1, '丰收': 1, '成效': 1, '强劲': 2, '反弹': 2, '看好': 2, '受益': 2, '放量': 1,
}
NEG_WORDS = {
    '下跌': -2, '下滑': -2, '亏损': -2, '风险': -1, '下调': -2, '放缓': -2, '萎缩': -2,
    '暴跌': -3, '冲突': -2, '制裁': -3, '加征': -3, '关税': -2, '违约': -3, '退市': -3,
    '警告': -2, '低于预期': -3, '裁员': -2, '灾情': -1, '事故': -2, '爆炸': -2, '坠毁': -2,
    '紧急状态': -2, '失控': -2, '衰退': -3, '通胀': -1, '加息': -2, '收紧': -2, '抛售': -3,
    '踩踏': -2, '停产': -2, '罚款': -2, '调查': -1, '起诉': -1, '断供': -3, '限制': -2,
    '危机': -3, '疲软': -2, '承压': -2, '回落': -1, '减产': -1, '撤离': -1, '紧张': -1,
}

# 板块关键词库：sector 名 -> 命中词
SECTOR_RULES = {
    'PCB': ['算力', 'PCB', '芯片', '半导体', '服务器', '光模块', '数据中心', 'AI', '人工智能',
            '电子', '消费电子', '智算', '英伟达', '先进制程', '晶圆', '存储', '云计算', '大模型'],
    '中证红利低波': ['红利', '分红', '高股息', '银行', '煤炭', '电力', '公用事业', '保险',
                     '长期资金', '险资', '国企', '央企', '稳健', '基建', '水电', '运营商'],
    '中证A500': ['A股', '上证', '沪深', '大盘', '资本市场', 'GDP', 'PMI', 'CPI', '货币政策',
                 '降准', '降息', '内需', '消费', '制造业', '经济', '政策', '财政', '扩内需',
                 '证监会', '外资', '北向', '稳增长', '就业', '居民消费价格'],
    '纳斯达克100': ['美股', '纳斯达克', '美联储', '加息', '降息', '科技股', '英伟达', '苹果',
                    '特斯拉', '微软', '谷歌', '美国', '硅谷', '标普', '道琼斯', '鲍威尔'],
    '香港创新药': ['创新药', '生物医药', '医药', '港股', '恒生', '医保', '集采', '临床试验',
                   '新药', '疫苗', '药企', '生物科技', '创新药出海', '药品'],
}
# 极小仓位阈值：低于此比例视为零头/尾单，不参与「低配需补」的推断
TINY_WEIGHT = 2.0
# 板块别名归并
SECTOR_ALIAS = {'纳斯达克100': ['纳指', '纳斯达克'], '中证A500': ['A500'],
                '中证红利低波': ['红利低波'], '香港创新药': ['港股创新药', '创新药']}

MACRO_TAGS = ['货币政策', '财政政策', '地缘冲突', '大宗商品', '汇率', '房地产',
              '就业', '通胀', '科技监管', '产业政策']


# ---------- 高频词 ----------
def extract_keywords(texts, topn=60):
    """分词 + 词性过滤 + 词频统计。返回 [{word, count, weight}]"""
    cnt = Counter()
    # 刻意排除 nr(人名)：音译人名碎片会污染高频词榜
    allow_pos = {'n', 'nz', 'ns', 'nt', 'vn', 'an', 'eng', 'j', 'l', 'i'}
    for t in texts:
        if not t:
            continue
        t = re.sub(r'[^\u4e00-\u9fa5A-Za-z0-9]', ' ', t)
        for w, flag in pseg.cut(t):
            w = w.strip()
            if len(w) < 2 or w in STOPWORDS:
                continue
            if w.isdigit():
                continue
            if flag[0] not in allow_pos and flag not in allow_pos:
                continue
            if re.fullmatch(r'[A-Za-z]{1,2}', w):
                continue
            cnt[w] += 1
    items = cnt.most_common(topn)
    if not items:
        return []
    mx = items[0][1]
    return [{'word': w, 'count': c, 'weight': round(c / mx, 3)} for w, c in items]


# ---------- 情绪 ----------
def sentiment_of(text):
    """返回 (分值, 命中词列表)"""
    if not text:
        return 0, []
    score, hits = 0, []
    for w, v in POS_WORDS.items():
        if w in text:
            score += v
            hits.append(w)
    for w, v in NEG_WORDS.items():
        if w in text:
            score += v
            hits.append(w)
    return score, hits


def score_news(news_items, xwlb_items):
    """给每条新闻打情绪分，并标注命中的板块。"""
    scored = []
    for n in news_items:
        body = f"{n.get('title','')} {n.get('summary','')} {n.get('story','')[:1500]}"
        s, hits = sentiment_of(body)
        heat = n.get('heat', 50) or 50
        sectors = match_sectors(body)
        scored.append({
            'id': n.get('id'), 'title': n.get('title', ''),
            'summary': (n.get('summary') or '')[:220],
            'category': n.get('category', '综合'), 'heat': heat,
            'sentiment': s, 'sent_hits': hits[:8], 'sectors': sectors,
            'publish_time': n.get('publish_time', ''), 'source': n.get('source', ''),
            'story_len': len(n.get('story') or ''),
        })
    for i, x in enumerate(xwlb_items):
        t = x.get('title', '')
        s, hits = sentiment_of(t)
        scored.append({
            'id': f'xwlb-{i}', 'title': t, 'summary': '', 'category': '新闻联播',
            'heat': 70, 'sentiment': s, 'sent_hits': hits[:8],
            'sectors': match_sectors(t), 'publish_time': '', 'source': '新闻联播',
            'story_len': 0,
        })
    return scored


def match_sectors(text):
    """文本命中哪些板块。返回 [(sector, 命中词数)]"""
    out = []
    for sec, kws in SECTOR_RULES.items():
        hit = [k for k in kws if k.lower() in text.lower()]
        if hit:
            out.append({'sector': sec, 'hits': hit[:6], 'n': len(hit)})
    return sorted(out, key=lambda x: -x['n'])


# ---------- 板块传导 ----------
def sector_impact(scored, sectors_held):
    """计算每个持仓板块受到的消息面影响。"""
    agg = {}
    for sec in sectors_held:
        rel = [s for s in scored if any(x['sector'] == sec for x in s['sectors'])]
        if not rel:
            agg[sec] = {'sector': sec, 'news_count': 0, 'score': 0.0,
                        'level': '中性', 'drivers': []}
            continue
        num = sum(s['sentiment'] * (s['heat'] / 100.0) for s in rel)
        den = sum(s['heat'] / 100.0 for s in rel) or 1
        raw = num / den
        score = max(-100, min(100, raw * 18))
        drivers = sorted(rel, key=lambda s: -(abs(s['sentiment']) * s['heat']))[:4]
        agg[sec] = {
            'sector': sec,
            'news_count': len(rel),
            'score': round(score, 1),
            'level': level_of(score),
            'drivers': [{'title': d['title'][:60], 'sentiment': d['sentiment'],
                         'heat': d['heat'], 'hits': d['sent_hits'][:4]} for d in drivers],
        }
    return agg


def level_of(s):
    if s >= 35:
        return '偏多'
    if s >= 12:
        return '温和偏多'
    if s <= -35:
        return '偏空'
    if s <= -12:
        return '温和偏空'
    return '中性'


# ---------- 仓位建议 ----------
def position_advice(holdings, impacts):
    """综合消息面/动量/偏离，给出仓位操作倾向。非投资建议。"""
    advices = []
    n = len(holdings) or 1
    even_w = 100.0 / n
    for h in holdings:
        sec = h.get('sector') or ''
        imp = impacts.get(sec, {'score': 0, 'news_count': 0, 'level': '中性'})
        news_score = imp['score']                      # -100..100

        day = safe_float(h.get('day_pct'))
        year = safe_float(h.get('year_pct'))
        # 动量分：年内趋势为主，当日为辅；做压缩避免极端值主导
        mom = max(-100, min(100, math.tanh(year / 30.0) * 70 + math.tanh(day / 3.0) * 30))

        # 偏离分：权重过高→建议降低，过低→可补
        w = safe_float(h.get('weight'))
        tiny = w < TINY_WEIGHT
        if tiny:
            # 零头持仓（如同一基金的尾数份额）不应因「极度低配」刷出高分
            dev = 0.0
        else:
            dev = (even_w - w) / even_w * 100 if even_w else 0
            dev = max(-100, min(100, dev))

        # 盈亏状态微调：深亏且消息面转好 → 倾向补；大幅盈利且消息面转差 → 倾向止盈
        ep = safe_float(h.get('earn_pct'))

        total = news_score * 0.5 + mom * 0.3 + dev * 0.2
        if ep > 20 and news_score < 0:
            total -= 10
        if ep < -10 and news_score > 20:
            total += 8

        action, reason = decide(total, news_score, mom, w, even_w, ep, imp, tiny)
        advices.append({
            'code': h.get('code'), 'name': h.get('name'),
            'sector': sec, 'weight': w, 'tiny': tiny,
            'earn_pct': ep, 'day_pct': day, 'year_pct': year,
            'news_score': round(news_score, 1), 'news_count': imp.get('news_count', 0),
            'news_level': imp.get('level', '中性'),
            'momentum': round(mom, 1), 'deviation': round(dev, 1),
            'total_score': round(total, 1),
            'action': action, 'reason': reason,
        })
    advices.sort(key=lambda x: -x['total_score'])
    return advices


def decide(total, news, mom, w, even_w, ep, imp, tiny=False):
    if tiny:
        return '零头持仓·可并入同类', (
            f'仅占 {w:.2f}%，属尾数份额；'
            f"板块消息面{imp.get('level','中性')}，建议与同标的主份额合并管理，单独调仓意义不大"
        )
    if total >= 30:
        act = '可考虑加仓'
    elif total >= 10:
        act = '持有偏乐观'
    elif total <= -30:
        act = '建议减仓'
    elif total <= -10:
        act = '持有偏谨慎'
    else:
        act = '维持观望'

    bits = []
    if imp.get('news_count'):
        bits.append(f"板块命中 {imp['news_count']} 条相关新闻，消息面{imp.get('level')}")
    else:
        bits.append('当日无直接相关新闻，消息面中性')
    if mom > 25:
        bits.append('中期动量向上')
    elif mom < -25:
        bits.append('中期动量走弱')
    else:
        bits.append('动量中性')
    if w > even_w * 1.35:
        bits.append(f'仓位占比 {w:.1f}% 偏集中')
    elif w < even_w * 0.5:
        bits.append(f'仓位占比 {w:.1f}% 偏低')
    if ep > 15:
        bits.append(f'浮盈 {ep:.1f}%，注意止盈纪律')
    elif ep < -8:
        bits.append(f'浮亏 {ep:.1f}%，关注补仓成本')
    return act, '；'.join(bits)


# ---------- 走势预判 ----------
def forecast(impacts, holdings, index_data):
    """对持仓相关板块给出短期倾向。规则推理，非预测承诺。"""
    out = []
    for sec, imp in impacts.items():
        hs = [h for h in holdings if h.get('sector') == sec]
        year = sum(safe_float(h.get('year_pct')) for h in hs) / len(hs) if hs else 0
        s = imp['score']
        mom = math.tanh(year / 30.0) * 100
        blend = s * 0.6 + mom * 0.4
        if blend >= 30:
            bias, prob = '看多', min(78, 50 + blend * 0.35)
        elif blend >= 10:
            bias, prob = '偏多震荡', min(68, 50 + blend * 0.3)
        elif blend <= -30:
            bias, prob = '看空', min(78, 50 + abs(blend) * 0.35)
        elif blend <= -10:
            bias, prob = '偏空震荡', min(68, 50 + abs(blend) * 0.3)
        else:
            bias, prob = '区间震荡', 55
        conf = '高' if imp['news_count'] >= 5 else ('中' if imp['news_count'] >= 2 else '低')
        out.append({
            'sector': sec, 'bias': bias, 'prob': round(prob),
            'confidence': conf, 'news_count': imp['news_count'],
            'blend': round(blend, 1),
            'note': f"消息面 {imp['score']:+.0f} / 中期动量 {mom:+.0f}",
        })
    out.sort(key=lambda x: -x['blend'])
    return out


# ---------- 主分析 ----------
def analyze(news_pack, fund_pack):
    news = news_pack.get('news', [])
    xwlb = news_pack.get('xwlb', [])
    holdings = fund_pack.get('holdings', [])

    texts = [f"{n.get('title','')} {n.get('summary','')} {n.get('story','')[:2000]}" for n in news]
    texts += [x.get('title', '') for x in xwlb]
    keywords = extract_keywords(texts, topn=60)

    scored = score_news(news, xwlb)

    # 全局情绪
    if scored:
        num = sum(s['sentiment'] * (s['heat'] / 100.0) for s in scored)
        den = sum(s['heat'] / 100.0 for s in scored) or 1
        market_mood = max(-100, min(100, num / den * 18))
    else:
        market_mood = 0

    sectors_held = sorted({h.get('sector') for h in holdings if h.get('sector')})
    impacts = sector_impact(scored, sectors_held)
    advices = position_advice(holdings, impacts)
    fc = forecast(impacts, holdings, fund_pack.get('index', []))

    cat_dist = Counter(s['category'] for s in scored)
    top_news = sorted(scored, key=lambda s: -(s['heat'] + abs(s['sentiment']) * 3))[:12]

    return {
        'keywords': keywords,
        'market_mood': round(market_mood, 1),
        'market_mood_level': level_of(market_mood),
        'sector_impacts': impacts,
        'advices': advices,
        'forecast': fc,
        'category_dist': dict(cat_dist),
        'top_news': top_news,
        'scored_news': scored,
        'stats': {
            'news_total': len(news), 'xwlb_total': len(xwlb),
            'scored_total': len(scored),
            'pos': sum(1 for s in scored if s['sentiment'] > 0),
            'neg': sum(1 for s in scored if s['sentiment'] < 0),
            'neutral': sum(1 for s in scored if s['sentiment'] == 0),
        },
    }
