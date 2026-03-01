# 快速參考卡 - Grafana Dashboard 自動載入

## 🚀 一鍵部署

```bash
# 部署所有配置
kubectl apply -f grafana-dashboard-provider.yaml
kubectl apply -f grafana-dashboards-configmap.yaml
kubectl apply -f monitoring-stack.yaml

# 重啟 Grafana
kubectl rollout restart deployment grafana -n monitoring
```

## 📊 訪問 Grafana

- **URL**: http://localhost:3000
- **帳號**: admin
- **密碼**: admin123

## 📈 可用的儀表板

1. **GPU 與租戶監控面板** ✅ 立即可用
   - GPU 使用率、功耗、顯存
   - 按租戶分組統計

2. **AI 服務監控面板** ⚠️ 需要實作指標
   - LLM 請求、攻擊攔截、處理時間

## 🔍 快速驗證

```bash
./verify-grafana-dashboards.sh
```

## 📝 新增儀表板

### 方法 1: UI 匯出
1. 在 Grafana 創建儀表板
2. Share → Export → Save to file
3. 加入到 `grafana-dashboards-configmap.yaml`
4. 應用並重啟

### 方法 2: 直接編輯
```bash
# 編輯 ConfigMap
vim grafana-dashboards-configmap.yaml

# 應用變更
kubectl apply -f grafana-dashboards-configmap.yaml
kubectl rollout restart deployment grafana -n monitoring
```

## 🛠️ 常用命令

```bash
# 查看 ConfigMaps
kubectl get configmap -n monitoring | grep grafana

# 查看 Grafana Pod
kubectl get pods -n monitoring -l app=grafana

# 查看 Grafana 日誌
kubectl logs -n monitoring -l app=grafana | grep dashboard

# 重啟 Grafana
kubectl rollout restart deployment grafana -n monitoring

# Port-forward Prometheus
kubectl port-forward -n monitoring svc/prometheus 9090:9090

# Port-forward Grafana (如果 NodePort 不可用)
kubectl port-forward -n monitoring svc/grafana 3000:3000
```

## 🐛 故障排除

### 儀表板沒出現
```bash
# 檢查 Volume 掛載
kubectl describe pod -n monitoring -l app=grafana | grep -A 10 "Volumes:"

# 檢查 provisioning 日誌
kubectl logs -n monitoring -l app=grafana | grep provisioning
```

### 顯示 "No data"
```bash
# 檢查 Prometheus targets
kubectl port-forward -n monitoring svc/prometheus 9090:9090
# 訪問 http://localhost:9090/targets

# 檢查 mock-exporter
kubectl logs -n monitoring -l app=mock-exporter
```

## 📁 重要檔案

| 檔案 | 用途 |
|------|------|
| `grafana-dashboard-provider.yaml` | Dashboard 載入配置 |
| `grafana-dashboards-configmap.yaml` | Dashboard 定義 |
| `grafana-dashboard-gpu-monitoring.json` | GPU 監控儀表板 |
| `grafana-dashboard-ai-monitoring.json` | AI 監控儀表板 |
| `monitoring-stack.yaml` | 完整監控堆疊 |

## 📚 詳細文檔

- `GRAFANA_DASHBOARD_SETUP.md` - 完整設定指南
- `DASHBOARD_SUMMARY.md` - 實作總結
- `k8s-deployment-guide.md` - K8s 部署指南

## ✅ 檢查清單

- [ ] ConfigMaps 已創建
- [ ] Grafana Pod 正在運行
- [ ] Volume 正確掛載
- [ ] 可以訪問 Grafana UI
- [ ] 儀表板出現在列表中
- [ ] GPU 監控面板顯示數據
