from fastapi import FastAPI, HTTPException, Depends, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import Response
from pydantic import BaseModel, Field
from kubernetes import client, config
from kubernetes.client.rest import ApiException
import httpx
import logging
import base64  # 用於 Harbor 的 Basic Auth 加密
import re
import time
import asyncio
import random
import json
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from jose import JWTError, jwt
from passlib.context import CryptContext
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from prometheus_client import (
    Counter,
    Histogram,
    Gauge,
    generate_latest,
    CONTENT_TYPE_LATEST,
)
import redis
import psutil
import threading
from collections import defaultdict, deque

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Guardrails AI 整合
GUARDRAILS_AVAILABLE = False
try:
    import guardrails as gd
    from guardrails import Guard
    
    GUARDRAILS_AVAILABLE = True
    logger.info("✅ Guardrails AI 已載入")
except ImportError as e:
    logger.warning(f"⚠️ Guardrails AI 未安裝，將使用基本防護: {e}")


# Guardrails 防護類
class GuardrailsProtection:
    """Guardrails AI 整合 - 提供進階內容安全檢查"""

    def __init__(self):
        self.enabled = GUARDRAILS_AVAILABLE
        self.validation_cache = {}

        # 定義安全規則
        self.safety_rules = {
            "max_length": 10000,  # 最大字元數
            "min_length": 1,  # 最小字元數
            "forbidden_topics": [
                "violence",
                "hate_speech",
                "illegal_activities",
                "personal_attacks",
                "harassment",
                "discrimination",
            ],
            "required_language": "professional",
            "pii_detection": True,  # 個人資訊檢測
            "toxicity_threshold": 0.3,  # 毒性閾值 (降低以提高敏感度)
        }

        # 內容分類規則
        self.content_categories = {
            "safe": ["general_query", "technical_question", "creative_writing"],
            "review": ["sensitive_topic", "medical_advice", "legal_advice"],
            "block": ["malicious_code", "exploit_attempt", "data_exfiltration"],
        }

    def validate_prompt(self, prompt: str, user_id: str = "unknown") -> Dict[str, Any]:
        """驗證 Prompt 的安全性"""

        validation_result = {
            "is_safe": True,
            "violations": [],
            "warnings": [],
            "risk_score": 0.0,
            "category": "safe",
            "guardrails_used": self.enabled,
        }

        # 1. 基本長度檢查
        if len(prompt) > self.safety_rules["max_length"]:
            validation_result["is_safe"] = False
            validation_result["violations"].append(
                {
                    "type": "length_exceeded",
                    "message": f"Prompt exceeds maximum length of {self.safety_rules['max_length']} characters",
                    "severity": "high",
                }
            )
            validation_result["risk_score"] += 0.3

        if len(prompt) < self.safety_rules["min_length"]:
            validation_result["is_safe"] = False
            validation_result["violations"].append(
                {
                    "type": "length_too_short",
                    "message": "Prompt is too short",
                    "severity": "low",
                }
            )

        # 2. 禁止主題檢查
        prompt_lower = prompt.lower()
        for topic in self.safety_rules["forbidden_topics"]:
            if topic.replace("_", " ") in prompt_lower:
                validation_result["warnings"].append(
                    {
                        "type": "sensitive_topic",
                        "topic": topic,
                        "message": f"Prompt contains potentially sensitive topic: {topic}",
                        "severity": "medium",
                    }
                )
                validation_result["risk_score"] += 0.2

        # 3. PII 檢測 (簡化版)
        if self.safety_rules["pii_detection"]:
            pii_patterns = {
                "email": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
                "phone": r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b",
                "ssn": r"\b\d{3}-\d{2}-\d{4}\b",
                "credit_card": r"\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b",
            }

            for pii_type, pattern in pii_patterns.items():
                if re.search(pattern, prompt):
                    validation_result["warnings"].append(
                        {
                            "type": "pii_detected",
                            "pii_type": pii_type,
                            "message": f"Potential {pii_type} detected in prompt",
                            "severity": "high",
                        }
                    )
                    validation_result["risk_score"] += 0.3

        # 4. 毒性語言檢測 (基於關鍵字 - 支援多語言)
        toxic_keywords = [
            # 英文毒性詞彙
            "hate",
            "kill",
            "destroy",
            "attack",
            "bomb",
            "weapon",
            "racist",
            "sexist",
            "offensive",
            "abuse",
            "threat",
            "stupid",
            "idiot",
            "fool",
            "dumb",
            # 中文毒性詞彙
            "白癡",
            "笨蛋",
            "傻瓜",
            "蠢貨",
            "混蛋",
            "王八蛋",
            "垃圾",
            "廢物",
            "去死",
            "該死",
            "他媽",
            "媽的",
            "幹",
            "操",
            "靠",
            "智障",
            "腦殘",
            "低能",
            "賤人",
            "婊子",
        ]

        # 檢測毒性詞彙 (對原始 prompt 和小寫版本都檢查，以支援中文)
        detected_toxic_words = []
        for keyword in toxic_keywords:
            if keyword.lower() in prompt_lower or keyword in prompt:
                detected_toxic_words.append(keyword)
        
        toxic_count = len(detected_toxic_words)
        if toxic_count > 0:
            # 每個毒性詞彙 0.25 分，這樣 2 個詞就能達到 0.5 分
            toxicity_score = min(toxic_count * 0.25, 1.0)
            validation_result["risk_score"] += toxicity_score

            # 添加警告（即使未達到封鎖閾值）
            if toxicity_score < self.safety_rules["toxicity_threshold"]:
                validation_result["warnings"].append(
                    {
                        "type": "toxic_language",
                        "message": f"Toxic language detected: {', '.join(detected_toxic_words[:3])} (score: {toxicity_score:.2f})",
                        "severity": "medium",
                        "toxic_words": detected_toxic_words,
                    }
                )
            
            # 達到閾值則封鎖
            if toxicity_score >= self.safety_rules["toxicity_threshold"]:
                validation_result["is_safe"] = False
                validation_result["violations"].append(
                    {
                        "type": "toxic_language",
                        "message": f"High toxicity detected: {', '.join(detected_toxic_words)} (score: {toxicity_score:.2f})",
                        "severity": "critical",
                        "toxic_words": detected_toxic_words,
                    }
                )

        # 5. 使用 Guardrails AI (如果可用)
        if self.enabled:
            try:
                guardrails_result = self._run_guardrails_validation(prompt)
                validation_result["guardrails_result"] = guardrails_result

                if not guardrails_result.get("passed", True):
                    validation_result["is_safe"] = False
                    validation_result["violations"].extend(
                        guardrails_result.get("violations", [])
                    )
                    validation_result["risk_score"] += 0.4

            except Exception as e:
                logger.error(f"Guardrails 驗證錯誤: {e}")
                validation_result["warnings"].append(
                    {
                        "type": "guardrails_error",
                        "message": f"Guardrails validation failed: {str(e)}",
                        "severity": "low",
                    }
                )

        # 6. 計算最終風險等級
        if validation_result["risk_score"] >= 0.8:
            validation_result["category"] = "block"
            validation_result["is_safe"] = False
        elif validation_result["risk_score"] >= 0.5:
            validation_result["category"] = "review"
        else:
            validation_result["category"] = "safe"

        # 7. 記錄到監控指標
        if not validation_result["is_safe"]:
            guardrails_violations.labels(
                user_id=user_id,
                violation_type=validation_result["violations"][0]["type"]
                if validation_result["violations"]
                else "unknown",
            ).inc()

        return validation_result

    def _run_guardrails_validation(self, prompt: str) -> Dict[str, Any]:
        """執行 Guardrails AI 驗證"""

        if not self.enabled:
            return {"passed": True, "message": "Guardrails not available"}

        try:
            # 這裡可以整合實際的 Guardrails AI 驗證
            # 目前使用簡化版本
            result = {
                "passed": True,
                "violations": [],
                "metadata": {"validator": "guardrails-ai", "version": "0.5.0"},
            }

            # 示例：長度驗證
            if len(prompt) > 5000:
                result["passed"] = False
                result["violations"].append(
                    {
                        "type": "guardrails_length",
                        "message": "Prompt exceeds Guardrails length limit",
                        "severity": "medium",
                    }
                )

            return result

        except Exception as e:
            logger.error(f"Guardrails 執行錯誤: {e}")
            return {
                "passed": True,  # 失敗時預設通過，避免阻斷正常請求
                "error": str(e),
            }

    def sanitize_output(self, output: str) -> str:
        """清理輸出內容，移除敏感資訊"""

        # 移除可能的 PII
        sanitized = output

        # Email 遮罩
        sanitized = re.sub(
            r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
            "[EMAIL_REDACTED]",
            sanitized,
        )

        # 電話號碼遮罩
        sanitized = re.sub(
            r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b", "[PHONE_REDACTED]", sanitized
        )

        # SSN 遮罩
        sanitized = re.sub(r"\b\d{3}-\d{2}-\d{4}\b", "[SSN_REDACTED]", sanitized)

        return sanitized

    def get_safety_report(self) -> Dict[str, Any]:
        """獲取安全報告"""
        return {
            "guardrails_enabled": self.enabled,
            "safety_rules": self.safety_rules,
            "content_categories": self.content_categories,
            "cache_size": len(self.validation_cache),
        }


# 初始化 Guardrails 防護
guardrails_protection = GuardrailsProtection()
from collections import defaultdict, deque
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 安全配置
SECRET_KEY = "your-secret-key-change-in-production"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

# 密碼加密
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# JWT Token 安全驗證
security = HTTPBearer()

# Rate Limiting 配置 (任務 C: 應用層遏制)
limiter = Limiter(key_func=get_remote_address)

app = FastAPI(
    title="LLM Gateway Provisioning API",
    description="動態多租戶算力與 Cilium 安全隔離管理系統 - 具備 JWT 驗證、RBAC 權限控管、Prompt Injection 防護",
)


# IP 黑名單管理
class IPBlacklistManager:
    def __init__(self):
        self.blacklisted_ips = set()
        self.suspicious_ips = defaultdict(
            lambda: {"count": 0, "last_seen": datetime.utcnow()}
        )
        self.auto_ban_threshold = 5  # 5次惡意行為自動封鎖
        self.ban_duration = timedelta(hours=1)  # 封鎖1小時

    def add_suspicious_activity(self, ip: str, activity_type: str):
        """記錄可疑活動"""
        self.suspicious_ips[ip]["count"] += 1
        self.suspicious_ips[ip]["last_seen"] = datetime.utcnow()
        self.suspicious_ips[ip]["activity_type"] = activity_type

        logger.warning(
            f"🚨 可疑活動記錄: IP {ip}, 類型: {activity_type}, 累計: {self.suspicious_ips[ip]['count']}"
        )

        # 自動封鎖
        if self.suspicious_ips[ip]["count"] >= self.auto_ban_threshold:
            self.blacklist_ip(ip, f"自動封鎖 - {activity_type}")

    def blacklist_ip(self, ip: str, reason: str):
        """將 IP 加入黑名單"""
        self.blacklisted_ips.add(ip)
        logger.error(f"🚫 IP 已封鎖: {ip}, 原因: {reason}")

        # 記錄到 Prometheus
        malicious_ip_blocked.labels(ip=ip, reason=reason).inc()

    def is_blacklisted(self, ip: str) -> bool:
        """檢查 IP 是否在黑名單中"""
        return ip in self.blacklisted_ips

    def unblock_ip(self, ip: str):
        """解除 IP 封鎖"""
        if ip in self.blacklisted_ips:
            self.blacklisted_ips.remove(ip)
            logger.info(f"✅ IP 解除封鎖: {ip}")


# Token Bucket 演算法實作
class TokenBucket:
    def __init__(self, capacity: int, refill_rate: float):
        self.capacity = capacity
        self.tokens = capacity
        self.refill_rate = refill_rate  # tokens per second
        self.last_refill = time.time()
        self.lock = threading.Lock()

    def consume(self, tokens: int = 1) -> bool:
        """嘗試消耗 tokens，成功返回 True"""
        with self.lock:
            now = time.time()
            # 補充 tokens
            elapsed = now - self.last_refill
            self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
            self.last_refill = now

            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
            return False


# 進階 Rate Limiting 管理
class AdvancedRateLimiter:
    def __init__(self):
        self.user_buckets = defaultdict(
            lambda: TokenBucket(capacity=10, refill_rate=1.0)
        )  # 每秒1個token
        self.ip_buckets = defaultdict(
            lambda: TokenBucket(capacity=20, refill_rate=2.0)
        )  # 每秒2個token
        self.global_bucket = TokenBucket(capacity=100, refill_rate=10.0)  # 全域限制

    def check_rate_limit(self, user_id: str, ip: str) -> tuple[bool, str]:
        """檢查是否超過限制，返回 (允許, 原因)"""

        # 1. 全域限制檢查
        if not self.global_bucket.consume():
            return False, "global_rate_limit"

        # 2. IP 限制檢查
        if not self.ip_buckets[ip].consume():
            return False, "ip_rate_limit"

        # 3. 使用者限制檢查
        if not self.user_buckets[user_id].consume():
            return False, "user_rate_limit"

        return True, "allowed"


# 惡意行為檢測器
class MaliciousBehaviorDetector:
    def __init__(self):
        self.behavior_patterns = {
            "rapid_requests": {"window": 60, "threshold": 30},  # 1分鐘內30個請求
            "repeated_failures": {"window": 300, "threshold": 10},  # 5分鐘內10次失敗
            "suspicious_patterns": {
                "window": 600,
                "threshold": 5,
            },  # 10分鐘內5次可疑模式
        }
        self.user_activity = defaultdict(lambda: defaultdict(list))

    def record_activity(self, user_id: str, ip: str, activity_type: str, success: bool):
        """記錄使用者活動"""
        timestamp = time.time()
        activity = {
            "timestamp": timestamp,
            "type": activity_type,
            "success": success,
            "ip": ip,
        }

        self.user_activity[user_id]["activities"].append(activity)

        # 清理舊資料 (保留最近10分鐘)
        cutoff = timestamp - 600
        self.user_activity[user_id]["activities"] = [
            a
            for a in self.user_activity[user_id]["activities"]
            if a["timestamp"] > cutoff
        ]

        # 檢測惡意行為
        self._detect_malicious_behavior(user_id, ip)

    def _detect_malicious_behavior(self, user_id: str, ip: str):
        """檢測惡意行為模式"""
        activities = self.user_activity[user_id]["activities"]
        current_time = time.time()

        # 檢測快速請求
        recent_requests = [a for a in activities if current_time - a["timestamp"] <= 60]
        if len(recent_requests) >= 30:
            self._trigger_security_action(
                user_id, ip, "rapid_requests", len(recent_requests)
            )

        # 檢測重複失敗
        recent_failures = [
            a
            for a in activities
            if current_time - a["timestamp"] <= 300 and not a["success"]
        ]
        if len(recent_failures) >= 10:
            self._trigger_security_action(
                user_id, ip, "repeated_failures", len(recent_failures)
            )

        # 檢測可疑模式 (多種不同類型的失敗)
        failure_types = set(a["type"] for a in recent_failures)
        if len(failure_types) >= 3 and len(recent_failures) >= 5:
            self._trigger_security_action(
                user_id, ip, "suspicious_patterns", len(failure_types)
            )

    def _trigger_security_action(
        self, user_id: str, ip: str, pattern_type: str, severity: int
    ):
        """觸發安全行動"""
        logger.error(
            f"🚨 惡意行為檢測: 使用者 {user_id}, IP {ip}, 模式 {pattern_type}, 嚴重度 {severity}"
        )

        # 記錄到監控指標
        malicious_behavior_detected.labels(
            user_id=user_id, ip=ip, pattern_type=pattern_type
        ).inc()

        # 根據嚴重度採取行動
        if severity >= 20:  # 高風險
            ip_blacklist.blacklist_ip(ip, f"惡意行為檢測 - {pattern_type}")
            security_actions_taken.labels(
                action="ip_blocked", reason=pattern_type
            ).inc()
        elif severity >= 10:  # 中風險
            ip_blacklist.add_suspicious_activity(ip, pattern_type)
            security_actions_taken.labels(
                action="marked_suspicious", reason=pattern_type
            ).inc()


# 初始化安全組件
ip_blacklist = IPBlacklistManager()
rate_limiter = AdvancedRateLimiter()
behavior_detector = MaliciousBehaviorDetector()


# 安全中間件
@app.middleware("http")
async def security_middleware(request: Request, call_next):
    """安全中間件 - 第一線防護"""
    start_time = time.time()
    client_ip = request.client.host

    # 定義管理端點白名單（即使 IP 被封鎖，管理員仍可訪問這些端點）
    admin_whitelist_paths = [
        "/security/blacklist",
        "/security/unblock-ip",
        "/security/incidents",
        "/auth/login",  # 允許登入
    ]

    # 1. IP 黑名單檢查（管理端點除外）
    if ip_blacklist.is_blacklisted(client_ip):
        # 檢查是否是管理端點
        is_admin_path = any(request.url.path.startswith(path) for path in admin_whitelist_paths)
        
        if not is_admin_path:
            blocked_requests_total.labels(block_reason="ip_blacklisted", ip=client_ip).inc()
            logger.warning(f"🚫 封鎖的 IP 嘗試存取: {client_ip} -> {request.url.path}")
            return Response(
                content=json.dumps({"detail": "Access denied: IP address is blacklisted"}),
                status_code=status.HTTP_403_FORBIDDEN,
                media_type="application/json"
            )
        else:
            logger.info(f"⚠️ 被封鎖的 IP 訪問管理端點（允許）: {client_ip} -> {request.url.path}")
    # 2. 基本 Rate Limiting (針對未認證請求)
    if not request.url.path.startswith("/auth/"):
        # 檢查是否有認證 header
        auth_header = request.headers.get("authorization")
        if not auth_header:
            # 未認證請求使用更嚴格的限制
            if not rate_limiter.ip_buckets[client_ip].consume(2):  # 消耗2個token
                rate_limit_violations.labels(
                    limit_type="unauthenticated", user_id="anonymous"
                ).inc()
                blocked_requests_total.labels(
                    block_reason="rate_limit_unauthenticated", ip=client_ip
                ).inc()
                return Response(
                    content=json.dumps({"detail": "Rate limit exceeded for unauthenticated requests"}),
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    media_type="application/json",
                    headers={"Retry-After": "60"}
                )

    # 3. 可疑 User-Agent 檢查
    user_agent = request.headers.get("user-agent", "").lower()
    suspicious_agents = ["bot", "crawler", "scanner", "hack", "exploit"]
    if any(agent in user_agent for agent in suspicious_agents):
        ip_blacklist.add_suspicious_activity(client_ip, "suspicious_user_agent")
        security_incidents.labels(
            incident_type="suspicious_user_agent", severity="medium"
        ).inc()
        logger.warning(f"🚨 可疑 User-Agent: {client_ip} - {user_agent}")

    # 4. 執行請求
    try:
        response = await call_next(request)

        # 記錄成功請求
        processing_time = time.time() - start_time
        if hasattr(request.state, "current_user"):
            behavior_detector.record_activity(
                request.state.current_user.username,
                client_ip,
                f"{request.method}_{request.url.path}",
                True,
            )

        return response

    except HTTPException as e:
        # 記錄失敗請求
        processing_time = time.time() - start_time

        if hasattr(request.state, "current_user"):
            behavior_detector.record_activity(
                request.state.current_user.username,
                client_ip,
                f"{request.method}_{request.url.path}",
                False,
            )

        # 根據錯誤類型記錄可疑活動
        if e.status_code == 401:
            ip_blacklist.add_suspicious_activity(client_ip, "authentication_failure")
        elif e.status_code == 403:
            ip_blacklist.add_suspicious_activity(client_ip, "authorization_failure")
        elif e.status_code == 400:
            ip_blacklist.add_suspicious_activity(client_ip, "malicious_request")

        raise e


# Redis 連接 (用於 Rate Limiting)
import os

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_DB = int(os.getenv("REDIS_DB", "0"))

try:
    redis_client = redis.Redis(
        host=REDIS_HOST, 
        port=REDIS_PORT, 
        db=REDIS_DB, 
        decode_responses=True,
        socket_connect_timeout=2  # 2 秒超時
    )
    redis_client.ping()
    logger.info(f"✅ Redis 連接成功 ({REDIS_HOST}:{REDIS_PORT})")
except Exception as e:
    logger.info(f"ℹ️  Redis 未連接 ({REDIS_HOST}:{REDIS_PORT})，使用記憶體儲存模式")
    redis_client = None

# Prometheus 監控指標 (任務 B: AI 專屬指標)
llm_requests_total = Counter(
    "llm_requests_total", "Total LLM requests", ["tenant", "status", "model"]
)
llm_prompt_injection_detected = Counter(
    "llm_prompt_injection_detected",
    "Prompt injection attempts detected",
    ["tenant", "attack_type"],
)
llm_request_duration = Histogram(
    "llm_request_duration_seconds", "LLM request duration", ["tenant", "model"]
)
llm_tokens_processed = Counter(
    "llm_tokens_processed_total",
    "Total tokens processed by LLM",
    ["tenant", "model", "type"],
)
llm_concurrent_requests = Gauge(
    "llm_concurrent_requests", "Current concurrent LLM requests", ["tenant"]
)
llm_queue_size = Gauge("llm_queue_size", "LLM request queue size", ["tenant"])
llm_error_rate = Counter(
    "llm_errors_total", "LLM processing errors", ["tenant", "error_type"]
)
llm_model_load_time = Histogram(
    "llm_model_load_seconds", "Time to load LLM model", ["tenant", "model"]
)
llm_memory_usage = Gauge(
    "llm_memory_usage_bytes", "LLM memory usage in bytes", ["tenant", "model"]
)
llm_gpu_utilization = Gauge(
    "llm_gpu_utilization_percent", "GPU utilization percentage", ["tenant", "gpu_id"]
)
llm_throughput = Gauge(
    "llm_throughput_requests_per_second",
    "LLM throughput in requests per second",
    ["tenant"],
)

# 系統監控指標
auth_failures_total = Counter(
    "auth_failures_total", "Authentication failures", ["reason"]
)
system_cpu_usage = Gauge("system_cpu_usage_percent", "System CPU usage percentage")
system_memory_usage = Gauge("system_memory_usage_bytes", "System memory usage in bytes")
network_connections = Gauge(
    "network_connections_total", "Total network connections", ["state"]
)

# 異常檢測指標
anomaly_detection_alerts = Counter(
    "anomaly_detection_alerts_total",
    "Anomaly detection alerts",
    ["tenant", "alert_type"],
)
traffic_spike_detected = Counter(
    "traffic_spike_detected_total", "Traffic spike detection events", ["tenant"]
)
unusual_pattern_detected = Counter(
    "unusual_pattern_detected_total",
    "Unusual pattern detection",
    ["tenant", "pattern_type"],
)

# 任務 C: 惡意行為控制指標
malicious_behavior_detected = Counter(
    "malicious_behavior_detected_total",
    "Malicious behavior detection",
    ["user_id", "ip", "pattern_type"],
)
malicious_ip_blocked = Counter(
    "malicious_ip_blocked_total", "IPs blocked for malicious behavior", ["ip", "reason"]
)
security_actions_taken = Counter(
    "security_actions_taken_total", "Security actions taken", ["action", "reason"]
)
rate_limit_violations = Counter(
    "rate_limit_violations_total", "Rate limit violations", ["limit_type", "user_id"]
)
blocked_requests_total = Counter(
    "blocked_requests_total", "Total blocked requests", ["block_reason", "ip"]
)
security_incidents = Counter(
    "security_incidents_total", "Security incidents", ["incident_type", "severity"]
)

# Guardrails 防護指標
guardrails_violations = Counter(
    "guardrails_violations_total",
    "Guardrails validation violations",
    ["user_id", "violation_type"],
)
guardrails_warnings = Counter(
    "guardrails_warnings_total",
    "Guardrails validation warnings",
    ["user_id", "warning_type"],
)
guardrails_validations = Counter(
    "guardrails_validations_total", "Total Guardrails validations", ["result"]
)
guardrails_risk_score = Histogram(
    "guardrails_risk_score", "Guardrails risk score distribution", ["user_id"]
)
pii_detected = Counter(
    "pii_detected_total", "PII detection events", ["pii_type", "user_id"]
)
toxic_content_blocked = Counter(
    "toxic_content_blocked_total", "Toxic content blocked", ["toxicity_level"]
)

# 假的使用者資料庫 (生產環境應使用真實資料庫)
fake_users_db = {
    "admin": {
        "username": "admin",
        "hashed_password": pwd_context.hash("admin123"),
        "role": "admin",
        "tenant_id": "system",
    },
    "user1": {
        "username": "user1",
        "hashed_password": pwd_context.hash("user123"),
        "role": "basic_user",
        "tenant_id": "company-a",
    },
}

# 添加 Rate Limiting 錯誤處理
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Prompt Injection 檢測規則 (擴充版)
PROMPT_INJECTION_PATTERNS = [
    # 指令注入類
    r"ignore.*previous.*instructions",
    r"forget.*everything",
    r"disregard.*above",
    r"override.*settings",
    # 角色劫持類
    r"system\s*:\s*you\s+are",
    r"act\s+as.*admin",
    r"pretend\s+to\s+be",
    r"roleplay\s+as",
    # 程式碼注入類
    r"<\s*script\s*>",
    r"javascript\s*:",
    r"eval\s*\(",
    r"exec\s*\(",
    r"__import__",
    r"subprocess",
    r"os\.system",
    # 系統指令類
    r"rm\s+-rf",
    r"sudo\s+",
    r"chmod\s+",
    r"wget\s+",
    r"curl.*\|.*sh",
    # SQL 注入類
    r"DROP\s+TABLE",
    r"DELETE\s+FROM",
    r"INSERT\s+INTO",
    r"UPDATE.*SET",
    r"UNION\s+SELECT",
    r";\s*--",
    # 資訊洩露類
    r"show.*password",
    r"reveal.*secret",
    r"display.*config",
    r"print.*env",
    # 繞過嘗試類
    r"\\n\\n.*admin",
    r"<!--.*-->",
    r"\{\{.*\}\}",
    r"\$\{.*\}",
]


# 資料模型
class UserLogin(BaseModel):
    username: str
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str
    role: str
    tenant_id: str


class User(BaseModel):
    username: str
    role: str
    tenant_id: str


class AIRequest(BaseModel):
    prompt: str
    model: str = "qwen:0.5b"
    tenant_id: Optional[str] = None


# 安全工具函數
def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password):
    return pwd_context.hash(password)


def authenticate_user(username: str, password: str):
    user = fake_users_db.get(username)
    if not user or not verify_password(password, user["hashed_password"]):
        return False
    return user


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    try:
        payload = jwt.decode(
            credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM]
        )
        username: str = payload.get("sub")
        if username is None:
            auth_failures_total.labels(reason="invalid_token").inc()
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )
        user = fake_users_db.get(username)
        if user is None:
            auth_failures_total.labels(reason="user_not_found").inc()
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # 建立 User 物件並儲存到 request state
        current_user = User(
            username=user["username"], role=user["role"], tenant_id=user["tenant_id"]
        )
        return current_user

    except JWTError:
        auth_failures_total.labels(reason="jwt_decode_error").inc()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )


def verify_token_with_rate_limit(
    request: Request, credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """帶有進階 Rate Limiting 的 Token 驗證"""
    client_ip = request.client.host

    # 先驗證 Token
    current_user = verify_token(credentials)

    # 進階 Rate Limiting 檢查
    allowed, reason = rate_limiter.check_rate_limit(current_user.username, client_ip)
    if not allowed:
        rate_limit_violations.labels(
            limit_type=reason, user_id=current_user.username
        ).inc()
        blocked_requests_total.labels(
            block_reason=f"rate_limit_{reason}", ip=client_ip
        ).inc()

        # 記錄可疑活動
        ip_blacklist.add_suspicious_activity(
            client_ip, f"rate_limit_violation_{reason}"
        )

        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded: {reason}",
            headers={"Retry-After": "60"},
        )

    # 儲存使用者資訊到 request state
    request.state.current_user = current_user
    return current_user


def require_admin(
    request: Request, current_user: User = Depends(verify_token_with_rate_limit)
):
    if current_user.role != "admin":
        # 記錄未授權存取嘗試
        client_ip = request.client.host
        ip_blacklist.add_suspicious_activity(client_ip, "unauthorized_admin_access")
        security_incidents.labels(
            incident_type="unauthorized_admin_access", severity="high"
        ).inc()

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required"
        )
    return current_user


def require_tenant_access(
    tenant_id: str,
    request: Request,
    current_user: User = Depends(verify_token_with_rate_limit),
):
    if current_user.role != "admin" and current_user.tenant_id != tenant_id:
        # 記錄跨租戶存取嘗試
        client_ip = request.client.host
        ip_blacklist.add_suspicious_activity(client_ip, "cross_tenant_access")
        security_incidents.labels(
            incident_type="cross_tenant_access", severity="high"
        ).inc()

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: insufficient permissions for this tenant",
        )
    return current_user


# 異常檢測和監控類
class AIServiceMonitor:
    def __init__(self):
        self.request_history = defaultdict(
            lambda: deque(maxlen=100)
        )  # 保留最近100個請求
        self.concurrent_requests = defaultdict(int)
        self.baseline_metrics = {}
        self.alert_thresholds = {
            "request_rate_spike": 5.0,  # 請求率異常倍數
            "error_rate_threshold": 0.1,  # 錯誤率閾值 10%
            "response_time_spike": 2.0,  # 回應時間異常倍數
            "concurrent_limit": 50,  # 併發請求限制
        }

    def record_request(self, tenant_id: str, model: str, duration: float, status: str):
        """記錄請求資訊用於異常檢測"""
        timestamp = datetime.utcnow()
        request_data = {
            "timestamp": timestamp,
            "duration": duration,
            "status": status,
            "model": model,
        }
        self.request_history[tenant_id].append(request_data)

        # 檢測異常
        self._detect_anomalies(tenant_id)

    def _detect_anomalies(self, tenant_id: str):
        """檢測異常模式"""
        history = self.request_history[tenant_id]
        if len(history) < 10:  # 需要足夠的歷史資料
            return

        recent_requests = [
            r
            for r in history
            if r["timestamp"] > datetime.utcnow() - timedelta(minutes=5)
        ]

        # 1. 檢測流量暴增
        current_rate = len(recent_requests) / 5.0  # 每分鐘請求數
        baseline_rate = self.baseline_metrics.get(
            f"{tenant_id}_request_rate", current_rate
        )

        if current_rate > baseline_rate * self.alert_thresholds["request_rate_spike"]:
            traffic_spike_detected.labels(tenant=tenant_id).inc()
            anomaly_detection_alerts.labels(
                tenant=tenant_id, alert_type="traffic_spike"
            ).inc()
            logger.warning(
                f"🚨 流量暴增檢測: 租戶 {tenant_id}, 當前: {current_rate:.1f}/min, 基準: {baseline_rate:.1f}/min"
            )

        # 2. 檢測錯誤率異常
        error_requests = [r for r in recent_requests if r["status"] != "success"]
        error_rate = (
            len(error_requests) / len(recent_requests) if recent_requests else 0
        )

        if error_rate > self.alert_thresholds["error_rate_threshold"]:
            anomaly_detection_alerts.labels(
                tenant=tenant_id, alert_type="high_error_rate"
            ).inc()
            logger.warning(f"🚨 錯誤率異常: 租戶 {tenant_id}, 錯誤率: {error_rate:.1%}")

        # 3. 檢測回應時間異常
        recent_durations = [r["duration"] for r in recent_requests]
        if recent_durations:
            avg_duration = sum(recent_durations) / len(recent_durations)
            baseline_duration = self.baseline_metrics.get(
                f"{tenant_id}_avg_duration", avg_duration
            )

            if (
                avg_duration
                > baseline_duration * self.alert_thresholds["response_time_spike"]
            ):
                anomaly_detection_alerts.labels(
                    tenant=tenant_id, alert_type="slow_response"
                ).inc()
                logger.warning(
                    f"🚨 回應時間異常: 租戶 {tenant_id}, 當前: {avg_duration:.2f}s, 基準: {baseline_duration:.2f}s"
                )

        # 更新基準指標
        self._update_baseline_metrics(
            tenant_id,
            current_rate,
            sum(recent_durations) / len(recent_durations) if recent_durations else 0,
        )

    def _update_baseline_metrics(
        self, tenant_id: str, request_rate: float, avg_duration: float
    ):
        """更新基準指標 (使用指數移動平均)"""
        alpha = 0.1  # 平滑係數

        current_rate_key = f"{tenant_id}_request_rate"
        current_duration_key = f"{tenant_id}_avg_duration"

        if current_rate_key in self.baseline_metrics:
            self.baseline_metrics[current_rate_key] = (
                1 - alpha
            ) * self.baseline_metrics[current_rate_key] + alpha * request_rate
        else:
            self.baseline_metrics[current_rate_key] = request_rate

        if current_duration_key in self.baseline_metrics:
            self.baseline_metrics[current_duration_key] = (
                1 - alpha
            ) * self.baseline_metrics[current_duration_key] + alpha * avg_duration
        else:
            self.baseline_metrics[current_duration_key] = avg_duration

    def increment_concurrent(self, tenant_id: str):
        """增加併發請求計數"""
        self.concurrent_requests[tenant_id] += 1
        llm_concurrent_requests.labels(tenant=tenant_id).set(
            self.concurrent_requests[tenant_id]
        )

        # 檢查併發限制
        if (
            self.concurrent_requests[tenant_id]
            > self.alert_thresholds["concurrent_limit"]
        ):
            anomaly_detection_alerts.labels(
                tenant=tenant_id, alert_type="high_concurrency"
            ).inc()
            logger.warning(
                f"🚨 併發請求過高: 租戶 {tenant_id}, 當前併發: {self.concurrent_requests[tenant_id]}"
            )

    def decrement_concurrent(self, tenant_id: str):
        """減少併發請求計數"""
        if self.concurrent_requests[tenant_id] > 0:
            self.concurrent_requests[tenant_id] -= 1
            llm_concurrent_requests.labels(tenant=tenant_id).set(
                self.concurrent_requests[tenant_id]
            )


# 系統監控類
class SystemMonitor:
    def __init__(self):
        self.monitoring = True
        self.monitor_thread = None

    def start_monitoring(self):
        """啟動系統監控"""
        if self.monitor_thread is None or not self.monitor_thread.is_alive():
            self.monitoring = True
            self.monitor_thread = threading.Thread(
                target=self._monitor_loop, daemon=True
            )
            self.monitor_thread.start()
            logger.info("✅ 系統監控已啟動")

    def stop_monitoring(self):
        """停止系統監控"""
        self.monitoring = False
        if self.monitor_thread:
            self.monitor_thread.join(timeout=1)
        logger.info("⏹️ 系統監控已停止")

    def _monitor_loop(self):
        """監控循環"""
        current_proccess = psutil.Process()
        while self.monitoring:
            try:
                # CPU 使用率
                cpu_percent = psutil.cpu_percent(interval=1)
                system_cpu_usage.set(cpu_percent)

                # 記憶體使用率
                memory = psutil.virtual_memory()
                system_memory_usage.set(memory.used)

                # 網路連線數
                connections = current_proccess.net_connections()
                conn_states = defaultdict(int)
                for conn in connections:
                    conn_states[conn.status] += 1

                for state, count in conn_states.items():
                    network_connections.labels(state=state).set(count)

                # 模擬 GPU 使用率 (實際環境中應該使用 nvidia-ml-py)
                import random

                for gpu_id in range(2):  # 假設有2張GPU
                    gpu_util = random.uniform(20, 80)  # 模擬GPU使用率
                    llm_gpu_utilization.labels(tenant="system", gpu_id=str(gpu_id)).set(
                        gpu_util
                    )

                time.sleep(5)  # 每5秒更新一次

            except Exception as e:
                logger.error(f"系統監控錯誤: {e}")
                time.sleep(10)


# 初始化監控器
ai_monitor = AIServiceMonitor()
system_monitor = SystemMonitor()


@app.on_event("startup")
async def startup_event():
    """應用啟動時的初始化"""
    logger.info("🚀 FastAPI 應用啟動中...")

    # 啟動系統監控
    system_monitor.start_monitoring()

    # 初始化基準指標
    logger.info("📊 監控系統已啟動")


@app.on_event("shutdown")
async def shutdown_event():
    """應用關閉時的清理"""
    logger.info("⏹️ FastAPI 應用關閉中...")

    # 停止系統監控
    system_monitor.stop_monitoring()

    logger.info("✅ 監控系統已停止")


def detect_prompt_injection(prompt: str, tenant_id: str = "unknown") -> bool:
    """檢測 Prompt Injection 攻擊"""
    prompt_lower = prompt.lower()

    for pattern in PROMPT_INJECTION_PATTERNS:
        if re.search(pattern, prompt_lower, re.IGNORECASE):
            attack_type = pattern.replace("\\s+", "_").replace("\\", "")
            llm_prompt_injection_detected.labels(
                tenant=tenant_id, attack_type=attack_type
            ).inc()
            logger.warning(f"🚨 Prompt Injection 檢測到: {pattern} | 租戶: {tenant_id}")
            return True

    return False


# 安全相關 API 端點
@app.post("/auth/login", response_model=Token)
async def login(user_credentials: UserLogin):
    """使用者登入並取得 JWT Token"""
    user = authenticate_user(user_credentials.username, user_credentials.password)
    if not user:
        auth_failures_total.labels(reason="invalid_credentials").inc()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user["username"]}, expires_delta=access_token_expires
    )

    logger.info(f"✅ 使用者 {user['username']} 登入成功 (角色: {user['role']})")

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "role": user["role"],
        "tenant_id": user["tenant_id"],
    }


@app.get("/auth/me", response_model=User)
async def read_users_me(current_user: User = Depends(verify_token)):
    """取得目前使用者資訊"""
    return current_user


@app.post("/ai/chat")
async def ai_chat_endpoint(
    request: Request,
    ai_request: AIRequest,
    current_user: User = Depends(verify_token_with_rate_limit),
):
    """AI 聊天端點 - 具備完整安全防護、惡意行為控制和 Guardrails 驗證"""
    start_time = time.time()
    tenant_id = ai_request.tenant_id or current_user.tenant_id
    model = ai_request.model
    client_ip = request.client.host

    # 增加併發計數
    ai_monitor.increment_concurrent(tenant_id)

    try:
        # 1. 權限檢查
        if ai_request.tenant_id:
            require_tenant_access(ai_request.tenant_id, request, current_user)

        # 2. Guardrails 內容安全驗證 (新增)
        guardrails_result = guardrails_protection.validate_prompt(
            ai_request.prompt, current_user.username
        )

        # 記錄 Guardrails 驗證結果
        guardrails_validations.labels(
            result="safe" if guardrails_result["is_safe"] else "blocked"
        ).inc()

        guardrails_risk_score.labels(user_id=current_user.username).observe(
            guardrails_result["risk_score"]
        )

        # 記錄警告
        for warning in guardrails_result["warnings"]:
            guardrails_warnings.labels(
                user_id=current_user.username, warning_type=warning["type"]
            ).inc()

            # PII 檢測特別記錄
            if warning["type"] == "pii_detected":
                pii_detected.labels(
                    pii_type=warning.get("pii_type", "unknown"),
                    user_id=current_user.username,
                ).inc()

        # 如果 Guardrails 檢測到違規，阻斷請求
        if not guardrails_result["is_safe"]:
            # 記錄違規
            for violation in guardrails_result["violations"]:
                guardrails_violations.labels(
                    user_id=current_user.username, violation_type=violation["type"]
                ).inc()

                # 毒性內容特別記錄
                if violation["type"] == "toxic_language":
                    toxic_content_blocked.labels(
                        toxicity_level="high"
                        if violation["severity"] == "critical"
                        else "medium"
                    ).inc()

            # 記錄可疑活動
            ip_blacklist.add_suspicious_activity(client_ip, "guardrails_violation")
            security_incidents.labels(
                incident_type="guardrails_violation", severity="high"
            ).inc()

            llm_requests_total.labels(
                tenant=tenant_id, status="blocked_guardrails", model=model
            ).inc()
            blocked_requests_total.labels(
                block_reason="guardrails_violation", ip=client_ip
            ).inc()

            # 構建詳細錯誤訊息
            violation_details = "; ".join(
                [
                    f"{v['type']}: {v['message']}"
                    for v in guardrails_result["violations"]
                ]
            )

            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Content safety violation detected. {violation_details}",
                headers={
                    "X-Guardrails-Risk-Score": str(guardrails_result["risk_score"])
                },
            )

        # 3. 進階 Prompt Injection 檢測
        if detect_prompt_injection(ai_request.prompt, tenant_id):
            # 記錄惡意 Prompt 嘗試
            ip_blacklist.add_suspicious_activity(client_ip, "prompt_injection")
            security_incidents.labels(
                incident_type="prompt_injection", severity="high"
            ).inc()

            llm_requests_total.labels(
                tenant=tenant_id, status="blocked_injection", model=model
            ).inc()
            blocked_requests_total.labels(
                block_reason="prompt_injection", ip=client_ip
            ).inc()

            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Malicious prompt detected. Request blocked for security reasons.",
            )

        # 4. 內容長度檢查 (防止 DoS 攻擊)
        if len(ai_request.prompt) > 10000:  # 10KB 限制
            ip_blacklist.add_suspicious_activity(client_ip, "oversized_prompt")
            security_incidents.labels(
                incident_type="oversized_prompt", severity="medium"
            ).inc()
            blocked_requests_total.labels(
                block_reason="oversized_prompt", ip=client_ip
            ).inc()

            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Prompt too large. Maximum 10KB allowed.",
            )

        # 5. 模擬 Token 計算和處理
        input_tokens = len(ai_request.prompt.split())
        output_tokens = random.randint(50, 200)

        # 5. 模擬 AI 處理
        processing_delay = random.uniform(0.5, 3.0)
        await asyncio.sleep(processing_delay)

        # 6. 模擬記憶體使用
        memory_usage = random.randint(1024 * 1024 * 100, 1024 * 1024 * 500)
        llm_memory_usage.labels(tenant=tenant_id, model=model).set(memory_usage)

        # 7. 生成回應
        response_text = f"Hello! I'm an AI assistant. Your prompt was: '{ai_request.prompt[:50]}...'"

        # 8. 記錄成功請求的詳細指標
        duration = time.time() - start_time
        llm_requests_total.labels(tenant=tenant_id, status="success", model=model).inc()
        llm_request_duration.labels(tenant=tenant_id, model=model).observe(duration)
        llm_tokens_processed.labels(tenant=tenant_id, model=model, type="input").inc(
            input_tokens
        )
        llm_tokens_processed.labels(tenant=tenant_id, model=model, type="output").inc(
            output_tokens
        )

        # 9. 記錄到異常檢測和行為分析系統
        ai_monitor.record_request(tenant_id, model, duration, "success")
        behavior_detector.record_activity(
            current_user.username, client_ip, "ai_chat", True
        )

        # 10. 計算並更新吞吐量
        current_throughput = 1.0 / duration if duration > 0 else 0
        llm_throughput.labels(tenant=tenant_id).set(current_throughput)

        logger.info(
            f"✅ AI 請求成功 | 使用者: {current_user.username} | 租戶: {tenant_id} | IP: {client_ip}"
        )

        return {
            "response": response_text,
            "model": model,
            "tenant_id": tenant_id,
            "user": current_user.username,
            "processing_time": f"{duration:.2f}s",
            "tokens": {
                "input": input_tokens,
                "output": output_tokens,
                "total": input_tokens + output_tokens,
            },
            "memory_usage_mb": memory_usage // (1024 * 1024),
            "security_status": "clean",
        }

    except HTTPException:
        # 記錄被攔截的請求
        duration = time.time() - start_time
        ai_monitor.record_request(tenant_id, model, duration, "blocked")
        behavior_detector.record_activity(
            current_user.username, client_ip, "ai_chat", False
        )
        raise
    except Exception as e:
        # 記錄錯誤
        duration = time.time() - start_time
        llm_requests_total.labels(tenant=tenant_id, status="error", model=model).inc()
        llm_error_rate.labels(tenant=tenant_id, error_type="processing_error").inc()
        ai_monitor.record_request(tenant_id, model, duration, "error")
        behavior_detector.record_activity(
            current_user.username, client_ip, "ai_chat", False
        )

        logger.error(f"❌ AI 請求失敗: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )
    finally:
        # 減少併發計數
        ai_monitor.decrement_concurrent(tenant_id)


@app.get("/metrics")
async def metrics():
    """Prometheus 監控指標端點"""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/metrics/dashboard")
async def metrics_dashboard(current_user: User = Depends(verify_token)):
    """監控儀表板資料 API"""
    tenant_id = current_user.tenant_id if current_user.role != "admin" else None

    # 獲取租戶的監控資料
    dashboard_data = {
        "tenant_id": tenant_id or "all",
        "user_role": current_user.role,
        "timestamp": datetime.utcnow().isoformat(),
        "metrics": {
            "concurrent_requests": ai_monitor.concurrent_requests.copy(),
            "baseline_metrics": ai_monitor.baseline_metrics.copy(),
            "alert_thresholds": ai_monitor.alert_thresholds.copy(),
        },
        "recent_alerts": _get_recent_alerts(tenant_id),
        "system_status": _get_system_status(),
    }

    return dashboard_data


@app.get("/metrics/alerts")
async def get_alerts(current_user: User = Depends(verify_token)):
    """獲取異常告警資訊"""
    tenant_id = current_user.tenant_id if current_user.role != "admin" else None
    alerts = _get_recent_alerts(tenant_id)

    return {"alerts": alerts, "total_count": len(alerts), "tenant_filter": tenant_id}


@app.post("/metrics/simulate-load")
async def simulate_load(
    current_user: User = Depends(require_admin),
    requests_count: int = 20,
    concurrent: bool = False,
):
    """模擬負載測試 - 僅管理員可用"""
    logger.info(
        f"🧪 管理員 {current_user.username} 啟動負載模擬: {requests_count} 個請求"
    )

    async def make_test_request(i):
        test_request = AIRequest(
            prompt=f"Load test request {i} - {random.choice(['Hello', 'Hi', 'Test', 'Demo'])}",
            model="qwen:0.5b",
        )

        # 模擬處理
        start = time.time()
        await asyncio.sleep(random.uniform(0.1, 1.0))
        duration = time.time() - start

        # 記錄指標
        tenant_id = current_user.tenant_id
        llm_requests_total.labels(
            tenant=tenant_id, status="success", model="qwen:0.5b"
        ).inc()
        llm_request_duration.labels(tenant=tenant_id, model="qwen:0.5b").observe(
            duration
        )
        ai_monitor.record_request(tenant_id, "qwen:0.5b", duration, "success")

        return f"Request {i} completed in {duration:.2f}s"

    if concurrent:
        # 併發執行
        tasks = [make_test_request(i) for i in range(requests_count)]
        results = await asyncio.gather(*tasks)
    else:
        # 序列執行
        results = []
        for i in range(requests_count):
            result = await make_test_request(i)
            results.append(result)

    return {
        "message": f"Load simulation completed: {requests_count} requests",
        "concurrent": concurrent,
        "results_count": len(results),
    }


def _get_recent_alerts(tenant_filter: Optional[str] = None) -> list:
    """獲取最近的告警 (模擬資料)"""
    # 在實際環境中，這裡會從 Prometheus 或告警系統獲取資料
    alerts = [
        {
            "timestamp": (datetime.utcnow() - timedelta(minutes=5)).isoformat(),
            "tenant": "company-a",
            "alert_type": "traffic_spike",
            "severity": "warning",
            "message": "Request rate increased by 300%",
        },
        {
            "timestamp": (datetime.utcnow() - timedelta(minutes=15)).isoformat(),
            "tenant": "company-b",
            "alert_type": "high_error_rate",
            "severity": "critical",
            "message": "Error rate exceeded 10%",
        },
    ]

    if tenant_filter:
        alerts = [a for a in alerts if a["tenant"] == tenant_filter]

    return alerts


@app.get("/security/status")
async def security_status(
    request: Request, current_user: User = Depends(verify_token_with_rate_limit)
):
    """安全狀態查詢"""
    client_ip = request.client.host

    return {
        "user": current_user.username,
        "ip": client_ip,
        "security_status": {
            "ip_blacklisted": ip_blacklist.is_blacklisted(client_ip),
            "suspicious_activity_count": ip_blacklist.suspicious_ips.get(
                client_ip, {}
            ).get("count", 0),
            "rate_limit_status": "normal",  # 簡化顯示
            "last_activity": datetime.utcnow().isoformat(),
        },
        "permissions": {
            "role": current_user.role,
            "tenant_id": current_user.tenant_id,
            "admin_access": current_user.role == "admin",
        },
    }


@app.get("/security/blacklist")
async def get_blacklist(request: Request, current_user: User = Depends(require_admin)):
    """查看 IP 黑名單 - 僅管理員"""
    return {
        "blacklisted_ips": list(ip_blacklist.blacklisted_ips),
        "suspicious_ips": dict(ip_blacklist.suspicious_ips),
        "total_blacklisted": len(ip_blacklist.blacklisted_ips),
        "total_suspicious": len(ip_blacklist.suspicious_ips),
    }


class IPBlockRequest(BaseModel):
    ip_address: str = Field(..., description="要封鎖的 IP 地址")
    reason: str = Field(..., description="封鎖原因")


class IPUnblockRequest(BaseModel):
    ip_address: str = Field(..., description="要解除封鎖的 IP 地址")


@app.post("/security/unblock-ip")
async def unblock_ip(
    request: Request,
    unblock_request: IPUnblockRequest,
    current_user: User = Depends(require_admin)
):
    """解除 IP 封鎖 - 僅管理員"""
    ip_address = unblock_request.ip_address
    ip_blacklist.unblock_ip(ip_address)

    # 記錄管理員操作
    security_actions_taken.labels(action="ip_unblocked", reason="admin_action").inc()
    logger.info(f"🔓 管理員 {current_user.username} 解除 IP 封鎖: {ip_address}")

    return {
        "message": f"IP {ip_address} has been unblocked",
        "action_by": current_user.username,
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.post("/security/block-ip")
async def block_ip(
    request: Request,
    block_request: IPBlockRequest,
    current_user: User = Depends(require_admin),
):
    """手動封鎖 IP - 僅管理員"""
    ip_address = block_request.ip_address
    reason = block_request.reason
    
    ip_blacklist.blacklist_ip(ip_address, f"管理員手動封鎖: {reason}")

    # 記錄管理員操作
    security_actions_taken.labels(
        action="ip_blocked_manual", reason="admin_action"
    ).inc()
    logger.info(
        f"🚫 管理員 {current_user.username} 手動封鎖 IP: {ip_address}, 原因: {reason}"
    )

    return {
        "message": f"IP {ip_address} has been blocked",
        "reason": reason,
        "action_by": current_user.username,
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.get("/security/incidents")
async def get_security_incidents(
    request: Request, current_user: User = Depends(require_admin)
):
    """查看安全事件 - 僅管理員"""

    # 模擬最近的安全事件
    incidents = [
        {
            "timestamp": (datetime.utcnow() - timedelta(minutes=5)).isoformat(),
            "type": "prompt_injection",
            "severity": "high",
            "ip": "192.168.1.100",
            "user": "user1",
            "details": "Detected SQL injection attempt in prompt",
        },
        {
            "timestamp": (datetime.utcnow() - timedelta(minutes=15)).isoformat(),
            "type": "rate_limit_violation",
            "severity": "medium",
            "ip": "10.0.0.50",
            "user": "anonymous",
            "details": "Exceeded rate limit for unauthenticated requests",
        },
        {
            "timestamp": (datetime.utcnow() - timedelta(hours=1)).isoformat(),
            "type": "unauthorized_admin_access",
            "severity": "high",
            "ip": "172.16.0.25",
            "user": "user1",
            "details": "Attempted to access admin-only endpoint",
        },
    ]

    return {
        "incidents": incidents,
        "total_count": len(incidents),
        "query_by": current_user.username,
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.get("/guardrails/status")
async def guardrails_status(
    request: Request, current_user: User = Depends(verify_token_with_rate_limit)
):
    """查詢 Guardrails 狀態"""
    safety_report = guardrails_protection.get_safety_report()

    return {
        "user": current_user.username,
        "guardrails_status": safety_report,
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.post("/guardrails/validate")
async def validate_content(
    request: Request,
    content: str,
    current_user: User = Depends(verify_token_with_rate_limit),
):
    """手動驗證內容安全性 - 測試用"""
    validation_result = guardrails_protection.validate_prompt(
        content, current_user.username
    )

    return {
        "user": current_user.username,
        "validation_result": validation_result,
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.get("/guardrails/report")
async def guardrails_report(
    request: Request, current_user: User = Depends(require_admin)
):
    """獲取 Guardrails 安全報告 - 僅管理員"""

    # 模擬統計資料
    report = {
        "summary": {
            "total_validations": 1250,
            "blocked_requests": 87,
            "warnings_issued": 234,
            "average_risk_score": 0.23,
        },
        "top_violations": [
            {"type": "toxic_language", "count": 45},
            {"type": "pii_detected", "count": 28},
            {"type": "length_exceeded", "count": 14},
        ],
        "top_warnings": [
            {"type": "sensitive_topic", "count": 156},
            {"type": "pii_detected", "count": 78},
        ],
        "safety_rules": guardrails_protection.safety_rules,
        "guardrails_enabled": guardrails_protection.enabled,
    }

    return {
        "report": report,
        "generated_by": current_user.username,
        "timestamp": datetime.utcnow().isoformat(),
    }


def _get_system_status() -> dict:
    """獲取系統狀態"""
    try:
        cpu_percent = psutil.cpu_percent()
        memory = psutil.virtual_memory()

        return {
            "cpu_usage": cpu_percent,
            "memory_usage": {
                "used_gb": memory.used / (1024**3),
                "total_gb": memory.total / (1024**3),
                "percent": memory.percent,
            },
            "status": "healthy"
            if cpu_percent < 80 and memory.percent < 80
            else "warning",
        }
    except Exception as e:
        logger.error(f"獲取系統狀態失敗: {e}")
        return {"status": "unknown", "error": str(e)}


@app.get("/health")
async def health_check():
    """健康檢查端點"""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "redis_connected": redis_client is not None,
    }


# 核心基礎設施函數
def parse_storage_to_bytes(size_str: str) -> int:
    """將例如 '50Gi' 的字串轉換為 Harbor 需要的 Bytes"""
    try:
        if size_str.endswith("Gi"):
            return int(size_str[:-2]) * (1024**3)
        elif size_str.endswith("Mi"):
            return int(size_str[:-2]) * (1024**2)
        return int(size_str)  # 假設直接傳入數字則視為 Bytes
    except Exception:
        logger.warning(f"無法解析容量 {size_str}，使用預設值 5GB")
        return 5368709120  # 預設 5GB


# 定義資料合約 (Data Models)
class QuotaSpec(BaseModel):
    tpm_limit: int = 100000  # 設定預設值
    rpm_limit: int = 1000  # 設定預設值


class ComputeResources(BaseModel):
    cpu_limit: str = "2"  # 設定預設值
    memory_limit: str = "4Gi"  # 設定預設值
    model_name: str = "qwen:0.5b"


class TenantCreateRequest(BaseModel):
    tenant_name: str
    gpu_limit: int
    storage_quota: str
    admin_email: str

    tier: str = "premium"
    quota: QuotaSpec = Field(default_factory=QuotaSpec)
    compute_resources: ComputeResources = Field(default_factory=ComputeResources)


# 核心基礎設施函數
def create_k8s_namespace(api_instance, namespace_name):
    ns = client.V1Namespace(metadata=client.V1ObjectMeta(name=namespace_name))
    try:
        api_instance.create_namespace(body=ns)
        logger.info(f" Namespace {namespace_name} 建立成功")
    except ApiException as e:
        if e.status != 409:
            raise e


def create_k8s_service(core_api, tenant_name, namespace):
    """為租戶的 LLM Pod 建立內部通訊用的 K8s Service"""
    svc_name = f"llm-backend-{tenant_name}"
    svc_body = client.V1Service(
        metadata=client.V1ObjectMeta(name=svc_name, namespace=namespace),
        spec=client.V1ServiceSpec(
            selector={"app": "llm-backend", "tenant": tenant_name},
            ports=[
                client.V1ServicePort(port=11434, target_port=11434, name="http-llm")
            ],
        ),
    )
    try:
        core_api.create_namespaced_service(namespace=namespace, body=svc_body)
        logger.info(f" Service {svc_name} 建立成功，已綁定內部 DNS")
    except ApiException as e:
        if e.status != 409:
            raise e


def create_cilium_network_policy(custom_api, tenant_name, namespace):
    """動態建立 Cilium 隔離政策"""
    policy_name = f"strict-isolation-{tenant_name}"
    cnp_body = {
        "apiVersion": "cilium.io/v2",
        "kind": "CiliumNetworkPolicy",
        "metadata": {"name": policy_name, "namespace": namespace},
        "spec": {
            "endpointSelector": {"matchLabels": {"tenant": tenant_name}},
            "ingress": [
                {
                    "fromEndpoints": [
                        {
                            "matchLabels": {
                                "app": "litellm-gateway",
                                "k8s:io.kubernetes.pod.namespace": "ai-system",
                            }
                        }
                    ],
                    "toPorts": [{"ports": [{"port": "11434", "protocol": "TCP"}]}],
                },
                {
                    "fromEndpoints": [
                        {
                            "matchLabels": {
                                "k8s:io.kubernetes.pod.namespace": "monitoring"
                            }
                        }
                    ],
                    "toPorts": [{"ports": [{"port": "9400", "protocol": "TCP"}]}],
                },
            ],
            "egress": [
                {
                    "toEndpoints": [
                        {
                            "matchLabels": {
                                "k8s:io.kubernetes.pod.namespace": "kube-system",
                                "k8s-app": "kube-dns",
                            }
                        }
                    ],
                    "toPorts": [{"ports": [{"port": "53", "protocol": "ANY"}]}],
                },
                {
                    "toEndpoints": [
                        {
                            "matchLabels": {
                                "app": "litellm-gateway",
                                "k8s:io.kubernetes.pod.namespace": "ai-system",
                            }
                        }
                    ],
                    "toPorts": [{"ports": [{"port": "4000", "protocol": "TCP"}]}],
                },
                # 允許對外下載模型
                {
                    "toEntities": ["world"],
                    "toPorts": [{"ports": [{"port": "443", "protocol": "TCP"}]}],
                },
            ],
        },
    }
    try:
        custom_api.create_namespaced_custom_object(
            "cilium.io", "v2", namespace, "ciliumnetworkpolicies", cnp_body
        )
        logger.info(f" Cilium 隔離政策 {policy_name} 已套用")
    except ApiException as e:
        if e.status != 409:
            raise e


def deploy_tenant_llm_pod(apps_api, request: TenantCreateRequest):
    """部署 Ollama，並綁定 GPU 限制與 DCGM"""
    namespace = f"tenant-{request.tenant_name}"
    dep_body = {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {
            "name": f"llm-backend-{request.tenant_name}",
            "namespace": namespace,
        },
        "spec": {
            "replicas": 1,
            "selector": {
                "matchLabels": {"app": "llm-backend", "tenant": request.tenant_name}
            },
            "template": {
                "metadata": {
                    "labels": {"app": "llm-backend", "tenant": request.tenant_name}
                },
                "spec": {
                    "priorityClassName": "premium-tier"
                    if request.tier == "premium"
                    else "free-tier",
                    "containers": [
                        {
                            "name": "ollama",
                            "image": "ollama/ollama:latest",
                            "resources": {
                                "limits": {
                                    "cpu": request.compute_resources.cpu_limit,
                                    "memory": request.compute_resources.memory_limit,
                                    "nvidia.com/gpu": str(
                                        request.gpu_limit
                                    ),  # 動態帶入 GPU 限制
                                }
                            },
                        },
                        {
                            "name": "mock-dcgm-exporter",
                            "image": "my-mock-dcgm:v1",
                            "env": [
                                {"name": "TENANT_ID", "value": request.tenant_name},
                                {
                                    "name": "LITELLM_METRICS_URL",
                                    "value": "http://litellm-gateway.ai-system.svc.cluster.local:4000/metrics",
                                },
                            ],
                        },
                    ],
                },
            },
        },
    }
    try:
        apps_api.create_namespaced_deployment(namespace=namespace, body=dep_body)
        logger.info(
            f" Deployment llm-backend-{request.tenant_name} 建立成功 (配置 {request.gpu_limit} 張 GPU)"
        )
    except ApiException as e:
        if e.status != 409:
            raise e


# 外部服務整合 (LiteLLM)
async def generate_litellm_key(request: TenantCreateRequest) -> str:
    litellm_url = "http://localhost:4000/key/generate"
    payload = {
        "models": [request.compute_resources.model_name],
        "tpm_limit": request.quota.tpm_limit,
        "rpm_limit": request.quota.rpm_limit,
        "metadata": {
            "tenant_name": request.tenant_name,
            "admin_email": request.admin_email,  # 將負責人 Email 寫入 API Key Metadata
        },
    }
    headers = {"Authorization": "Bearer sk-master-key"}

    async with httpx.AsyncClient() as h_client:
        try:
            response = await h_client.post(
                litellm_url, json=payload, headers=headers, timeout=10.0
            )
            response.raise_for_status()
            logger.info(f" LiteLLM API Key 建立成功 (綁定信箱: {request.admin_email})")
            return response.json().get("key", "N/A")
        except Exception as e:
            logger.warning(f" LiteLLM API Key 產生失敗，使用預設值。錯誤: {e}")
            return "sk-lite-mock-key-for-demo"


# 外部服務整合 (真實呼叫 Harbor API)
async def create_harbor_project(tenant_name: str, storage_quota_str: str) -> int:
    """真實呼叫 Harbor API 為租戶建立專屬空間，並動態設定容量上限"""
    harbor_url = "http://localhost:8088/api/v2.0/projects"
    auth_string = base64.b64encode(b"admin:Harbor12345").decode("utf-8")
    headers = {
        "Authorization": f"Basic {auth_string}",
        "Content-Type": "application/json",
    }

    project_name = f"tenant-{tenant_name}"
    storage_limit_bytes = parse_storage_to_bytes(
        storage_quota_str
    )  #  轉換 "50Gi" 為 Bytes

    payload = {
        "project_name": project_name,
        "public": False,  # 確保是私有空間
        "storage_limit": storage_limit_bytes,  # 套用客製化容量限制
    }

    async with httpx.AsyncClient() as client_http:
        # 1. 發送 POST 建立專案請求
        response = await client_http.post(
            harbor_url, json=payload, headers=headers, timeout=10.0
        )

        if response.status_code == 201:
            location = response.headers.get("Location", "")
            try:
                project_id = int(location.split("/")[-1])
                logger.info(
                    f" Harbor 專案 {project_name} 建立成功 (容量限制: {storage_quota_str}), 取得 ID: {project_id}"
                )
                return project_id
            except ValueError:
                logger.warning(
                    "建立成功，但無法從 Location Header 解析 ID，嘗試 GET 重新查詢。"
                )

        elif response.status_code == 409:
            logger.info(f" Harbor 專案 {project_name} 已經存在，正在讀取現有 ID...")

        else:
            logger.error(f" Harbor API 錯誤: {response.text}")
            response.raise_for_status()

        # 2. 若專案已存在 (409) 或 Location 解析失敗，改用 GET 查詢
        get_url = f"{harbor_url}?name={project_name}"
        get_resp = await client_http.get(get_url, headers=headers, timeout=10.0)
        get_resp.raise_for_status()

        projects = get_resp.json()
        if projects and len(projects) > 0:
            project_id = projects[0].get("project_id")
            logger.info(
                f" 成功取得已存在的 Harbor 專案 {project_name} ID: {project_id}"
            )
            return project_id

        raise Exception(f"無法在 Harbor 中找到或建立專案: {project_name}")


# 核心 API 端點 (需要管理員權限)
@app.post("/api/v1/tenants", status_code=201)
async def provision_tenant(
    request: TenantCreateRequest,
    current_user: User = Depends(require_admin),  # 只有管理員可以建立租戶
):
    """建立新租戶 - 需要管理員權限"""
    try:
        config.load_kube_config()
        core_api, apps_api, custom_api = (
            client.CoreV1Api(),
            client.AppsV1Api(),
            client.CustomObjectsApi(),
        )

        namespace_name = f"tenant-{request.tenant_name}"
        priority_class = "premium-tier" if request.tier == "premium" else "free-tier"

        logger.info(
            f"🔧 管理員 {current_user.username} 正在建立租戶: {request.tenant_name}"
        )

        # 基礎設施部署
        create_k8s_namespace(core_api, namespace_name)
        create_k8s_service(core_api, request.tenant_name, namespace_name)
        create_cilium_network_policy(custom_api, request.tenant_name, namespace_name)

        # 改為直接傳入整個 request 物件
        deploy_tenant_llm_pod(apps_api, request)

        # 改為直接傳入整個 request 物件
        api_key = await generate_litellm_key(request)

        # 呼叫 Harbor 分配專屬倉庫 (帶入 storage_quota)
        harbor_id = await create_harbor_project(
            request.tenant_name, request.storage_quota
        )

        # 記錄成功的租戶建立
        llm_requests_total.labels(
            tenant=request.tenant_name, status="tenant_created"
        ).inc()

        return {
            "status": "success",
            "message": "Tenant provisioned successfully.",
            "created_by": current_user.username,
            "data": {
                "tenant_id": request.tenant_name,
                "admin_email": request.admin_email,
                "infrastructure": {
                    "k8s_namespace": namespace_name,
                    "priority_class": priority_class,
                    "harbor_project_id": harbor_id,
                    "allocated_gpu": request.gpu_limit,
                    "storage_quota": request.storage_quota,
                },
                "gateway": {
                    "assigned_api_key": api_key,
                    "gateway_endpoint": "http://litellm.ai-system.svc.cluster.local:4000",
                },
                "observability": {
                    "grafana_dashboard_url": f"http://grafana.local/d/tenant-monitor?var-tenant={request.tenant_name}"
                },
            },
        }

    except Exception as e:
        logger.error(f"❌ 租戶建立失敗 (操作者: {current_user.username}): {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/tenants")
async def list_tenants(current_user: User = Depends(verify_token)):
    """列出租戶 - 管理員可看全部，一般使用者只能看自己的"""
    if current_user.role == "admin":
        # 管理員可以看到所有租戶 (這裡簡化為示例)
        return {
            "tenants": ["company-a", "company-b", "company-c"],
            "total": 3,
            "user_role": "admin",
        }
    else:
        # 一般使用者只能看到自己的租戶
        return {
            "tenants": [current_user.tenant_id],
            "total": 1,
            "user_role": "basic_user",
        }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
