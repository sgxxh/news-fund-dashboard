#!/usr/bin/env bash
# 云主机 / VPS 一键启动脚本（Linux）
set -e
cd "$(dirname "$0")"

echo "[1/2] 安装依赖…"
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt

echo "[2/2] 启动工作台（端口 8787，0.0.0.0）…"
exec python3 server.py
