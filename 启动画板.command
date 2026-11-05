#!/bin/sh
# 双击启动网页画板：开本地服务并在浏览器打开
cd "$(dirname "$0")"
(sleep 1 && open "http://localhost:5178") &
exec python3 server.py
