# -*- coding: utf-8 -*-
"""本地工作台服务：静态托管 dist/ + 实时刷新接口。

- 静态托管 dist/（前端、data/），供 PC 浏览器与手机同网访问。
- /api/ping              健康检查，前端据此判断是否能实时刷新。
- POST /api/refresh/funds 重新从养基宝拉取持仓 + 生成基金行情详情（K线/估值）。
- POST /api/refresh/news  重新采集当日新闻并重建分析。
- GET  /api/fund/{code}   按需实时生成单只基金的详情档案。

基金刷新依赖本机养基宝登录态（~/.yjb_token.json），因此只能在本机运行；
云端部署的静态版无 /api 路由，前端会自动降级为静态缓存刷新。
"""
import os, sys, json, mimetypes, datetime as dt, threading
from http.server import HTTPServer, BaseHTTPRequestHandler

ROOT = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.join(ROOT, 'dist')
PIPE = os.path.join(ROOT, 'pipeline')
if PIPE not in sys.path:
    sys.path.insert(0, PIPE)

PORT = int(os.environ.get('PORT', '8787'))
HOST = os.environ.get('HOST', '0.0.0.0')

_imports = {}
def _pipeline():
    """基金相关只需 common / fetch_funds / fetch_quote，避免触发 jieba。"""
    if 'fetch_quote' not in _imports:
        import common
        import fetch_funds, fetch_quote
        _imports.update(common=common, fetch_funds=fetch_funds, fetch_quote=fetch_quote)
    return _imports


def _pipeline_full():
    """新闻/全量刷新才需要 run_daily（会引入 jieba）。"""
    _pipeline()
    if 'run_daily' not in _imports:
        import run_daily, aggregate
        _imports.update(run_daily=run_daily, aggregate=aggregate)
    return _imports


def refresh_funds():
    m = _pipeline_full()
    common = m['common']; fetch_funds = m['fetch_funds']
    fetch_quote = m['fetch_quote']; run_daily = m['run_daily']
    token = common.load_yjb_token()
    if not token:
        return {'ok': False, 'reason': 'NO_TOKEN'}
    today = common.today_str()
    fp = fetch_funds.collect(today)
    if not fp.get('ok'):
        return {'ok': False, 'reason': fp.get('reason', 'FAIL')}
    hs = [h for h in fp.get('holdings', []) if h.get('code') and h.get('money', 0) >= 50]
    fetch_quote.collect_all(hs, common.DIST_FUNDS)
    # 把最新快照写回当日日档案，并同步到 dist
    from common import DAILY_DIR, read_json, write_json
    path = os.path.join(DAILY_DIR, f'{today}.json')
    doc = read_json(path, {}) or {}
    doc['funds'] = {
        'ok': True, 'reason': '', 'summary': fp.get('summary', {}),
        'holdings': fp.get('holdings', []), 'index': fp.get('index', []),
    }
    write_json(path, doc)
    run_daily.build_dist(today)
    return {'ok': True, 'date': today, 'funds': len(hs),
            'total_money': (fp.get('summary') or {}).get('total_money')}


def refresh_news():
    m = _pipeline_full()
    common = m['common']; run_daily = m['run_daily']; aggregate = m['aggregate']
    today = common.today_str()
    # 仅补当日新闻（不回补历史）
    run_daily.build_day(today, session='refresh')
    aggregate.build_all()
    run_daily.build_dist(today)
    return {'ok': True, 'date': today}


def gen_fund(code, market_type=''):
    m = _pipeline()
    fetch_quote = m['fetch_quote']
    return fetch_quote.collect_fund(code, market_type=market_type or 'ch')


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype='application/json; charset=utf-8', extra=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False)
        data = body.encode('utf-8') if isinstance(body, str) else body
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Access-Control-Allow-Origin', '*')
        if extra:
            for k, v in extra.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _serve_static(self):
        url = self.path.split('?', 1)[0]
        if url == '/':
            url = '/index.html'
        # 防目录穿越
        rel = url.lstrip('/').replace('\\', '/')
        full = os.path.normpath(os.path.join(DIST, rel))
        if not full.startswith(DIST):
            self._send(403, {'ok': False, 'error': 'forbidden'})
            return
        if os.path.isdir(full):
            full = os.path.join(full, 'index.html')
        if not os.path.exists(full):
            # SPA 兜底：未知路径回 index.html（不含 /api）
            self._send(404, {'ok': False, 'error': 'not found'})
            return
        ctype, _ = mimetypes.guess_type(full)
        ctype = ctype or 'application/octet-stream'
        # data/ 下的数据文件禁止缓存，保证刷新即时生效
        nocache = url.startswith('/data/') or url.startswith('/api/')
        with open(full, 'rb') as f:
            data = f.read()
        self.send_response(200)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Access-Control-Allow-Origin', '*')
        if nocache:
            self.send_header('Cache-Control', 'no-store')
        else:
            self.send_header('Cache-Control', 'public, max-age=300')
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        # 跨域预检（云端前端 → VPS 后端）
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.send_header('Access-Control-Max-Age', '86400')
        self.end_headers()

    def do_GET(self):
        p = self.path.split('?', 1)[0]
        if p == '/api/ping':
            self._send(200, {'ok': True, 'ts': dt.datetime.now().isoformat(timespec='seconds')})
            return
        if p.startswith('/api/fund/'):
            code = p.split('/')[-1].strip()
            mt = ''
            if '?' in self.path:
                from urllib.parse import parse_qs
                mt = parse_qs(self.path.split('?', 1)[1]).get('mt', [''])[0]
            try:
                self._send(200, gen_fund(code, mt))
            except Exception as e:
                self._send(500, {'ok': False, 'error': str(e)})
            return
        self._serve_static()

    def do_POST(self):
        p = self.path.split('?', 1)[0]
        length = int(self.headers.get('Content-Length', 0) or 0)
        if length:
            self.rfile.read(length)  # 丢弃 body
        if p == '/api/ping':
            self._send(200, {'ok': True})
            return
        if p == '/api/refresh/funds':
            try:
                self._send(200, refresh_funds())
            except Exception as e:
                self._send(500, {'ok': False, 'error': str(e)})
            return
        if p == '/api/refresh/news':
            try:
                self._send(200, refresh_news())
            except Exception as e:
                self._send(500, {'ok': False, 'error': str(e)})
            return
        self._send(404, {'ok': False, 'error': 'unknown endpoint'})


def run():
    srv = HTTPServer((HOST, PORT), H)
    print(f'工作台已启动： http://{HOST}:{PORT}  （云部署请开放 {PORT} 端口并做反向代理/域名）')
    print('按 Ctrl+C 停止。')
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print('\n已停止。')


if __name__ == '__main__':
    run()
