FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 养基宝 token：优先读环境变量 YJB_TOKEN，
# 否则放本项目根目录的 yjb_token.json（内容 {"token": "..."}）
ENV HOST=0.0.0.0 PORT=8787

EXPOSE 8787

CMD ["python", "server.py"]
