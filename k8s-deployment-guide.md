# Kubernetes 多租戶 AI 平台部署指南

本指南提供完整的 Kubernetes 集群部署步驟，包含 Cilium CNI、LiteLLM Gateway、監控系統和 Harbor 映像倉庫。

## 前置需求

- Docker Desktop 或 OrbStack
- Kind (Kubernetes in Docker)
- Helm 3.x
- kubectl

## 架構概覽

- **CNI**: Cilium (替代 kube-proxy，提供網路策略)
- **AI Gateway**: LiteLLM (統一 LLM API 介面)
- **監控**: Prometheus + Grafana
- **映像倉庫**: Harbor
- **租戶隔離**: 3 個租戶 namespace (company-a, company-b, company-c)

---

## 步驟 1: 建立 Kind 集群

```bash
# 使用自訂配置建立集群（禁用預設 CNI，使用 Cilium）
kind create cluster --name 2504-cluster --config kind-config.yaml
```

**驗證集群**:
```bash
kubectl cluster-info
kubectl get nodes
```

---

## 步驟 2: 安裝 Cilium CNI

```bash
# 添加 Cilium Helm repo
helm repo add cilium https://helm.cilium.io/
helm repo update

# 安裝 Cilium（使用自訂配置）
helm install cilium cilium/cilium \
  --namespace kube-system \
  --values cilium-values.yaml
```

**驗證 Cilium**:
```bash
# 等待所有 Pod 就緒
kubectl wait --for=condition=ready pod -l k8s-app=cilium -n kube-system --timeout=300s

# 檢查 Cilium 狀態
kubectl get pods -n kube-system -l k8s-app=cilium
```

---

## 步驟 3: 配置 Cilium L2 網路

```bash
# 部署 LoadBalancer IP 池和 L2 宣告策略
kubectl apply -f cilium-l2-config.yaml
```

**驗證**:
```bash
kubectl get ciliumloadbalancerippool
kubectl get ciliuml2announcementpolicy
```

---

## 步驟 4: 建立優先級類別

```bash
# 為租戶定義資源優先級（Premium vs Free）
kubectl apply -f priority-classes.yaml
```

**驗證**:
```bash
kubectl get priorityclasses
```

---

## 步驟 5: 部署 LiteLLM Gateway 堆疊

```bash
# 部署 Redis、PostgreSQL 和 LiteLLM Gateway
kubectl apply -f litellm-stack.yaml
```

**等待服務就緒**:
```bash
kubectl wait --for=condition=ready pod -l app=litellm-gateway -n ai-system --timeout=300s
```

**檢查 LoadBalancer IP**:
```bash
kubectl get svc -n ai-system litellm
```

**測試 LiteLLM API**:
```bash
# 取得 LoadBalancer IP
LITELLM_IP=$(kubectl get svc -n ai-system litellm -o jsonpath='{.status.loadBalancer.ingress[0].ip}')

# 測試健康檢查
curl http://$LITELLM_IP:4000/health
```

---

## 步驟 6: 建立租戶 Namespace

```bash
# 建立三個租戶的 namespace
kubectl create namespace tenant-company-a
kubectl create namespace tenant-company-b
kubectl create namespace tenant-company-c
```

---

## 步驟 7: 部署 Cilium 安全策略

```bash
# 套用網路隔離和安全策略
kubectl apply -f cilium-security-policies.yaml
```

**驗證策略**:
```bash
kubectl get ciliumnetworkpolicies -A
```

---

## 步驟 8: 部署監控堆疊

```bash
# 部署 Prometheus 和 Grafana
kubectl apply -f monitoring-stack.yaml
```

**等待監控服務就緒**:
```bash
kubectl wait --for=condition=ready pod -l app=prometheus -n monitoring --timeout=300s
kubectl wait --for=condition=ready pod -l app=grafana -n monitoring --timeout=300s
```

**訪問 Grafana**:
```bash
# Grafana 已配置 NodePort 30000，映射到本機 3000
# 直接訪問: http://localhost:3000
# 帳號: admin
# 密碼: admin123
```

---

## 步驟 9: 建置並部署 Mock Exporter

Mock Exporter 用於模擬 GPU 指標，供 Prometheus 抓取。

### 9.1 建置 Docker 映像

```bash
# 在 mock-exporter 目錄建置映像
docker build -t mock-exporter:latest ./mock-exporter
```

### 9.2 載入映像到 Kind 集群

```bash
# 載入映像到 Kind（本地映像不會從 Docker Hub 拉取）
kind load docker-image mock-exporter:latest --name 2504-cluster
```

### 9.3 部署 Mock Exporter

```bash
kubectl apply -f mock-exporter-deployment.yaml
```

**驗證**:
```bash
# 檢查 Pod 狀態
kubectl get pods -n monitoring -l app=mock-exporter

# 查看日誌（應該看到 GPU 指標輸出）
kubectl logs -n monitoring -l app=mock-exporter --tail=20

# 測試指標端點
kubectl port-forward -n monitoring svc/mock-exporter 9400:9400
# 訪問 http://localhost:9400/metrics
```

---

## 步驟 10: 部署 Harbor 映像倉庫

### 10.1 安裝 Harbor

```bash
# 添加 Harbor Helm repo
helm repo add harbor https://helm.goharbor.io
helm repo update

# 建立 namespace
kubectl create namespace harbor-system

# 安裝 Harbor（使用輕量配置）
helm install harbor harbor/harbor \
  -n harbor-system \
  -f harbor-lite-values.yaml \
  --wait --timeout=5m
```

### 10.2 驗證 Harbor

```bash
# 檢查所有 Pod 是否就緒
kubectl get pods -n harbor-system

# 應該看到以下 Pod 都是 Running:
# - harbor-core
# - harbor-database
# - harbor-jobservice
# - harbor-nginx
# - harbor-portal
# - harbor-redis
# - harbor-registry
```

### 10.3 訪問 Harbor UI

```bash
# 設定 port-forward
kubectl port-forward -n harbor-system svc/harbor 8080:80
```

然後訪問: http://localhost:8080
- 使用者名稱: `admin`
- 密碼: `Harbor12345`

### 10.4 使用 Harbor 推送映像

```bash
# 登入 Harbor
docker login localhost:8080
# 輸入: admin / Harbor12345

# 標記映像
docker tag mock-exporter:latest localhost:8080/library/mock-exporter:latest

# 推送映像
docker push localhost:8080/library/mock-exporter:latest
```

---

## 驗證整體部署

### 檢查所有 Namespace

```bash
kubectl get namespaces
```

應該看到:
- `ai-system` - LiteLLM Gateway
- `monitoring` - Prometheus & Grafana
- `harbor-system` - Harbor
- `tenant-company-a/b/c` - 租戶 namespace

### 檢查所有服務

```bash
kubectl get svc -A
```

### 檢查網路策略

```bash
kubectl get ciliumnetworkpolicies -A
```

---

## 常用操作

### 查看 Prometheus 目標

```bash
kubectl port-forward -n monitoring svc/prometheus 9090:9090
# 訪問 http://localhost:9090/targets
```

### 查看 Grafana 儀表板

```bash
# 已配置 NodePort，直接訪問
# http://localhost:3000
# 帳號: admin / admin123
```

### 查看 LiteLLM 日誌

```bash
kubectl logs -n ai-system -l app=litellm-gateway -f
```

### 重啟服務

```bash
# 重啟 LiteLLM
kubectl rollout restart deployment litellm-gateway -n ai-system

# 重啟 Prometheus
kubectl rollout restart deployment prometheus -n monitoring

# 重啟 Grafana
kubectl rollout restart deployment grafana -n monitoring
```

---

## 清理環境

### 刪除特定服務

```bash
# 刪除 Harbor
helm uninstall harbor -n harbor-system
kubectl delete namespace harbor-system

# 刪除監控堆疊
kubectl delete -f monitoring-stack.yaml

# 刪除 LiteLLM
kubectl delete -f litellm-stack.yaml
```

### 完全刪除集群

```bash
kind delete cluster --name 2504-cluster
```

---

## 故障排除

### Pod 無法啟動

```bash
# 查看 Pod 詳細資訊
kubectl describe pod <pod-name> -n <namespace>

# 查看日誌
kubectl logs <pod-name> -n <namespace>
```

### 映像拉取失敗

如果看到 `ImagePullBackOff` 錯誤:

1. 確認映像已建置: `docker images | grep <image-name>`
2. 確認映像已載入 Kind: `kind load docker-image <image-name>:latest --name 2504-cluster`
3. 確認 deployment 有設定 `imagePullPolicy: Never`

### 網路連線問題

```bash
# 檢查 Cilium 狀態
kubectl get pods -n kube-system -l k8s-app=cilium

# 查看 Cilium 日誌
kubectl logs -n kube-system -l k8s-app=cilium

# 檢查網路策略
kubectl get ciliumnetworkpolicies -A
```

### LoadBalancer 沒有 External IP

```bash
# 檢查 Cilium L2 配置
kubectl get ciliumloadbalancerippool
kubectl get ciliuml2announcementpolicy

# 確認 L2 announcement 已啟用
kubectl get svc -A | grep LoadBalancer
```

---

## 配置檔案說明

| 檔案 | 用途 |
|------|------|
| `kind-config.yaml` | Kind 集群配置（禁用預設 CNI，port mapping） |
| `cilium-values.yaml` | Cilium Helm 安裝配置 |
| `cilium-l2-config.yaml` | LoadBalancer IP 池和 L2 宣告 |
| `priority-classes.yaml` | 租戶資源優先級定義 |
| `litellm-stack.yaml` | LiteLLM Gateway 完整堆疊 |
| `cilium-security-policies.yaml` | 租戶網路隔離策略 |
| `monitoring-stack.yaml` | Prometheus + Grafana 監控 |
| `mock-exporter-deployment.yaml` | GPU 指標模擬器 |
| `harbor-lite-values.yaml` | Harbor 輕量配置 |

---

## 下一步

1. 部署實際的 LLM 後端（Ollama、vLLM 等）
2. 配置 LiteLLM 路由規則
3. 設定租戶配額和限制
4. 配置 Grafana 告警規則
5. 整合 CI/CD 流程

---

## 參考資源

- [Cilium 文檔](https://docs.cilium.io/)
- [LiteLLM 文檔](https://docs.litellm.ai/)
- [Harbor 文檔](https://goharbor.io/docs/)
- [Kind 文檔](https://kind.sigs.k8s.io/)
