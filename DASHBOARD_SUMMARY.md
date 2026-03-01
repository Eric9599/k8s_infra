# Grafana Dashboard 自動載入 - 實作總結

## 已完成的工作

✅ **創建了 Dashboard Provider ConfigMap**
- 檔案: `grafana-dashboard-provider.yaml`
- 用途: 告訴 Grafana 從哪裡自動載入儀表板

✅ **創建了兩個完整的儀表板**
1. **GPU 與租戶監控面板** (`grafana-dashboard-gpu-monitoring.json`)
   - 使用實際的 mock-exporter 指標
   - 6 個監控面板（GPU 使用率、功耗、顯存等）
   
2. **AI 服務監控面板** (`grafana-dashboard-ai-monitoring.json`)
   - 8 個監控面板（請求數、攻擊攔截、處理時間等）
   - 需要應用程式實作相應的 Prometheus 指標

✅ **創建了 Dashboard ConfigMap**
- 檔案: `grafana-dashboards-configmap.yaml`
- 包含兩個儀表板的完整 JSON 定義

✅ **更新了 Grafana Deployment**
- 修改 `monitoring-stack.yaml`
- 加入 dashboard provider 的 volume 掛載
- 配置自動載入機制

✅ **部署並驗證**
- 所有 ConfigMap 已成功創建
- Grafana 已重啟並載入儀表板
- Volume 掛載正確

✅ **創建了驗證腳本**
- 檔案: `verify-grafana-dashboards.sh`
- 可快速檢查部署狀態

✅ **創建了完整文檔**
- `GRAFANA_DASHBOARD_SETUP.md` - 詳細設定指南
- 包含故障排除和進階配置

## 如何使用

### 快速開始

```bash
# 1. 部署所有配置
kubectl apply -f grafana-dashboard-provider.yaml
kubectl apply -f grafana-dashboards-configmap.yaml
kubectl apply -f monitoring-stack.yaml

# 2. 重啟 Grafana
kubectl rollout restart deployment grafana -n monitoring

# 3. 等待就緒
kubectl wait --for=condition=ready pod -l app=grafana -n monitoring --timeout=120s

# 4. 驗證
./verify-grafana-dashboards.sh
```

### 訪問儀表板

1. 訪問 http://localhost:3000
2. 登入（admin / admin123）
3. 點選 "Dashboards"
4. 選擇儀表板：
   - **GPU 與租戶監控面板** - 立即可用，顯示實際 GPU 指標
   - **AI 服務監控面板** - 需要應用程式實作指標

## 架構說明

```
┌────────────────────────────────────────────────────────┐
│                    Grafana Pod                         │
│                                                        │
│  ┌──────────────────────────────────────────────────┐  │
│  │  /etc/grafana/provisioning/dashboards/           │  │
│  │  ├── dashboards.yaml (from provider ConfigMap)   │  │
│  │  └── (告訴 Grafana 從哪裡載入)                     │  │
│  └──────────────────────────────────────────────────┘  │
│                          │                             │
│                          ▼                             │
│  ┌──────────────────────────────────────────────────┐  │
│  │  /var/lib/grafana/dashboards/                    │  │
│  │  ├── gpu-monitoring.json (from dashboards CM)    │  │
│  │  └── ai-monitoring.json (from dashboards CM)     │  │
│  └──────────────────────────────────────────────────┘  │
│                          │                             │
│                          ▼                             │
│  ┌──────────────────────────────────────────────────┐  │
│  │  /etc/grafana/provisioning/datasources/          │  │
│  │  └── datasources.yaml (Prometheus 連線)           │  │
│  └──────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────┘
                          │
                          ▼
              ┌───────────────────────┐
              │   Prometheus          │
              │   (收集指標)           │
              └───────────────────────┘
                          │
                          ▼
              ┌───────────────────────┐
              │   Mock Exporter       │
              │   (產生 GPU 指標)      │
              └───────────────────────┘
```

## 目前可用的指標

### 來自 Mock Exporter (實際可用)

- `DCGM_FI_DEV_GPU_UTIL` - GPU 使用率 (%)
- `DCGM_FI_DEV_POWER_USAGE` - GPU 功耗 (W)
- `DCGM_FI_DEV_FB_USED` - GPU 顯存使用 (MB)
- `DCGM_ST_HW_SLOWDOWN` - GPU 降頻狀態 (0/1)

### 需要實作的指標 (AI 監控面板)

- `llm_requests_total` - LLM 請求總數
- `llm_prompt_injection_detected_total` - Prompt injection 攔截
- `llm_request_duration_seconds` - 請求處理時間
- `llm_concurrent_requests` - 併發請求數
- `llm_gpu_utilization_percent` - GPU 使用率
- `anomaly_detection_alerts_total` - 異常告警
- `llm_tokens_processed_total` - Token 處理統計
- `system_cpu_usage_percent` - CPU 使用率
- `system_memory_usage_bytes` - 記憶體使用

## 下一步建議

### 1. 實作 AI 服務指標

在你的 FastAPI 或 LiteLLM 應用中加入 Prometheus 指標：

```python
from prometheus_client import Counter, Histogram, Gauge

# 定義指標
llm_requests = Counter('llm_requests_total', 'Total requests', ['tenant'])
llm_duration = Histogram('llm_request_duration_seconds', 'Request duration')

# 使用指標
@app.post("/chat")
async def chat(request: ChatRequest):
    llm_requests.labels(tenant=request.tenant).inc()
    with llm_duration.time():
        # 處理請求
        ...
```

### 2. 配置告警規則

在 Grafana 中設定告警：
- GPU 使用率超過 90%
- GPU 降頻事件
- 請求處理時間過長
- Prompt injection 攻擊頻繁

### 3. 整合更多資料源

- 加入 Loki 收集日誌
- 加入 Tempo 追蹤分散式請求
- 整合 Kubernetes 事件

### 4. 優化儀表板

- 加入變數選擇器（租戶、時間範圍）
- 加入表格視圖顯示詳細數據
- 加入連結跳轉到相關面板

## 檔案清單

```
.
├── grafana-dashboard-provider.yaml          # Dashboard provider 配置
├── grafana-dashboards-configmap.yaml        # Dashboard 定義 (自動生成)
├── grafana-dashboard-gpu-monitoring.json    # GPU 監控儀表板
├── grafana-dashboard-ai-monitoring.json     # AI 監控儀表板
├── monitoring-stack.yaml                    # 監控堆疊 (已更新)
├── verify-grafana-dashboards.sh             # 驗證腳本
├── GRAFANA_DASHBOARD_SETUP.md               # 詳細設定指南
└── DASHBOARD_SUMMARY.md                     # 本文件
```

## 常見問題

### Q: 為什麼儀表板沒有自動出現？

A: 檢查以下幾點：
1. ConfigMap 是否正確創建
2. Grafana Pod 是否重啟
3. Volume 是否正確掛載
4. 查看 Grafana 日誌

### Q: 如何新增自訂儀表板？

A: 兩種方式：
1. 在 UI 中創建後匯出 JSON，加入 ConfigMap
2. 直接編輯 `grafana-dashboards-configmap.yaml`

### Q: 儀表板顯示 "No data"？

A: 檢查：
1. Prometheus 是否正常運作
2. 指標是否存在（訪問 Prometheus UI）
3. 查詢語法是否正確

### Q: 如何更新現有儀表板？

A: 
1. 編輯對應的 JSON 檔案
2. 重新生成 ConfigMap
3. 重啟 Grafana

## 成功標準

✅ Grafana 啟動時自動載入儀表板
✅ 不需要手動匯入
✅ GPU 監控面板顯示實際數據
✅ 可以輕鬆新增或修改儀表板
✅ 配置可以版本控制

## 總結

透過 ConfigMap 自動載入 Grafana Dashboard 的功能已完全實作並測試成功。現在你可以：

1. ✅ 自動載入預定義的儀表板
2. ✅ 監控實際的 GPU 指標
3. ✅ 輕鬆新增或修改儀表板
4. ✅ 將儀表板配置納入版本控制
5. ✅ 快速部署到新環境

所有配置檔案都已準備好，可以直接使用或根據需求調整。
