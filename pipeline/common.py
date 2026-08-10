# -*- coding: utf-8 -*-
"""公共配置与工具。所有管道脚本共用。"""
import os, sys, json, time, hashlib, datetime as dt

# --- Windows 控制台编码兜底 ---
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, 'data')
DAILY_DIR = os.path.join(DATA_DIR, 'daily')
REPORT_DIR = os.path.join(DATA_DIR, 'reports')
DIST_DIR = os.path.join(ROOT, 'dist')
DIST_DATA = os.path.join(DIST_DIR, 'data')
DIST_FUNDS = os.path.join(DIST_DATA, 'funds')

for _d in (DAILY_DIR, REPORT_DIR, DIST_DATA):
    os.makedirs(_d, exist_ok=True)

# --- 养基宝 ---
YJB_SECRET = os.environ.get('YJB_SIGN_SECRET', 'YxmKSrQR4uoJ5lOoWIhcbd7SlUEh9OOc')
YJB_PLUG = 'http://browser-plug-api.yangjibao.com'
YJB_APP = 'https://app-api.yangjibao.com'
YJB_TOKEN_FILE = os.path.expanduser('~/.yjb_token.json')
# 云端部署时，token 可放在项目根目录（与 server.py 同目录），或注入环境变量 YJB_TOKEN
YJB_TOKEN_LOCAL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'yjb_token.json')

NEWS_API = 'https://api.cjiot.cc/api/v1'

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 ' \
     '(KHTML, like Gecko) Chrome/124.0 Safari/537.36'


def today_str():
    return dt.date.today().isoformat()


def load_yjb_token():
    # 优先级：环境变量 > 项目根目录 yjb_token.json > 用户家目录（本机）
    env = os.environ.get('YJB_TOKEN')
    if env:
        return env.strip()
    for path in (YJB_TOKEN_LOCAL, YJB_TOKEN_FILE):
        if os.path.exists(path):
            try:
                with open(path, encoding='utf-8') as f:
                    tok = json.load(f).get('token')
                    if tok:
                        return tok
            except Exception:
                continue
    return None


def yjb_headers(path, token):
    """browser-plug-api 签名头。path 不含 query string。"""
    sign_path = path.split('?')[0]
    t = int(time.time())
    s = hashlib.md5(('' + sign_path + token + str(t) + YJB_SECRET).encode()).hexdigest()
    return {'Request-Time': str(t), 'Request-Sign': s,
            'Authorization': token, 'User-Agent': UA}


def read_json(path, default=None):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return default


def write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def log(msg):
    print(f'[{dt.datetime.now():%H:%M:%S}] {msg}', flush=True)


def safe_float(v, d=0.0):
    try:
        if v in (None, '', '-'):
            return d
        return float(v)
    except (TypeError, ValueError):
        return d
