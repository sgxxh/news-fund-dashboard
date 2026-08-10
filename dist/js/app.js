/* 新闻·基金工作台 —— 纯原生实现，无外部依赖，可离线运行 */
'use strict';

const S = {
  index: null,      // 日期索引
  doc: null,        // 当前日档案
  date: null,
  view: 'overview',
  showMoney: localStorage.getItem('showMoney') === '1',
  newsFilter: 'all',
  repType: 'week',
  repIndex: null,
  repDoc: null,
  apiBase: '',      // 后端基地址：''=同源(本机/VPS托管)；云端静态版可配为 VPS 地址
  cloud: false,     // 是否 GitHub Pages 云端模式（无后端，数据由 Actions 定时刷新）
};

/* ---------------- 工具 ---------------- */
const $ = s => document.querySelector(s);
const el = (t, c, h) => { const e = document.createElement(t); if (c) e.className = c; if (h != null) e.innerHTML = h; return e; };
const esc = s => String(s ?? '').replace(/[&<>"']/g, m => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[m]));

// 涨红跌绿（A股习惯）
const cls = v => v > 0 ? 'up' : (v < 0 ? 'down' : 'flat');
const numCls = s => {
  const n = typeof s === 'number' ? s : parseFloat(String(s).replace(/[+%]/g, ''));
  return cls(isNaN(n) ? 0 : n);
};
const sign = v => (v > 0 ? '+' : '') + v;
const pct = (v, d = 2) => { const n = Number(v) || 0; return `<span class="${cls(n)}">${n > 0 ? '+' : ''}${n.toFixed(d)}%</span>`; };
const money = v => {
  const n = Number(v) || 0;
  if (!S.showMoney) return '<span class="masked">••••</span>';
  return '¥' + n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
};
const moneySigned = v => {
  const n = Number(v) || 0;
  if (!S.showMoney) return `<span class="masked ${cls(n)}">••••</span>`;
  return `<span class="${cls(n)}">${n > 0 ? '+' : ''}${n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>`;
};

async function getJSON(url) {
  const r = await fetch(url + (url.includes('?') ? '&' : '?') + 't=' + Date.now());
  if (!r.ok) throw new Error(url + ' -> ' + r.status);
  return r.json();
}

// 后端基地址：云端静态版可经 data/backend.json 指向 VPS 后端
const api = p => (S.apiBase || '') + p;

/* ---------------- 启动 ---------------- */
async function boot() {
  try {
    if (S.cloud) setCloudPill(); else await detectApi();
    S.index = await getJSON('data/index.json');
    const dates = S.index.dates || [];
    if (!dates.length) { $('#main').innerHTML = '<div class="empty">暂无数据，请先运行采集管道。</div>'; return; }
    const sel = $('#dateSel');
    sel.innerHTML = dates.map(d => {
      const wd = '日一二三四五六'[new Date(d.date + 'T00:00:00').getDay()];
      return `<option value="${d.date}">${d.date} 周${wd}　情绪 ${sign(d.mood)}</option>`;
    }).join('');
    S.date = dates[0].date;
    sel.value = S.date;
    $('#tbSub').textContent = '最近更新 ' + (S.index.updated_at || '').replace('T', ' ').slice(0, 16);
    $('#footMeta').textContent = `数据覆盖 ${dates.length} 天 · ${dates[dates.length - 1].date} 至 ${dates[0].date}`;
    syncEye();
    await loadDay(S.date);
  } catch (e) {
    $('#main').innerHTML = `<div class="empty">加载失败：${esc(e.message)}</div>`;
  }
}

async function loadDay(d) {
  $('#main').innerHTML = '<div class="loading"><div class="spinner"></div><span>正在载入 ' + d + '…</span></div>';
  try {
    S.doc = await getJSON(`data/daily/${d}.json`);
    S.date = d;
    const sess = { morning: '早报', evening: '晚报', backfill: '回补', auto: '自动' }[S.doc.session] || S.doc.session || '';
    $('#sessionBadge').textContent = sess;
    updateNav();
    render();
  } catch (e) {
    $('#main').innerHTML = `<div class="empty">该日期数据不可用：${esc(e.message)}</div>`;
  }
}

function updateNav() {
  const ds = (S.index.dates || []).map(x => x.date);
  const i = ds.indexOf(S.date);
  $('#nextDay').disabled = i <= 0;
  $('#prevDay').disabled = i < 0 || i >= ds.length - 1;
}

/* ---------------- 渲染分发 ---------------- */
function render() {
  const m = $('#main');
  m.innerHTML = '';
  ({ overview: vOverview, news: vNews, words: vWords, funds: vFunds, reports: vReports }[S.view] || vOverview)(m);
  // 注意：不在重渲染时强制滚动，避免点击标签/筛选/按钮时页面跳动
}

/* ---------------- 概览 ---------------- */
function vOverview(m) {
  const a = S.doc.analysis || {}, f = S.doc.funds || {}, s = f.summary || {};
  const st = a.stats || {};

  // KPI
  const k = el('div', 'kpis');
  k.innerHTML = `
    <div class="kpi"><div class="k-label">持仓总市值</div><div class="k-val">${money(s.total_money)}</div>
      <div class="k-sub">${s.count || 0} 只基金</div></div>
    <div class="kpi"><div class="k-label">今日收益</div><div class="k-val">${moneySigned(s.today_income)}</div>
      <div class="k-sub">${pct(s.today_income_rate)}</div></div>
    <div class="kpi"><div class="k-label">累计盈亏</div><div class="k-val">${moneySigned(s.total_earn)}</div>
      <div class="k-sub">${pct(s.total_earn_pct)}</div></div>
    <div class="kpi"><div class="k-label">今日资讯</div><div class="k-val">${(st.news_total || 0) + (st.xwlb_total || 0)}</div>
      <div class="k-sub">要闻 ${st.news_total || 0} · 联播 ${st.xwlb_total || 0}</div></div>`;
  m.appendChild(k);

  if (!f.ok) {
    const w = el('div', 'card');
    w.innerHTML = `<h3>⚠️ 基金数据未接入</h3><div class="sub">${f.reason === 'TOKEN_EXPIRED'
      ? '养基宝登录已过期，请在电脑端重新扫码登录后重跑采集。'
      : '原因：' + esc(f.reason || '未知')}</div>`;
    m.appendChild(w);
  }

  // 市场情绪
  const mood = Number(a.market_mood) || 0;
  const c1 = el('div', 'card');
  c1.innerHTML = `<h3>市场消息面情绪<span class="h-tag">${st.pos || 0} 正面 / ${st.neg || 0} 负面 / ${st.neutral || 0} 中性</span></h3>
    <div class="mood-wrap">
      <div class="mood-num ${cls(mood)}">${sign(mood.toFixed(1))}</div>
      <div class="mood-meta">
        <div style="font-weight:600;font-size:14px">${esc(a.market_mood_level || '中性')}</div>
        <div class="mood-bar"><div class="mood-pin" style="left:calc(${(mood + 100) / 2}% - 2px)"></div></div>
        <div class="mood-scale"><span>-100 极度悲观</span><span>0</span><span>+100 极度乐观</span></div>
      </div>
    </div>
    <div class="note">基于当日 ${st.scored_total || 0} 条资讯的情绪词命中情况，按新闻热度加权计算。</div>`;
  m.appendChild(c1);

  // 板块传导
  const imps = Object.values(a.sector_impacts || {}).sort((x, y) => y.score - x.score);
  if (imps.length) {
    const c2 = el('div', 'card');
    c2.innerHTML = '<h3>新闻 → 持仓板块传导</h3><div class="sub">当日新闻按关键词映射到你持有的板块，加权得出消息面强弱</div>';
    imps.forEach(v => {
      const row = el('div', 'fc');
      row.innerHTML = `${ringSVG(v.score)}
        <div class="fc-s">${esc(v.sector)}
          <div class="fc-p">命中 ${v.news_count} 条 · ${esc(v.level)}</div></div>
        <div class="num ${cls(v.score)}" style="font-weight:650;font-size:15px">${sign(v.score.toFixed(1))}</div>`;
      c2.appendChild(row);
    });
    m.appendChild(c2);
  }

  // 今日要闻 TOP
  const top = (a.top_news || []).slice(0, 6);
  if (top.length) {
    const c3 = el('div', 'card');
    c3.innerHTML = '<h3>今日最高关注</h3>';
    top.forEach(n => c3.appendChild(newsNode(n)));
    m.appendChild(c3);
  }

  // 指数
  if ((f.index || []).length) {
    const c4 = el('div', 'card');
    c4.innerHTML = '<h3>主要指数</h3>';
    f.index.forEach(i => {
      c4.appendChild(el('div', 'idx-row',
        `<span>${esc(i.name)}</span><span class="num"><b>${i.value}</b>　${pct(i.pct)}</span>`));
    });
    m.appendChild(c4);
  }
}

/* 环形分数图 */
function ringSVG(score) {
  const v = Math.max(-100, Math.min(100, Number(score) || 0));
  const r = 17, C = 2 * Math.PI * r, len = Math.abs(v) / 100 * C;
  const col = v > 0 ? '#e0384e' : (v < 0 ? '#0f9d76' : '#c3cad6');
  return `<svg class="ring" viewBox="0 0 44 44">
    <circle cx="22" cy="22" r="${r}" fill="none" stroke="#eef1f6" stroke-width="4"/>
    <circle cx="22" cy="22" r="${r}" fill="none" stroke="${col}" stroke-width="4" stroke-linecap="round"
      stroke-dasharray="${len} ${C}" transform="rotate(-90 22 22)"/>
    <text x="22" y="26" text-anchor="middle" font-size="11" font-weight="700" fill="${col}">${Math.round(Math.abs(v))}</text>
  </svg>`;
}

/* ---------------- 新闻 ---------------- */
function newsNode(n) {
  const d = el('div', 'news-item row-click');
  const h = Math.round(n.heat || 0);
  const secs = (n.sectors || []).map(s => `<span class="tag">${esc(s.sector)}</span>`).join('');
  const sent = n.sentiment ? `<span class="tag ${cls(n.sentiment)}">情绪 ${sign(n.sentiment)}</span>` : '';
  const hits = (n.sent_hits || []).slice(0, 4).map(x => `<span class="tag">${esc(x)}</span>`).join('');
  d.innerHTML = `<div class="news-h">
      <span class="heat ${h < 60 ? 'low' : ''}">${h}</span>
      <div class="news-t">${esc(n.title)}</div></div>
    ${n.summary ? `<p class="news-s">${esc(n.summary)}</p>` : ''}
    <div class="news-m"><span class="tag">${esc(n.category || '综合')}</span>${sent}${secs}${hits}</div>`;
  d.dataset.nid = n.id;
  d.onclick = () => openNews(n.id, n.title);
  return d;
}

function vNews(m) {
  const a = S.doc.analysis || {};
  const all = a.scored_news || [];
  const cats = ['all', ...Object.keys(a.category_dist || {})];

  const fw = el('div', 'filters');
  cats.forEach(c => {
    const b = el('button', 'chip' + (S.newsFilter === c ? ' on' : ''),
      c === 'all' ? `全部 ${all.length}` : `${esc(c)} ${a.category_dist[c]}`);
    b.onclick = () => { S.newsFilter = c; render(); };
    fw.appendChild(b);
  });
  m.appendChild(fw);

  const list = S.newsFilter === 'all' ? all : all.filter(n => n.category === S.newsFilter);
  const sorted = [...list].sort((x, y) => y.heat - x.heat);

  const c = el('div', 'card');
  c.innerHTML = `<h3>${S.newsFilter === 'all' ? '全部资讯' : esc(S.newsFilter)}<span class="h-tag">${sorted.length} 条</span></h3>`;
  if (!sorted.length) c.appendChild(el('div', 'empty', '该分类暂无内容'));
  sorted.forEach(n => c.appendChild(newsNode(n)));
  m.appendChild(c);
}

/* ---------------- 高频词 ---------------- */
function vWords(m) {
  const kws = (S.doc.analysis || {}).keywords || [];
  if (!kws.length) { m.appendChild(el('div', 'empty', '暂无高频词数据')); return; }

  const c1 = el('div', 'card');
  c1.innerHTML = `<h3>高频词云<span class="h-tag">TOP ${Math.min(kws.length, 50)}</span></h3>
    <div class="sub">来自当日全部要闻正文与新闻联播要目，已过滤停用词与人名</div>`;
  const cloud = el('div', 'cloud');
  const palette = ['#1a2b4c', '#2563eb', '#0f9d76', '#e0384e', '#7c3aed', '#d97706', '#0891b2'];
  kws.slice(0, 50).forEach((k, i) => {
    const size = 13 + k.weight * 21;
    const op = 0.55 + k.weight * 0.45;
    const s = el('span', 'cw', esc(k.word));
    s.style.cssText = `font-size:${size.toFixed(1)}px;color:${palette[i % palette.length]};opacity:${op.toFixed(2)}`;
    s.title = `出现 ${k.count} 次`;
    cloud.appendChild(s);
  });
  c1.appendChild(cloud);
  m.appendChild(c1);

  const c2 = el('div', 'card');
  c2.innerHTML = '<h3>词频排行</h3>';
  const wl = el('div', 'wlist');
  kws.slice(0, 30).forEach(k => {
    wl.appendChild(el('div', 'wrow',
      `<span class="wn" title="${esc(k.word)}">${esc(k.word)}</span>
       <span class="wbar"><i style="width:${(k.weight * 100).toFixed(1)}%"></i></span>
       <span class="wc">${k.count}</span>`));
  });
  c2.appendChild(wl);
  m.appendChild(c2);
}

/* ---------------- 基金 ---------------- */
function actClass(a) {
  if (a.includes('加仓')) return 'act-add';
  if (a.includes('减仓')) return 'act-cut';
  if (a.includes('零头')) return 'act-tiny';
  if (a.includes('持有')) return 'act-hold';
  return 'act-wait';
}

function vFunds(m) {
  const f = S.doc.funds || {}, a = S.doc.analysis || {};
  const hs = f.holdings || [];

  if (!hs.length) {
    m.appendChild(el('div', 'empty',
      f.reason === 'TOKEN_EXPIRED' ? '养基宝登录已过期，请重新扫码后重跑采集。' : '暂无持仓数据'));
    return;
  }

  // 持仓表
  const c1 = el('div', 'card');
  c1.innerHTML = `<h3>持仓明细<span class="h-tag">合计 ${money(f.summary?.total_money)}</span></h3>`;
  const sc = el('div', 'scroll-x');
  sc.innerHTML = `<table class="tbl"><thead><tr>
      <th>基金 / 板块</th><th class="num">占比</th><th class="num">市值</th>
      <th class="num">当日</th><th class="num">持有收益</th><th class="num">年内</th></tr></thead>
    <tbody>${hs.map(h => `<tr class="row-click" data-code="${esc(h.code)}">
      <td><div style="font-weight:600;font-size:13px">${esc(h.name)}</div>
          <div style="font-size:11px;color:var(--ink3)">${esc(h.code)}${h.sector ? ' · ' + esc(h.sector) : ''}</div></td>
      <td class="num">${(h.weight || 0).toFixed(1)}%</td>
      <td class="num">${money(h.money)}</td>
      <td class="num">${pct(h.day_pct)}</td>
      <td class="num">${moneySigned(h.earn)}<br><span style="font-size:11px">${pct(h.earn_pct)}</span></td>
      <td class="num">${pct(h.year_pct)}</td></tr>`).join('')}</tbody></table>`;
  sc.querySelectorAll('tbody tr').forEach(tr => {
    tr.onclick = () => openFund(tr.dataset.code);
  });
  c1.appendChild(sc);
  m.appendChild(c1);

  // 仓位建议
  const adv = a.advices || [];
  if (adv.length) {
    const c2 = el('div', 'card');
    c2.innerHTML = `<h3>今日仓位操作建议</h3>
      <div class="sub">综合评分 = 消息面 50% + 中期动量 30% + 持仓偏离 20%，分数越高越偏积极</div>`;
    adv.forEach(x => {
      const d = el('div', 'adv');
      d.innerHTML = `<div class="adv-h">
          <div><div class="adv-n">${esc(x.name)}</div>
            <div class="adv-c">${esc(x.code)}${x.sector ? ' · ' + esc(x.sector) : ''} · 占比 ${(x.weight || 0).toFixed(1)}%</div></div>
          <span class="tag ${actClass(x.action)}">${esc(x.action)}</span></div>
        <div class="bars">
          ${bx('消息面', x.news_score)}${bx('动量', x.momentum)}${bx('偏离', x.deviation)}
        </div>
        <div class="adv-r"><b>综合 ${sign(x.total_score)}</b> · ${esc(x.reason)}</div>`;
      c2.appendChild(d);
    });
    m.appendChild(c2);
  }

  // 走势预判
  const fc = a.forecast || [];
  if (fc.length) {
    const c3 = el('div', 'card');
    c3.innerHTML = `<h3>未来走势倾向<span class="h-tag">短期视角</span></h3>
      <div class="sub">规则模型基于消息面与中期动量推演，概率为倾向强度而非真实胜率</div>`;
    fc.forEach(x => {
      const isUp = x.bias.includes('多');
      const isDn = x.bias.includes('空');
      const col = isUp ? 'up' : (isDn ? 'down' : 'flat');
      c3.appendChild(el('div', 'fc',
        `${ringSVG(x.blend)}
         <div class="fc-s">${esc(x.sector)} <span class="tag ${col}">${esc(x.bias)}</span>
           <div class="fc-p">${esc(x.note)} · 命中 ${x.news_count} 条 · 置信度 ${esc(x.confidence)}</div></div>
         <div class="num" style="font-weight:650">${x.prob}%</div>`));
    });
    m.appendChild(c3);
  }
}

function bx(label, v) {
  const n = Number(v) || 0;
  const col = n > 0 ? '#e0384e' : (n < 0 ? '#0f9d76' : '#c3cad6');
  const w = Math.min(50, Math.abs(n) / 2);
  const left = n >= 0 ? 50 : 50 - w;
  return `<div class="bx">${label}<div class="bv ${cls(n)}">${sign(n.toFixed(0))}</div>
    <div class="mini"><i style="left:${left}%;width:${w}%;background:${col}"></i></div></div>`;
}

/* ---------------- 报告 ---------------- */
async function vReports(m) {
  const tabs = el('div', 'rep-tabs');
  [['week', '周报'], ['month', '月报'], ['quarter', '季报']].forEach(([k, n]) => {
    const b = el('button', 'chip' + (S.repType === k ? ' on' : ''), n);
    b.onclick = () => { S.repType = k; S.repDoc = null; render(); };
    tabs.appendChild(b);
  });
  m.appendChild(tabs);

  const holder = el('div');
  m.appendChild(holder);
  holder.innerHTML = '<div class="loading"><div class="spinner"></div><span>载入报告…</span></div>';

  try {
    if (!S.repIndex) S.repIndex = await getJSON('data/reports/index.json');
    const list = S.repIndex[S.repType] || [];
    if (!list.length) { holder.innerHTML = '<div class="empty">该周期暂无报告</div>'; return; }

    const sel = el('select', 'date-sel');
    sel.innerHTML = list.map(r =>
      `<option value="${r.key}">${r.key}　${r.date_from} ~ ${r.date_to}　${r.days}天</option>`).join('');
    const wrap = el('div', 'card');
    wrap.innerHTML = '<h3>选择报告期</h3>';
    wrap.appendChild(sel);
    holder.innerHTML = '';
    holder.appendChild(wrap);

    const body = el('div');
    holder.appendChild(body);
    const load = async key => {
      body.innerHTML = '<div class="loading"><div class="spinner"></div><span>载入中…</span></div>';
      const rep = await getJSON(`data/reports/${S.repType}-${key}.json`);
      body.innerHTML = '';
      renderReport(body, rep);
    };
    sel.onchange = () => load(sel.value);
    await load(list[0].key);
  } catch (e) {
    holder.innerHTML = `<div class="empty">报告加载失败：${esc(e.message)}</div>`;
  }
}

function renderReport(root, r) {
  const k = el('div', 'kpis');
  const nav = r.nav_series || [];
  const first = nav[0], last = nav[nav.length - 1];
  const delta = (first && last) ? last.total - first.total : 0;
  k.innerHTML = `
    <div class="kpi"><div class="k-label">覆盖天数</div><div class="k-val">${r.days}</div>
      <div class="k-sub">${r.date_from} ~ ${r.date_to}</div></div>
    <div class="kpi"><div class="k-label">平均情绪</div><div class="k-val ${cls(r.avg_mood)}">${sign(r.avg_mood)}</div>
      <div class="k-sub">区间消息面均值</div></div>
    <div class="kpi"><div class="k-label">资讯总量</div><div class="k-val">${(r.stats?.news_total || 0) + (r.stats?.xwlb_total || 0)}</div>
      <div class="k-sub">要闻 ${r.stats?.news_total || 0} · 联播 ${r.stats?.xwlb_total || 0}</div></div>
    <div class="kpi"><div class="k-label">期内市值变化</div><div class="k-val">${moneySigned(delta)}</div>
      <div class="k-sub">${nav.length ? nav.length + ' 个采样日' : '无持仓采样'}</div></div>`;
  root.appendChild(k);

  // 情绪走势
  const ms = r.mood_series || [];
  if (ms.length > 1) {
    const c = el('div', 'card');
    c.innerHTML = '<h3>情绪走势</h3>';
    c.appendChild(sparkline(ms.map(x => x.mood), ms.map(x => x.date)));
    root.appendChild(c);
  }

  // 板块表现
  if ((r.sectors || []).length) {
    const c = el('div', 'card');
    c.innerHTML = '<h3>板块消息面表现</h3>';
    const sc = el('div', 'scroll-x');
    sc.innerHTML = `<table class="tbl"><thead><tr><th>板块</th><th class="num">均值</th>
        <th class="num">最高</th><th class="num">最低</th><th class="num">相关新闻</th></tr></thead>
      <tbody>${r.sectors.map(s => `<tr><td><b>${esc(s.sector)}</b></td>
        <td class="num ${cls(s.avg_score)}">${sign(s.avg_score)}</td>
        <td class="num up">${sign(s.max_score)}</td>
        <td class="num down">${sign(s.min_score)}</td>
        <td class="num">${s.news_count}</td></tr>`).join('')}</tbody></table>`;
    c.appendChild(sc);
    root.appendChild(c);
  }

  // 建议一致性
  if ((r.advice_consistency || []).length) {
    const c = el('div', 'card');
    c.innerHTML = `<h3>期内建议倾向</h3><div class="sub">同一标的在本期内出现最多的建议方向及其占比</div>`;
    const sc = el('div', 'scroll-x');
    sc.innerHTML = `<table class="tbl"><thead><tr><th>基金</th><th>主导建议</th>
        <th class="num">占比</th><th class="num">天数</th></tr></thead>
      <tbody>${r.advice_consistency.map(x => `<tr>
        <td style="font-size:12.5px">${esc(x.name)}</td>
        <td><span class="tag ${actClass(x.dominant)}">${esc(x.dominant)}</span></td>
        <td class="num">${x.ratio}%</td><td class="num">${x.days}/${x.total_days}</td></tr>`).join('')}</tbody></table>`;
    c.appendChild(sc);
    root.appendChild(c);
  }

  // 持仓变化
  if ((r.holding_change || []).length) {
    const c = el('div', 'card');
    c.innerHTML = '<h3>持仓变化</h3>';
    const sc = el('div', 'scroll-x');
    sc.innerHTML = `<table class="tbl"><thead><tr><th>基金</th><th class="num">占比</th>
        <th class="num">市值变化</th><th class="num">收益率变化</th></tr></thead>
      <tbody>${r.holding_change.map(h => `<tr>
        <td style="font-size:12.5px">${esc(h.name)}<div style="font-size:11px;color:var(--ink3)">${esc(h.sector || '')}</div></td>
        <td class="num">${(h.weight || 0).toFixed(1)}%</td>
        <td class="num">${moneySigned(h.money_delta)}</td>
        <td class="num ${cls(h.earn_pct_delta)}">${sign(h.earn_pct_delta.toFixed(2))}pp</td></tr>`).join('')}</tbody></table>`;
    c.appendChild(sc);
    root.appendChild(c);
  }

  // 高频词
  if ((r.keywords || []).length) {
    const c = el('div', 'card');
    c.innerHTML = '<h3>期内高频词</h3>';
    const cloud = el('div', 'cloud');
    const palette = ['#1a2b4c', '#2563eb', '#0f9d76', '#e0384e', '#7c3aed', '#d97706'];
    r.keywords.slice(0, 40).forEach((k2, i) => {
      const s = el('span', 'cw', esc(k2.word));
      s.style.cssText = `font-size:${(13 + k2.weight * 19).toFixed(1)}px;color:${palette[i % palette.length]};opacity:${(0.55 + k2.weight * 0.45).toFixed(2)}`;
      s.title = `${k2.count} 次`;
      cloud.appendChild(s);
    });
    c.appendChild(cloud);
    root.appendChild(c);
  }

  // 大事记
  if ((r.top_events || []).length) {
    const c = el('div', 'card');
    c.innerHTML = '<h3>期内高关注事件</h3>';
    const tl = el('div', 'tl');
    r.top_events.slice(0, 14).forEach(e => {
      tl.appendChild(el('div', 'tl-i',
        `<div style="font-size:11.5px;color:var(--ink3)">${e.date} · ${esc(e.category || '')}</div>
         <div style="font-size:13.5px;font-weight:600;margin-top:3px">${esc(e.title)}</div>
         <div style="margin-top:5px"><span class="tag">热度 ${Math.round(e.heat)}</span>
           <span class="tag ${cls(e.sentiment)}">情绪 ${sign(e.sentiment)}</span></div>`));
    });
    c.appendChild(tl);
    root.appendChild(c);
  }
}

/* 折线图 */
function sparkline(vals, labels) {
  const w = 600, h = 90, pad = 8;
  const mx = Math.max(...vals, 10), mn = Math.min(...vals, -10);
  const rng = (mx - mn) || 1;
  const X = i => pad + i * (w - pad * 2) / Math.max(1, vals.length - 1);
  const Y = v => pad + (1 - (v - mn) / rng) * (h - pad * 2);
  const pts = vals.map((v, i) => `${X(i).toFixed(1)},${Y(v).toFixed(1)}`).join(' ');
  const zeroY = Y(0).toFixed(1);
  const area = `${pad},${zeroY} ${pts} ${X(vals.length - 1).toFixed(1)},${zeroY}`;
  const dots = vals.map((v, i) =>
    `<circle cx="${X(i).toFixed(1)}" cy="${Y(v).toFixed(1)}" r="2.4"
      fill="${v >= 0 ? '#e0384e' : '#0f9d76'}"><title>${labels[i]}: ${v}</title></circle>`).join('');
  const s = el('div');
  s.innerHTML = `<svg class="spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">
    <line x1="${pad}" y1="${zeroY}" x2="${w - pad}" y2="${zeroY}" stroke="#e5e9f0" stroke-width="1" stroke-dasharray="3 3"/>
    <polygon points="${area}" fill="rgba(37,99,235,.09)"/>
    <polyline points="${pts}" fill="none" stroke="#2563eb" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>
    ${dots}</svg>
    <div style="display:flex;justify-content:space-between;font-size:10.5px;color:var(--ink3);margin-top:4px">
      <span>${labels[0]}</span><span>${labels[labels.length - 1]}</span></div>`;
  return s;
}

/* ---------------- 弹层：新闻全文 / 基金详情 ---------------- */
let fundCache = {};

function toast(msg, type) {
  let t = $('#toast');
  if (!t) {
    t = el('div'); t.id = 'toast';
    t.style.cssText = 'position:fixed;left:50%;bottom:calc(86px + env(safe-area-inset-bottom,0px));' +
      'transform:translateX(-50%);z-index:300;padding:10px 18px;border-radius:22px;font-size:13px;' +
      'font-weight:600;color:#fff;box-shadow:0 6px 22px rgba(16,24,40,.22);max-width:84vw;text-align:center;' +
      'transition:opacity .25s,transform .25s;pointer-events:none';
    document.body.appendChild(t);
  }
  const bg = type === 'warn' ? '#d97706' : (type === 'err' ? '#e0384e' : '#1a2b4c');
  t.style.background = bg; t.textContent = msg; t.style.opacity = '1'; t.style.transform = 'translateX(-50%) translateY(0)';
  clearTimeout(toast._t);
  toast._t = setTimeout(() => { t.style.opacity = '0'; t.style.transform = 'translateX(-50%) translateY(8px)'; }, 2200);
}

function closeModal() {
  const ex = $('#modalOv'); if (ex) ex.remove();
  document.body.style.overflow = '';
  S._fundDoc = null;
}

function modalShell(title, subHtml) {
  closeModal();
  const ov = el('div', 'modal-ov'); ov.id = 'modalOv';
  const m = el('div', 'modal');
  const h = el('div', 'modal-h');
  h.innerHTML = `<div class="mh-t">${title}</div>`;
  const x = el('button', 'modal-x', '×'); x.setAttribute('aria-label', '关闭');
  x.onclick = closeModal;
  h.appendChild(x);
  m.appendChild(h);
  if (subHtml) m.insertAdjacentHTML('beforeend', subHtml);
  ov.appendChild(m);
  ov.onclick = e => { if (e.target === ov) closeModal(); };
  $('#modalRoot').appendChild(ov);
  document.body.style.overflow = 'hidden';
  return m;
}

/* 新闻全文弹层 */
function openNews(id, title) {
  const doc = S.doc;
  const raws = doc.news_raw || [];
  const scs = (doc.analysis || {}).scored_news || [];
  const xwlbs = doc.xwlb_raw || [];
  // 优先按 id 解析
  let raw = raws.find(r => String(r.id) === String(id)) || {};
  let sc = scs.find(n => String(n.id) === String(id)) || {};
  // 新闻联播条目 id 为 null，退化为按标题解析
  if ((!raw.title && !sc.title) && title) {
    raw = raws.find(r => r.title === title) || {};
    sc = scs.find(n => n.title === title) || {};
  }
  const title0 = raw.title || sc.title || title || '新闻详情';
  // 判定是否为新闻联播（仅要目、无正文）
  const isXwlb = sc.category === '新闻联播' || xwlbs.some(x => x.title === title0);
  if (isXwlb) { renderXwlbModal(title0); return; }

  const source = raw.source || sc.source || '';
  const pt = raw.publish_time || sc.publish_time || '';
  const cover = raw.cover || '';
  const story = raw.story || '';
  const impact = raw.impact || '';
  const cat = raw.category || sc.category || '';
  const sub = `<div class="mh-sub">
      ${source ? `<span class="src">${esc(source)}</span>` : ''}
      ${pt ? `<span>${esc(pt)}</span>` : ''}
      ${cat ? `<span class="tag">${esc(cat)}</span>` : ''}</div>`;
  const m = modalShell(esc(title0), sub);
  if (cover) m.insertAdjacentHTML('beforeend',
    `<img class="news-cover" src="${esc(cover)}" alt="" onerror="this.style.display='none'">`);
  if (story) {
    m.insertAdjacentHTML('beforeend', `<div class="sec"><div class="sec-t">全文</div><div class="news-body">${esc(story)}</div></div>`);
  } else {
    m.insertAdjacentHTML('beforeend', `<div class="sec"><div class="empty">该资讯暂无全文（可能来自新闻联播要目或仅提供摘要）</div></div>`);
  }
  if (impact) {
    m.insertAdjacentHTML('beforeend',
      `<div class="sec"><div class="sec-t">影响解读</div><div class="impact-box">${esc(impact)}</div></div>`);
  }
}

/* 新闻联播要目弹层（仅标题要目，无正文） */
function renderXwlbModal(clickedTitle) {
  const xwlbs = S.doc.xwlb_raw || [];
  const d = S.date;
  const sub = `<div class="mh-sub"><span class="src">新闻联播</span><span>${esc(d)}</span><span class="tag">央视要闻</span></div>`;
  const m = modalShell(esc(clickedTitle), sub);
  if (!xwlbs.length) {
    m.insertAdjacentHTML('beforeend', '<div class="sec"><div class="empty">当日暂无新闻联播要目</div></div>');
    return;
  }
  m.insertAdjacentHTML('beforeend', `
    <div class="sec"><div class="sec-t">新闻联播要目（当日 ${xwlbs.length} 条）</div>
      <div class="xwlb-list">${xwlbs.map((x, i) =>
        `<div class="xwlb-i ${x.title === clickedTitle ? 'on' : ''}">
           <span class="xn">${i + 1}</span><span class="xt">${esc(x.title)}</span></div>`).join('')}</div>
      <div class="src-note">新闻联播为央视每日要闻汇编，仅公布标题要目、无详细正文。以上为当日完整要目。</div>
    </div>`);
}

/* K线 SVG（蜡烛图） */
function capKline(arr, n) {
  if (arr.length <= n) return arr;
  const step = arr.length / n;
  const out = [];
  for (let i = 0; i < n; i++) out.push(arr[Math.floor(i * step)]);
  out.push(arr[arr.length - 1]);
  return out;
}

function klineSVG(kdata, period) {
  if (!kdata || !kdata.length) return '<div class="empty">暂无K线数据</div>';
  const arr = capKline(kdata, 150);
  const W = 700, H = 260, padL = 8, padR = 50, padT = 12, padB = 22;
  const lo = Math.min(...arr.map(d => d.l)), hi = Math.max(...arr.map(d => d.h));
  const rng = (hi - lo) || 1;
  const X = i => arr.length === 1 ? (padL + padR) / 2 : padL + i * (W - padL - padR) / (arr.length - 1);
  const Y = v => padT + (1 - (v - lo) / rng) * (H - padT - padB);
  let grid = '';
  const ticks = 4;
  for (let t = 0; t <= ticks; t++) {
    const val = lo + rng * t / ticks, y = Y(val).toFixed(1);
    grid += `<line x1="${padL}" y1="${y}" x2="${W - padR}" y2="${y}" stroke="#eef1f6"/>` +
      `<text x="${W - padR + 5}" y="${(+y + 3).toFixed(1)}">${val.toFixed(3)}</text>`;
  }
  const cw = Math.max(2, (W - padL - padR) / arr.length * 0.6);
  let candles = '';
  arr.forEach((d, i) => {
    const x = X(i), up = d.c >= d.o, col = up ? '#e0384e' : '#0f9d76';
    const yO = Y(d.o), yC = Y(d.c), yH = Y(d.h), yL = Y(d.l);
    const top = Math.min(yO, yC), bh = Math.max(1, Math.abs(yC - yO));
    candles += `<line x1="${x.toFixed(1)}" y1="${yH.toFixed(1)}" x2="${x.toFixed(1)}" y2="${yL.toFixed(1)}" stroke="${col}" stroke-width="1"/>` +
      `<rect x="${(x - cw / 2).toFixed(1)}" y="${top.toFixed(1)}" width="${cw.toFixed(1)}" height="${bh.toFixed(1)}" fill="${col}"/>`;
  });
  let xl = '';
  const step = Math.max(1, Math.floor(arr.length / 5));
  for (let i = 0; i < arr.length; i += step) {
    const lab = period === 'day' ? arr[i].d.slice(5) : arr[i].d;
    xl += `<text x="${X(i).toFixed(1)}" y="${H - 6}" text-anchor="middle">${esc(lab)}</text>`;
  }
  return `<svg class="kchart" viewBox="0 0 ${W} ${H}">${grid}${candles}${xl}</svg>`;
}

const STAGE_LABEL = { '1w': '近1周', '1m': '近1月', '3m': '近3月', '6m': '近6月', '1y': '近1年', '3y': '近3年', 'ytd': '今年以来', 'all': '成立以来' };

function openFund(code) {
  if (!code) return;
  if (fundCache[code]) { renderFundModal(fundCache[code]); return; }
  const m = modalShell('载入中…', '');
  m.insertAdjacentHTML('beforeend', '<div class="loading"><div class="spinner"></div><span>正在加载基金详情…</span></div>');
  getJSON(`data/funds/${code}.json`).then(doc => {
    fundCache[code] = doc;
    renderFundModal(doc);
  }).catch(() => {
    m.innerHTML = `<div class="modal-h"><div class="mh-t">未找到详情</div></div>
      <div class="sec"><div class="empty">该基金暂无离线详情文件。<br>请在本地端点击「刷新」生成后重试。</div></div>`;
  });
}

function renderFundModal(doc) {
  S._fundDoc = doc;
  const v = doc.valuation || {}, stage = doc.stage || {}, risk = doc.risk || {};
  const tops = doc.top_holdings || [];
  const navPct = Number(doc.nav_pct);
  const mtMap = { us: '美股', hk: '港股', ch: 'A股' };
  const sub = `<div class="mh-sub">
      <span class="tag">${esc(doc.sector || '—')}</span>
      <span>${esc(mtMap[doc.market_type] || doc.market_type || '—')}</span>
      <span class="tag ${cls(navPct)}">净值日涨跌 ${sign(navPct.toFixed(2))}%</span>
      <span class="refresh-one" id="fdRefresh" ${(S.cloud || S.live) ? '' : 'disabled title="本地服务未连接，无法实时刷新"'} onclick="fdRefreshClick()">刷新估值</span>
    </div>`;
  const m = modalShell(`${esc(doc.name)} <span style="font-size:13px;color:var(--ink3);font-weight:500">${esc(doc.code)}</span>`, sub);

  // 头部净值
  m.insertAdjacentHTML('beforeend', `
    <div class="fd-head">
      <div><div class="fd-name">单位净值</div><div class="fd-nav"><div class="v">${doc.nav ?? '—'}</div>
        <div class="d">${esc(doc.nav_date || '')}${doc.acc_nav ? ' · 累计 ' + doc.acc_nav : ''}</div></div></div>
      <div style="font-size:12.5px;color:var(--ink3);line-height:2">
        ${doc.rate ? `申购费率 ${esc(doc.rate)}<br>` : ''}
        ${doc.min_buy ? `起购 ${esc(doc.min_buy)} 元<br>` : ''}
        ${(doc.managers || []).length ? `经理 ${(doc.managers || []).map(x => esc(x.name)).join('、')}` : ''}
      </div>
    </div>`);

  // K线
  m.insertAdjacentHTML('beforeend', `
    <div class="sec"><div class="sec-t">净值K线</div>
      <div class="pbar" id="kperiod">
        <button data-p="day" class="on">日</button>
        <button data-p="week">周</button>
        <button data-p="month">月</button>
      </div>
      <div id="kchart">${klineSVG(doc.kline.day, 'day')}</div>
      <div class="klegend"><span><i style="background:#e0384e"></i>涨（收≥开）</span><span><i style="background:#0f9d76"></i>跌（收<开）</span>
        <span>共 ${doc.series_len || '—'} 个交易日数据</span></div>
    </div>`);

  // 估值指标
  const peTxt = v.pe != null ? v.pe.toFixed(2) : '—';
  const pbTxt = v.pb != null ? v.pb.toFixed(2) : '—';
  const metrics = [
    ['PE（市盈率）', peTxt, v.pe != null ? `覆盖 ${v.pe_coverage || 0}% · ${v.stock_count || 0} 只样本` : '样本不足'],
    ['PB（市净率）', pbTxt, v.pb != null ? `覆盖 ${v.pb_coverage || 0}%` : '样本不足'],
    ['最大回撤', (risk.max_drawdown != null ? risk.max_drawdown.toFixed(2) + '%' : '—'),
      risk.mdd_from ? `${risk.mdd_from} ~ ${risk.mdd_to}` : '近一年'],
    ['夏普比率', (risk.sharpe != null ? risk.sharpe.toFixed(2) : '—'), '风险调整收益'],
    ['年化波动率', (risk.volatility != null ? risk.volatility.toFixed(2) + '%' : '—'), '近一年'],
    ['年化收益', (risk.annualized != null ? sign(risk.annualized.toFixed(2)) + '%' : '—'),
      risk.sortino != null ? `索提诺 ${risk.sortino.toFixed(2)}` : ''],
  ];
  m.insertAdjacentHTML('beforeend', `
    <div class="sec"><div class="sec-t">估值与风险</div>
      <div class="metric-grid">${metrics.map(([l, val, s]) =>
        `<div class="metric"><div class="ml">${l}</div><div class="mv ${numCls(val)}">${val}</div><div class="ms">${esc(s)}</div></div>`).join('')}</div>
    </div>`);

  // 阶段收益
  const stageItems = Object.keys(STAGE_LABEL).filter(k => stage[k] != null)
    .map(k => `<div class="metric"><div class="ml">${STAGE_LABEL[k]}</div><div class="mv ${cls(stage[k])}">${sign(Number(stage[k]).toFixed(2))}%</div></div>`).join('');
  if (stageItems) m.insertAdjacentHTML('beforeend',
    `<div class="sec"><div class="sec-t">阶段收益</div><div class="metric-grid">${stageItems}</div></div>`);

  // 重仓股
  if (tops.length) {
    m.insertAdjacentHTML('beforeend', `
      <div class="sec"><div class="sec-t">前十大重仓股 <span style="font-weight:400;color:var(--ink3)">${esc(doc.holding_season || '')}</span></div>
        <div class="scroll-x"><table class="tbl hold-tbl"><thead><tr>
          <th>股票</th><th class="num">占净值</th><th class="num">PE</th><th class="num">PB</th><th class="num">日涨跌</th></tr></thead>
        <tbody>${tops.map(h => `
          <tr><td>${esc(h.name)}<div style="font-size:11px;color:var(--ink3)">${esc(h.code)}</div></td>
          <td class="num"><div class="pcell"><span class="pbar"><i style="width:${Math.min(100, h.weight || 0)}%"></i></span>${(h.weight || 0).toFixed(2)}%</div></td>
          <td class="num">${h.pe ? h.pe : '—'}</td>
          <td class="num">${h.pb ? h.pb : '—'}</td>
          <td class="num ${cls(h.pct)}">${h.pct != null ? sign(h.pct) + '%' : '—'}</td></tr>`).join('')}</tbody></table></div>
      </div>`);
  }

  // 资产配置
  const series = (doc.alloc && doc.alloc.series) || [];
  const allocRows = series.filter(s => s.yAxis === 0 && /占净比/.test(s.name)).map(s => {
    const val = s.data && s.data.length ? s.data[s.data.length - 1] : 0;
    return { name: s.name.replace('占净比', ''), val };
  }).filter(r => r.val > 0);
  if (allocRows.length) {
    const colors = ['#2563eb', '#0f9d76', '#d97706', '#7c3aed', '#0891b2'];
    m.insertAdjacentHTML('beforeend', `
      <div class="sec"><div class="sec-t">资产配置（最新季报）</div>
        ${allocRows.map((r, i) => `
          <div class="alloc-row"><span class="an">${esc(r.name)}</span>
            <span class="alloc-bar"><i style="width:${r.val}%;background:${colors[i % colors.length]}"></i></span>
            <span style="width:48px;text-align:right;font-variant-numeric:tabular-nums;font-size:12.5px">${r.val.toFixed(1)}%</span></div>`).join('')}
      </div>`);
  }

  // 估值来源说明
  let srcNote = '';
  if (v.source) srcNote += `估值来源：${esc(v.source)}`;
  if (v.parent_etf) srcNote += `（母基金 ${esc(v.parent_etf.name)} ${esc(v.parent_etf.code)}）`;
  if (doc.updated_at) srcNote += ` · 更新于 ${esc(doc.updated_at.replace('T', ' ').slice(0, 16))}`;
  if (srcNote) m.insertAdjacentHTML('beforeend', `<div class="src-note">${srcNote}。基金本身无市盈率，PE/PB 由前十大重仓股按权重穿透（调和加权）估算，仅供参考。</div>`);

  // 周期切换
  $('#kperiod').addEventListener('click', e => {
    const b = e.target.closest('button'); if (!b) return;
    document.querySelectorAll('#kperiod button').forEach(x => x.classList.remove('on'));
    b.classList.add('on');
    const p = b.dataset.p;
    $('#kchart').innerHTML = klineSVG(doc.kline[p], p);
  });
}

function fdRefreshClick() {
  const doc = S._fundDoc; if (!doc) return;
  if (S.cloud) { reloadFundStatic(doc.code); return; }
  if (!S.live) return;
  const btn = $('#fdRefresh'); if (!btn) return;
  btn.disabled = true; btn.textContent = '刷新中…';
  fetch(`${api('/api/fund')}/${doc.code}?mt=${encodeURIComponent(doc.market_type || 'ch')}`).then(r => r.ok ? r.json() : Promise.reject(r.status))
    .then(nd => {
      fundCache[doc.code] = nd;
      renderFundModal(nd);
      toast('估值已刷新');
    }).catch(e => {
      btn.disabled = false; btn.textContent = '刷新估值';
      toast('刷新失败：' + e, 'err');
    });
}

document.addEventListener('keydown', e => { if (e.key === 'Escape') closeModal(); });

/* ---------------- 交互 ---------------- */
function syncEye() {
  $('#btnEye').classList.toggle('off', !S.showMoney);
  $('#btnEye').title = S.showMoney ? '隐藏金额' : '显示金额';
}

$('#tabs').addEventListener('click', e => {
  const b = e.target.closest('.tab'); if (!b) return;
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  b.classList.add('active');
  S.view = b.dataset.view;
  render();
});

$('#dateSel').addEventListener('change', e => { loadDay(e.target.value); window.scrollTo({ top: 0 }); });

$('#prevDay').onclick = () => {
  const ds = S.index.dates.map(x => x.date), i = ds.indexOf(S.date);
  if (i < ds.length - 1) { $('#dateSel').value = ds[i + 1]; loadDay(ds[i + 1]); window.scrollTo({ top: 0 }); }
};
$('#nextDay').onclick = () => {
  const ds = S.index.dates.map(x => x.date), i = ds.indexOf(S.date);
  if (i > 0) { $('#dateSel').value = ds[i - 1]; loadDay(ds[i - 1]); window.scrollTo({ top: 0 }); }
};

$('#btnEye').onclick = () => {
  S.showMoney = !S.showMoney;
  localStorage.setItem('showMoney', S.showMoney ? '1' : '0');
  syncEye(); render();
};

$('#btnRefresh').onclick = async () => {
  if (S.cloud) { await reloadStatic(); toast('已重新加载云端最新数据'); return; }
  if (S.live) { await liveRefresh(); return; }
  // 静态快照模式：无可用后端。若已配置后端地址但不可达，提示检查；否则仅重载静态缓存。
  if (S.apiBase) {
    toast('已配置后端（' + S.apiBase + '）但无法连接，请确认 VPS 服务是否在运行。', 'warn');
  } else {
    toast('当前为静态快照（无后端）。实时刷新需本机或 VPS 后端运行。', 'warn');
  }
  S.index = null; S.repIndex = null; S.repDoc = null; fundCache = {};
  await boot();
};

async function liveRefresh() {
  $('#main').innerHTML = '<div class="loading"><div class="spinner"></div><span>正在调用后端接口刷新基金数据…</span></div>';
  try {
    const r = await fetch(api('/api/refresh/funds'), { method: 'POST' });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const j = await r.json().catch(() => ({}));
    S.index = null; S.repIndex = null; S.repDoc = null; fundCache = {};
    await boot();
    toast('基金数据已刷新' + (j.funds ? `：${j.funds} 只` : ''));
  } catch (e) {
    toast('接口刷新失败，已回退静态数据：' + e.message, 'warn');
    S.index = null; S.repIndex = null; S.repDoc = null; fundCache = {};
    await boot();
  }
}

async function detectApi() {
  try {
    const r = await fetch(api('/api/ping'), { method: 'GET' });
    const j = await r.json().catch(() => null);
    S.live = !!(r.ok && j && j.ok);
  } catch (e) { S.live = false; }
  const b = $('#btnRefresh');
  const pill = $('#livePill');
  if (b) {
    b.classList.toggle('live', !!S.live);
    b.title = S.live ? '通过后端接口实时刷新（养基宝）' : '当前无可用后端（静态快照）';
  }
  if (pill) {
    if (S.live) {
      pill.textContent = S.apiBase ? '● 实时模式（云端后端已连接）' : '● 实时模式（本机已连接）';
      pill.className = 'live-pill on';
    } else {
      pill.textContent = S.apiBase ? '○ 后端未连接（检查 VPS 服务）' : '○ 静态快照（实时刷新需后端）';
      pill.className = 'live-pill off';
    }
  }
}

/* ---------------- 云端模式辅助 ---------------- */
function setCloudPill() {
  const b = $('#btnRefresh'), pill = $('#livePill');
  if (b) { b.classList.add('live'); b.title = '云端定时自动刷新（每交易日约30分钟）；点击重新加载最新数据'; }
  if (pill) { pill.textContent = '● 云端自动刷新（每交易日约30分钟）'; pill.className = 'live-pill on'; }
}

async function reloadStatic() {
  S.index = null; S.repIndex = null; S.repDoc = null; fundCache = {};
  $('#main').innerHTML = '<div class="loading"><div class="spinner"></div><span>正在重新加载云端最新数据…</span></div>';
  await boot();
}

function reloadFundStatic(code) {
  const btn = $('#fdRefresh'); if (!btn) return;
  btn.disabled = true; btn.textContent = '刷新中…';
  getJSON(`data/funds/${code}.json`).then(doc => {
    fundCache[code] = doc; renderFundModal(doc); toast('已重载最新估值');
  }).catch(e => { btn.disabled = false; btn.textContent = '刷新估值'; toast('重载失败：' + e.message, 'err'); });
}

/* PWA：云端模式关闭 SW，保证每次都拿到最新数据；本机模式保留离线缓存 */
async function init() {
  let cfg = {};
  try {
    const r = await fetch('data/backend.json?t=' + Date.now());
    if (r.ok) cfg = await r.json();
  } catch (e) {}
  if (cfg.mode === 'github-pages') {
    S.cloud = true;
    // 云端模式：彻底禁用 SW，避免外壳(index.html/app.js)被缓存导致页面卡在旧版
    if ('serviceWorker' in navigator) {
      navigator.serviceWorker.getRegistrations().then(rs => rs.forEach(r => r.unregister())).catch(() => { });
    }
  } else {
    if (cfg.apiBase) S.apiBase = String(cfg.apiBase).replace(/\/+$/, '');
    if ('serviceWorker' in navigator) {
      window.addEventListener('load', () => navigator.serviceWorker.register('sw.js').catch(() => { }));
    }
  }
  boot();
}

init();
