# Guardrails AI 整合 - 進階內容安全防護

## 🎯 功能概述

Guardrails AI 是一個強大的內容安全框架，為 AI 應用提供多層次的安全防護。本系統整合了 Guardrails，提供以下核心功能：

### 1. 內容安全驗證

#### 長度檢查
- ✅ **最大長度限制**: 10,000 字元 (防止 DoS 攻擊)
- ✅ **最小長度限制**: 1 字元 (防止空請求)
- ✅ **動態調整**: 可根據租戶等級調整限制

#### 主題過濾
- ✅ **禁止主題檢測**: 
  - 暴力內容 (violence)
  - 仇恨言論 (hate_speech)
  - 非法活動 (illegal_activities)
  - 人身攻擊 (personal_attacks)
  - 騷擾 (harassment)
  - 歧視 (discrimination)

#### PII (個人識別資訊) 檢測
- ✅ **Email 地址檢測**: 自動識別並標記
- ✅ **電話號碼檢測**: 支援多種格式
- ✅ **SSN 檢測**: 美國社會安全號碼
- ✅ **信用卡號檢測**: 16位數信用卡號
- ✅ **自動遮罩**: 輸出內容自動移除 PII

#### 毒性語言檢測
- ✅ **關鍵字檢測**: 識別仇恨、暴力、攻擊性語言
- ✅ **毒性評分**: 0.0-1.0 的風險評分
- ✅ **閾值控制**: 可配置的毒性閾值 (預設 0.7)
- ✅ **自動封鎖**: 高毒性內容自動攔截

### 2. 風險評分系統

#### 多維度風險評估
- **長度超限**: +0.3 風險分數
- **敏感主題**: +0.2 風險分數
- **PII 檢測**: +0.3 風險分數
- **毒性語言**: +0.2-1.0 風險分數 (根據嚴重度)
- **Guardrails 違規**: +0.4 風險分數

#### 風險等級分類
- **安全 (Safe)**: 風險分數 < 0.5
- **審查 (Review)**: 風險分數 0.5-0.8
- **封鎖 (Block)**: 風險分數 >= 0.8

### 3. Guardrails API 端點

#### 狀態查詢
```bash
GET /guardrails/status
```
查詢 Guardrails 配置和狀態

**回應範例**:
```json
{
  "user": "admin",
  "guardrails_status": {
    "guardrails_enabled": true,
    "safety_rules": {
      "max_length": 10000,
      "min_length": 1,
      "toxicity_threshold": 0.7,
      "pii_detection": true
    }
  }
}
```

#### 內容驗證
```bash
POST /guardrails/validate
Content-Type: application/json

{
  "content": "Your text to validate"
}
```

**回應範例**:
```json
{
  "user": "admin",
  "validation_result": {
    "is_safe": true,
    "violations": [],
    "warnings": [],
    "risk_score": 0.2,
    "category": "safe"
  }
}
```

#### 安全報告
```bash
GET /guardrails/report
```
獲取詳細的安全統計報告 (僅管理員)

**回應範例**:
```json
{
  "report": {
    "summary": {
      "total_validations": 1250,
      "blocked_requests": 87,
      "warnings_issued": 234,
      "average_risk_score": 0.23
    },
    "top_violations": [
      {"type": "toxic_language", "count": 45},
      {"type": "pii_detected", "count": 28}
    ]
  }
}
```

### 4. Prometheus 監控指標

#### Guardrails 專屬指標
- ✅ `guardrails_violations_total`: 違規總數 (按使用者、違規類型)
- ✅ `guardrails_warnings_total`: 警告總數 (按使用者、警告類型)
- ✅ `guardrails_validations_total`: 驗證總數 (按結果)
- ✅ `guardrails_risk_score`: 風險分數分佈 (按使用者)
- ✅ `pii_detected_total`: PII 檢測事件 (按 PII 類型、使用者)
- ✅ `toxic_content_blocked_total`: 毒性內容封鎖 (按毒性等級)

### 5. 整合流程

#### AI 聊天端點防護流程
```
1. 使用者發送請求
   ↓
2. JWT 驗證 + Rate Limiting
   ↓
3. Guardrails 內容安全驗證 ← 新增
   ├─ 長度檢查
   ├─ 主題過濾
   ├─ PII 檢測
   ├─ 毒性檢測
   └─ 風險評分
   ↓
4. Prompt Injection 檢測
   ↓
5. 內容長度檢查
   ↓
6. AI 模型處理
   ↓
7. 輸出內容清理 (PII 遮罩)
   ↓
8. 回傳結果
```

## 🚀 使用範例

### 範例 1: 正常請求
```bash
curl -X POST "http://localhost:8000/ai/chat" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "What is machine learning?",
    "model": "qwen:0.5b"
  }'
```

**回應**: HTTP 200 - 正常處理

### 範例 2: PII 檢測
```bash
curl -X POST "http://localhost:8000/ai/chat" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "My email is john@example.com and phone is 555-1234",
    "model": "qwen:0.5b"
  }'
```

**回應**: HTTP 200 - 但會記錄 PII 警告

### 範例 3: 毒性內容封鎖
```bash
curl -X POST "http://localhost:8000/ai/chat" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "I hate everyone and want to destroy everything",
    "model": "qwen:0.5b"
  }'
```

**回應**: HTTP 400 - Content safety violation detected

### 範例 4: 手動內容驗證
```bash
curl -X POST "http://localhost:8000/guardrails/validate" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "content": "Test content for validation"
  }'
```

## 📊 監控與告警

### Grafana 儀表板整合

建議添加以下面板到 Grafana：

1. **Guardrails 驗證率**
```promql
rate(guardrails_validations_total[5m])
```

2. **違規趨勢**
```promql
rate(guardrails_violations_total[5m])
```

3. **平均風險分數**
```promql
histogram_quantile(0.95, rate(guardrails_risk_score_bucket[5m]))
```

4. **PII 檢測事件**
```promql
rate(pii_detected_total[5m])
```

5. **毒性內容封鎖**
```promql
rate(toxic_content_blocked_total[5m])
```

### 告警規則範例

```yaml
groups:
  - name: guardrails_alerts
    rules:
      - alert: HighGuardrailsViolationRate
        expr: rate(guardrails_violations_total[5m]) > 10
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High Guardrails violation rate detected"
          
      - alert: PIIDetectionSpike
        expr: rate(pii_detected_total[5m]) > 5
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Unusual spike in PII detection"
```

## 🔧 配置選項

### 調整安全規則

在 `GuardrailsProtection` 類中修改 `safety_rules`:

```python
self.safety_rules = {
    "max_length": 10000,        # 調整最大長度
    "min_length": 1,
    "toxicity_threshold": 0.7,  # 調整毒性閾值
    "pii_detection": True,      # 啟用/停用 PII 檢測
    "forbidden_topics": [...]   # 自訂禁止主題
}
```

### 自訂風險評分

修改 `validate_prompt` 方法中的風險分數權重：

```python
# 長度超限
validation_result["risk_score"] += 0.3  # 可調整

# 敏感主題
validation_result["risk_score"] += 0.2  # 可調整

# PII 檢測
validation_result["risk_score"] += 0.3  # 可調整
```

## 🎯 最佳實踐

1. **漸進式部署**: 先以警告模式運行，觀察誤報率
2. **定期審查**: 檢查被封鎖的請求，調整規則
3. **使用者教育**: 提供清晰的錯誤訊息，引導使用者
4. **監控告警**: 設定適當的告警閾值
5. **定期更新**: 更新毒性關鍵字和 PII 模式

## 🔒 安全優勢

1. **多層防護**: Guardrails + Prompt Injection + Rate Limiting
2. **即時檢測**: 請求處理前即時驗證
3. **詳細記錄**: 完整的違規和警告記錄
4. **靈活配置**: 可根據需求調整規則
5. **效能優化**: 輕量級檢測，不影響回應時間

Guardrails 整合為您的 AI 應用提供了企業級的內容安全防護！