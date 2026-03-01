# Grafana Dashboard 自動載入設定

本文件說明如何透過 ConfigMap 自動載入 Grafana Dashboard。

## 架構說明

Grafana Dashboard 自動載入使用以下三個 ConfigMap：

1. **grafana-dashboard-provider** - 告訴 Grafana 從哪裡載入儀表板
2. **grafana-dashboards** - 包含實際的儀表板 JSON 定義
3. **grafana-datasources** - 配置 Prometheus 資料源

## 已部署的儀表板

### 1. GPU 與租戶監控面板
- **檔案**: `grafana-dashboard-gpu-monitoring.json`
- **用途**: 監控實際的 GPU 指標（來自 mock-exporter）
- **包含面板**:
  - GPU 使用率 (%)
  - GPU 功耗 (W)
  - GPU 顯存使用 (MB)
  - GPU 降頻狀態
  - 平均 GPU 使用率（按租戶）
  - 總功耗（按租戶）

### 2. AI 服務監控面板
- **檔案**: `grafana-dashboard-ai-monitoring.json`
- **用途**: 監控 AI 服務指標（需要應用程式實作）
- **包含面板**:
  - LLM 請求總數
  - Prompt Injection 攻擊攔截
  - 請求處理時間分佈
  - 併發請求數
  - GPU 使用率
  - 異常檢測告警
  - Token 處理統計
  - 系統資源使用率

## 部署步驟

### 1. 部署 Dashboard Provider

```bash
kubectl apply -f grafana-dashboard-provider.yaml
```

這會創建一個 ConfigMap，告訴 Grafana 從 `/var/lib/grafana/dashboards` 目錄載入儀表板。

### 2. 部署 Dashboard 定義

```bash
kubectl apply -f grafana-dashboards-configmap.yaml
```

這會創建包含兩個儀表板 JSON 定義的 ConfigMap。

### 3. 更新 Grafana Deployment

```bash
kubectl apply -f monitoring-stack.yaml
kubectl rollout restart deployment grafana -n monitoring
```

這會重啟 Grafana，讓它載入新的儀表板。

### 4. 驗證部署

```bash
./verify-grafana-dashboards.sh
```

或手動檢查：

```bash
# 檢查 ConfigMaps
kubectl get configmap -n monitoring | grep grafana

# 檢查 Grafana Pod
kubectl get pods -n monitoring -l app=grafana

# 檢查日誌
kubectl logs -n monitoring -l app=grafana | grep dashboard
```

## 訪問 Grafana

1. 訪問 http://localhost:3000
2. 登入（帳號: `admin` / 密碼: `admin123`）
3. 點選左側選單的 "Dashboards"
4. 你會看到兩個自動載入的儀表板

## 新增自訂儀表板

### 方法 1: 透過 UI 創建後匯出

1. 在 Grafana UI 中創建儀表板
2. 點選右上角的 "Share" → "Export" → "Save to file"
3. 將 JSON 內容加入到 `grafana-dashboards-configmap.yaml`

### 方法 2: 直接編輯 ConfigMap

1. 編輯 `grafana-dashboards-configmap.yaml`
2. 在 `data:` 區塊加入新的儀表板：

```yaml
data:
  my-custom-dashboard.json: |-
    {
      "id": null,
      "title": "我的自訂儀表板",
      ...
    }
```

3. 應用變更：

```bash
kubectl apply -f grafana-dashboards-configmap.yaml
kubectl rollout restart deployment grafana -n monitoring
```

## 修改現有儀表板

### 更新 GPU 監控儀表板

1. 編輯 `grafana-dashboard-gpu-monitoring.json`
2. 更新 ConfigMap：

```bash
# 重新生成 ConfigMap
kubectl create configmap grafana-dashboards \
  --from-file=gpu-monitoring.json=grafana-dashboard-gpu-monitoring.json \
  --from-file=ai-monitoring.json=grafana-dashboard-ai-monitoring.json \
  -n monitoring \
  --dry-run=client -o yaml | kubectl apply -f -

# 重啟 Grafana
kubectl rollout restart deployment grafana -n monitoring
```

### 更新 AI 監控儀表板

同上，編輯 `grafana-dashboard-ai-monitoring.json` 後重新應用。

## 故障排除

### 儀表板沒有出現

1. 檢查 ConfigMap 是否正確創建：
```bash
kubectl get configmap grafana-dashboards -n monitoring -o yaml
```

2. 檢查 Grafana Pod 的 Volume 掛載：
```bash
kubectl describe pod -n monitoring -l app=grafana | grep -A 10 "Volumes:"
```

3. 檢查 Grafana 日誌：
```bash
kubectl logs -n monitoring -l app=grafana | grep -i dashboard
```

### 儀表板顯示 "No data"

1. 檢查 Prometheus 是否正常運作：
```bash
kubectl get pods -n monitoring -l app=prometheus
```

2. 檢查 Prometheus 是否有抓取到指標：
```bash
kubectl port-forward -n monitoring svc/prometheus 9090:9090
# 訪問 http://localhost:9090/targets
```

3. 確認 mock-exporter 正在運行：
```bash
kubectl get pods -n monitoring -l app=mock-exporter
kubectl logs -n monitoring -l app=mock-exporter
```

### JSON 格式錯誤

如果 ConfigMap 應用失敗，檢查 JSON 格式：

```bash
# 驗證 JSON 格式
cat grafana-dashboard-gpu-monitoring.json | jq .
cat grafana-dashboard-ai-monitoring.json | jq .
```

## 進階配置

### 設定預設首頁儀表板

在 `monitoring-stack.yaml` 的 Grafana Deployment 中：

```yaml
env:
  - name: GF_DASHBOARDS_DEFAULT_HOME_DASHBOARD_PATH
    value: "/var/lib/grafana/dashboards/gpu-monitoring.json"
```

### 設定自動重新整理

在儀表板 JSON 中加入：

```json
{
  "refresh": "5s",
  "time": {
    "from": "now-15m",
    "to": "now"
  }
}
```

### 設定告警

Grafana 可以基於儀表板面板設定告警。需要額外配置：

1. 設定通知頻道（Email、Slack 等）
2. 在面板中加入告警規則
3. 配置告警條件和閾值

## 相關檔案

- `grafana-dashboard-provider.yaml` - Dashboard provider 配置
- `grafana-dashboards-configmap.yaml` - Dashboard 定義 ConfigMap
- `grafana-dashboard-gpu-monitoring.json` - GPU 監控儀表板
- `grafana-dashboard-ai-monitoring.json` - AI 服務監控儀表板
- `monitoring-stack.yaml` - 完整監控堆疊（包含 Grafana）
- `verify-grafana-dashboards.sh` - 驗證腳本

## 參考資源

- [Grafana Provisioning 文檔](https://grafana.com/docs/grafana/latest/administration/provisioning/)
- [Grafana Dashboard JSON 模型](https://grafana.com/docs/grafana/latest/dashboards/json-model/)
- [Prometheus 查詢語法](https://prometheus.io/docs/prometheus/latest/querying/basics/)
