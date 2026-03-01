import os
import time
import random
import requests
from prometheus_client import start_http_server, Gauge

# 環境變數與 Metadata 初始化
TENANT_ID = os.getenv("TENANT_ID", "default-tenant")
NAMESPACE = f"tenant-{TENANT_ID}"
GPU_UUID = f"MOCK-GPU-{TENANT_ID.upper()}-001"
POD_NAME = os.getenv("HOSTNAME", "mock-pod-x")

LITELLM_METRICS_URL = os.getenv(
    "LITELLM_METRICS_URL", "http://litellm.ai-system.svc.cluster.local:4000/metrics"
)

# 定義進階 Mock 指標
# 基礎指標：使用率與功耗
gpu_util_gauge = Gauge(
    "DCGM_FI_DEV_GPU_UTIL", "GPU Utilization (%)", ["namespace", "pod", "gpu"]
)
gpu_power_gauge = Gauge(
    "DCGM_FI_DEV_POWER_USAGE", "GPU Power Usage (W)", ["namespace", "pod", "gpu"]
)

# 新增：顯存佔用 (FB_USED) - 模擬模型載入後的靜態佔用
gpu_mem_gauge = Gauge(
    "DCGM_FI_DEV_FB_USED", "GPU Framebuffer Used (MB)", ["namespace", "pod", "gpu"]
)

# 新增：硬體降頻告警 (0: 正常, 1: 降頻)
gpu_slowdown_gauge = Gauge(
    "DCGM_ST_HW_SLOWDOWN", "Hardware Throttle Status", ["namespace", "pod", "gpu"]
)


# 模擬狀態控制 (用於平滑過渡)
class GPUSimulator:
    def __init__(self):
        self.current_util = 0.0
        self.current_power = 30.0
        self.base_mem_usage = random.uniform(8000.0, 8500.0)
        self.lerp_factor = 0.2  # 平滑係數：數值每步移動目標差距的 20% (模擬熱身/冷卻)

    def get_target_metrics(self, is_active):
        if is_active:
            return random.uniform(75.0, 95.0), random.uniform(180.0, 250.0)
        else:
            return random.uniform(0.0, 5.0), random.uniform(30.0, 45.0)

    def update(self, is_active):
        target_util, target_power = self.get_target_metrics(is_active)

        # 1. 實現熱身與冷卻 (線性插值 LERP)
        self.current_util += (target_util - self.current_util) * self.lerp_factor
        self.current_power += (target_power - self.current_power) * self.lerp_factor

        # 2. 模擬顯存：推論時會額外增加一點動態顯存 (KV Cache)
        dynamic_mem = random.uniform(200.0, 500.0) if is_active else 0.0
        total_mem = self.base_mem_usage + dynamic_mem

        # 3. 模擬隨機硬體降頻 (Error Simulation)
        # 設定極低機率 (1%) 觸發降頻，用來測試告警系統
        slowdown_status = 1 if random.random() < 0.01 else 0

        # 更新 Prometheus 指標
        labels = {"namespace": NAMESPACE, "pod": POD_NAME, "gpu": GPU_UUID}
        gpu_util_gauge.labels(**labels).set(self.current_util)
        gpu_power_gauge.labels(**labels).set(self.current_power)
        gpu_mem_gauge.labels(**labels).set(total_mem)
        gpu_slowdown_gauge.labels(**labels).set(slowdown_status)

        status_str = "RUNNING" if is_active else "IDLE"
        print(
            f"[{NAMESPACE}] Status: {status_str} | Util: {self.current_util:.1f}% | "
            f"Power: {self.current_power:.1f}W | Mem: {total_mem:.0f}MB | Slowdown: {slowdown_status}"
        )


def check_litellm_traffic():
    """向 LiteLLM 請求 Metrics 端點"""
    try:
        # 模擬實際生產環境，這裡會檢查租戶特定的計數器是否增長
        response = requests.get(LITELLM_METRICS_URL, timeout=1)
        if response.status_code == 200:
            return f'tenant_id="{TENANT_ID}"' in response.text
    except:
        pass
    return False


if __name__ == "__main__":
    start_http_server(9400)
    print(f"* Enhanced Mock DCGM Exporter started on port 9400")
    print(f"* Target Tenant: {TENANT_ID} | GPU: {GPU_UUID}")

    simulator = GPUSimulator()

    while True:
        # 獲取真實流量狀態
        has_traffic = check_litellm_traffic()

        if random.random() < 0.2:
            has_traffic = True

        # 執行模擬器更新 (內含平滑邏輯)
        simulator.update(is_active=has_traffic)

        # 輪詢時間縮短至 1 秒，讓過渡曲線在 Grafana 上更流暢
        time.sleep(1)
