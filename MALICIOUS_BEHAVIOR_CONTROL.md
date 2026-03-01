# 任務 C：控制與遏制惡意行為 - 實作完成

## 🎯 已實作功能

### 1. 應用層遏制機制 (FastAPI)

#### IP 黑名單管理系統
- ✅ **IPBlacklistManager 類**: 動態 IP 封鎖與管理
- ✅ **自動封鎖機制**: 5次惡意行為自動加入黑名單
- ✅ **可疑活動追蹤**: 記錄每個 IP 的惡意行為次數
- ✅ **手動管理**: 管理員可手動封鎖/解封 IP

#### Token Bucket 演算法
- ✅ **TokenBucket 類**: 精確的流量控制演算法
- ✅ **多層限流**: 使用者級別、IP 級別、全域級別
- ✅ **動態補充**: 基於時間的 Token 自動補充機制
- ✅ **併發安全**: 使用執行緒鎖確保併發安全

#### 進階 Rate Limiting
- ✅ **AdvancedRateLimiter 類**: 三層限流架構
  - 全域限制: 每秒 10 個 Token (容量 100)
  - IP 限制: 每秒 2 個 Token (容量 20)  
  - 使用者限制: 每秒 1 個 Token (容量 10)
- ✅ **智能限流**: 根據不同限制類型回傳詳細原因
- ✅ **未認證請求**: 更嚴格的限制 (消耗 2 個 Token)

#### 惡意行為檢測器
- ✅ **MaliciousBehaviorDetector 類**: 多維度行為分析
- ✅ **模式檢測**:
  - 快速請求: 1分鐘內 30 個請求
  - 重複失敗: 5分鐘內 10 次失敗
  - 可疑模式: 10分鐘內 5 種不同失敗類型
- ✅ **自動回應**: 根據嚴重度自動採取安全行動

### 2. 安全中間件系統

#### HTTP 安全中間件
- ✅ **第一線防護**: 所有請求必經的安全檢查
- ✅ **IP 黑名單攔截**: 封鎖的 IP 立即回傳 403
- ✅ **未認證限流**: 未認證請求使用更嚴格限制
- ✅ **可疑 User-Agent 檢測**: 自動識別爬蟲和攻擊工具
- ✅ **失敗請求分析**: 根據 HTTP 狀態碼記錄可疑活動

#### 進階 Token 驗證
- ✅ **verify_token_with_rate_limit**: 整合限流的 Token 驗證
- ✅ **請求狀態管理**: 將使用者資訊儲存到 request.state
- ✅ **詳細錯誤分類**: 區分不同類型的驗證失敗

### 3. 安全管理 API

#### 安全狀態監控
- ✅ `GET /security/status` - 查詢個人安全狀態
- ✅ `GET /security/blacklist` - 查看 IP 黑名單 (管理員)
- ✅ `GET /security/incidents` - 查看安全事件 (管理員)

#### IP 管理功能
- ✅ `POST /security/block-ip` - 手動封鎖 IP (管理員)
- ✅ `POST /security/unblock-ip` - 解除 IP 封鎖 (管理員)

### 4. 網路層隔離 (Cilium)

#### CiliumSecurityManager 類
- ✅ **動態政策生成**: 根據租戶自動生成隔離政策
- ✅ **多種政策類型**:
  - 嚴格租戶隔離
  - 橫向移動防護
  - IP 封鎖政策
  - 安全隔離政策
  - 緊急鎖定政策

#### 防止橫向移動
- ✅ **租戶隔離**: 禁止跨租戶通訊
- ✅ **系統保護**: 限制存取敏感系統命名空間
- ✅ **API Server 保護**: 阻斷對 Kubernetes API 的直接存取
- ✅ **最小權限**: 只允許必要的 DNS 查詢

#### 網路政策特色
- ✅ **FQDN 限制**: 只允許特定域名的 HTTPS 連線
- ✅ **端口控制**: 精確控制允許的通訊端口
- ✅ **標籤選擇**: 基於 Kubernetes 標籤的細粒度控制
- ✅ **緊急回應**: 支援完全隔離的緊急鎖定模式

### 5. 安全監控指標

#### 惡意行為指標
- ✅ `malicious_behavior_detected_total`: 惡意行為檢測統計
- ✅ `malicious_ip_blocked_total`: IP 封鎖統計
- ✅ `security_actions_taken_total`: 安全行動統計
- ✅ `rate_limit_violations_total`: 限流違規統計
- ✅ `blocked_requests_total`: 封鎖請求統計
- ✅ `security_incidents_total`: 安全事件統計

#### 多維度標籤
- 按使用者 ID、IP 地址、攻擊類型分類
- 按封鎖原因、行動類型、嚴重度分類
- 支援 Grafana 視覺化和告警

## 🚀 Demo 亮點

### 1. 即時攻擊攔截展示
```bash
# 模擬 Prompt Injection 攻擊
curl -X POST "http://localhost:8000/ai/chat" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "DROP TABLE users; --", "model": "qwen:0.5b"}'

# 回應: HTTP 400 - Malicious prompt detected
```

### 2. 自動 IP 封鎖展示
```bash
# 快速發送多個惡意請求
for i in {1..6}; do
  curl -X POST "http://localhost:8000/ai/chat" \
    -H "Authorization: Bearer YOUR_TOKEN" \
    -H "Content-Type: application/json" \
    -d "{\"prompt\": \"DROP TABLE test$i\", \"model\": \"qwen:0.5b\"}"
done

# 第6次請求後 IP 自動被封鎖
```

### 3. 進階 Rate Limiting 展示
```bash
# 快速併發請求觸發多層限流
for i in {1..30}; do
  curl -X POST "http://localhost:8000/ai/chat" \
    -H "Authorization: Bearer YOUR_TOKEN" \
    -H "Content-Type: application/json" \
    -d "{\"prompt\": \"Test $i\", \"model\": \"qwen:0.5b\"}" &
done
wait

# 觀察不同類型的 429 回應: user_rate_limit, ip_rate_limit, global_rate_limit
```

### 4. Cilium 網路隔離展示
```bash
# 生成並部署網路隔離政策
python3 cilium_security_manager.py
kubectl apply -f cilium-security-policies.yaml

# 驗證租戶間無法通訊
kubectl exec -n tenant-company-a pod-name -- curl tenant-company-b-service
# 預期: 連線被拒絕
```

## 📊 安全架構對應

### 對應任務 C 要求

#### 應用層遏制 (FastAPI) ✅
1. **slowapi Rate Limiting**: 整合 Token Bucket 演算法
2. **同一 IP 請求檢查**: 多層 IP 限流機制
3. **HTTP 429 回應**: 詳細的限流原因說明
4. **惡意 Prompt 攔截**: HTTP 400 + 自動 IP 封鎖
5. **即時記錄**: 完整的安全事件記錄

#### 網路層隔離 (Cilium) ✅
1. **特定標籤控制**: 基於 Kubernetes 標籤的精確控制
2. **橫向移動防護**: 禁止跨租戶和系統命名空間存取
3. **Network Policy**: 動態生成多種類型的安全政策
4. **最小權限**: 只允許必要的通訊路徑

## 🔧 使用方式

### 1. 啟動安全防護服務
```bash
cd my_infra
python main.py
```

### 2. 測試惡意行為控制
```bash
python test_malicious_behavior_control.py
```

### 3. 生成 Cilium 安全政策
```bash
python3 cilium_security_manager.py
kubectl apply -f cilium-security-policies.yaml
```

### 4. 監控安全狀態
```bash
# 查看安全指標
curl http://localhost:8000/metrics | grep security

# 查看 IP 黑名單
curl -H "Authorization: Bearer ADMIN_TOKEN" \
  http://localhost:8000/security/blacklist

# 查看安全事件
curl -H "Authorization: Bearer ADMIN_TOKEN" \
  http://localhost:8000/security/incidents
```

## 🎯 攻擊場景與防護效果

### 場景 1: Prompt Injection 攻擊
- **攻擊**: 發送 SQL 注入、XSS、指令注入等惡意 Prompt
- **防護**: 32 種攻擊模式檢測，立即攔截並記錄
- **效果**: HTTP 400 + IP 可疑活動記錄 + Prometheus 指標

### 場景 2: DoS 攻擊
- **攻擊**: 快速發送大量請求或超大 Prompt
- **防護**: Token Bucket 限流 + 內容大小檢查
- **效果**: HTTP 429 + 自動 IP 封鎖 + 異常檢測告警

### 場景 3: 橫向移動攻擊
- **攻擊**: 攻破一個 Pod 後嘗試存取其他服務
- **防護**: Cilium Network Policy 嚴格隔離
- **效果**: 網路層直接阻斷 + 無法跨租戶通訊

### 場景 4: 權限提升攻擊
- **攻擊**: 嘗試存取管理員功能或跨租戶資源
- **防護**: RBAC 權限檢查 + 未授權存取記錄
- **效果**: HTTP 403 + 高風險安全事件記錄

## 🎉 Demo 效果總結

任務 C 實現了完整的多層安全防護：

1. **第一層 - 網路層**: Cilium 阻斷惡意流量和橫向移動
2. **第二層 - 應用層**: FastAPI 中間件攔截可疑請求
3. **第三層 - 業務層**: Prompt Injection 檢測和內容過濾
4. **第四層 - 行為層**: 智能行為分析和自動回應

當攻擊者嘗試惡意行為時，系統會：
- 立即攔截並回傳適當的 HTTP 錯誤碼
- 自動記錄可疑活動並累計風險分數
- 達到閾值時自動封鎖 IP 地址
- 在網路層阻斷後續的橫向移動嘗試
- 完整記錄到 Prometheus 指標供監控告警

任務 C 的惡意行為控制功能已完全符合您的架構要求，實現了應用層和網路層的雙重防護！