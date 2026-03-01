# 為了節省資源 (12GB RAM 考量)，使用 python:3.9-alpine 這種極小映像檔
FROM python:3.9-alpine

# 設定工作目錄
WORKDIR /app

# 安裝需要的 Python 套件 (requests 與 prometheus_client)
# Alpine 預設沒有編譯工具，但這兩個套件是純 Python 的，可以直接裝
RUN pip install --no-cache-dir requests prometheus_client

# 將 Python 腳本複製進去
COPY mock_dcgm.py /app/mock_dcgm.py

# 暴露 Prometheus 抓取用的 Port
EXPOSE 9400

# 設定環境變數的預設值 (確保即便沒傳進來也不會掛掉)
ENV PYTHONUNBUFFERED=1
ENV TENANT_ID="default-tenant"

# 啟動命令
CMD ["python", "mock_dcgm.py"]
