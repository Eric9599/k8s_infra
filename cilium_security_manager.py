#!/usr/bin/env python3
"""
Cilium 安全管理器 - 任務 C: 網路層隔離
動態生成和管理 Cilium Network Policy 來防止橫向移動
"""

import json
from datetime import datetime
from typing import Dict, List, Optional
import logging

logger = logging.getLogger(__name__)

class CiliumSecurityManager:
    def __init__(self):
        self.policies = {}
        self.blocked_ips = set()
        self.security_groups = {
            "ai-gateway": {
                "namespace": "ai-system",
                "labels": {"app": "litellm-gateway"},
                "allowed_ports": [4000]
            },
            "llm-backend": {
                "namespace": "tenant-*",
                "labels": {"app": "llm-backend"},
                "allowed_ports": [11434]
            },
            "monitoring": {
                "namespace": "monitoring",
                "labels": {"app": "prometheus"},
                "allowed_ports": [9090, 3000]
            }
        }
    
    def generate_strict_isolation_policy(self, tenant_name: str) -> Dict:
        """生成嚴格的租戶隔離政策"""
        namespace = f"tenant-{tenant_name}"
        policy_name = f"strict-isolation-{tenant_name}"
        
        policy = {
            "apiVersion": "cilium.io/v2",
            "kind": "CiliumNetworkPolicy",
            "metadata": {
                "name": policy_name,
                "namespace": namespace,
                "labels": {
                    "security.policy/type": "tenant-isolation",
                    "security.policy/tenant": tenant_name,
                    "security.policy/created-by": "security-manager"
                }
            },
            "spec": {
                "endpointSelector": {
                    "matchLabels": {"tenant": tenant_name}
                },
                "ingress": [
                    # 只允許 AI Gateway 進入
                    {
                        "fromEndpoints": [
                            {
                                "matchLabels": {
                                    "app": "litellm-gateway",
                                    "k8s:io.kubernetes.pod.namespace": "ai-system"
                                }
                            }
                        ],
                        "toPorts": [
                            {
                                "ports": [{"port": "11434", "protocol": "TCP"}]
                            }
                        ]
                    },
                    # 允許監控系統進入
                    {
                        "fromEndpoints": [
                            {
                                "matchLabels": {
                                    "k8s:io.kubernetes.pod.namespace": "monitoring"
                                }
                            }
                        ],
                        "toPorts": [
                            {
                                "ports": [{"port": "9400", "protocol": "TCP"}]
                            }
                        ]
                    }
                ],
                "egress": [
                    # DNS 查詢
                    {
                        "toEndpoints": [
                            {
                                "matchLabels": {
                                    "k8s:io.kubernetes.pod.namespace": "kube-system",
                                    "k8s-app": "kube-dns"
                                }
                            }
                        ],
                        "toPorts": [
                            {
                                "ports": [{"port": "53", "protocol": "ANY"}]
                            }
                        ]
                    },
                    # 允許連回 AI Gateway (用於健康檢查)
                    {
                        "toEndpoints": [
                            {
                                "matchLabels": {
                                    "app": "litellm-gateway",
                                    "k8s:io.kubernetes.pod.namespace": "ai-system"
                                }
                            }
                        ],
                        "toPorts": [
                            {
                                "ports": [{"port": "4000", "protocol": "TCP"}]
                            }
                        ]
                    },
                    # 允許 HTTPS 下載模型 (限制特定域名)
                    {
                        "toFQDNs": [
                            {"matchName": "huggingface.co"},
                            {"matchName": "ollama.ai"},
                            {"matchPattern": "*.huggingface.co"}
                        ],
                        "toPorts": [
                            {
                                "ports": [{"port": "443", "protocol": "TCP"}]
                            }
                        ]
                    }
                ]
            }
        }
        
        self.policies[policy_name] = policy
        return policy
    
    def generate_security_quarantine_policy(self, namespace: str, pod_labels: Dict[str, str]) -> Dict:
        """生成安全隔離政策 - 完全阻斷可疑 Pod"""
        policy_name = f"security-quarantine-{namespace}"
        
        policy = {
            "apiVersion": "cilium.io/v2",
            "kind": "CiliumNetworkPolicy",
            "metadata": {
                "name": policy_name,
                "namespace": namespace,
                "labels": {
                    "security.policy/type": "quarantine",
                    "security.policy/severity": "critical",
                    "security.policy/created-by": "security-manager"
                }
            },
            "spec": {
                "endpointSelector": {
                    "matchLabels": pod_labels
                },
                "ingress": [],  # 完全阻斷入站流量
                "egress": [
                    # 只允許 DNS (最小權限)
                    {
                        "toEndpoints": [
                            {
                                "matchLabels": {
                                    "k8s:io.kubernetes.pod.namespace": "kube-system",
                                    "k8s-app": "kube-dns"
                                }
                            }
                        ],
                        "toPorts": [
                            {
                                "ports": [{"port": "53", "protocol": "UDP"}]
                            }
                        ]
                    }
                ]
            }
        }
        
        self.policies[policy_name] = policy
        return policy
    
    def generate_ip_blocking_policy(self, blocked_ips: List[str], namespace: str = "default") -> Dict:
        """生成 IP 封鎖政策"""
        policy_name = f"ip-blocking-{namespace}"
        
        # 將 IP 轉換為 CIDR 格式
        blocked_cidrs = [f"{ip}/32" for ip in blocked_ips]
        
        policy = {
            "apiVersion": "cilium.io/v2",
            "kind": "CiliumNetworkPolicy",
            "metadata": {
                "name": policy_name,
                "namespace": namespace,
                "labels": {
                    "security.policy/type": "ip-blocking",
                    "security.policy/created-by": "security-manager"
                }
            },
            "spec": {
                "endpointSelector": {},  # 套用到所有 Pod
                "ingress": [
                    {
                        "fromCIDRSet": [
                            {"cidr": cidr, "except": []} for cidr in blocked_cidrs
                        ],
                        "toPorts": []  # 阻斷所有端口
                    }
                ]
            }
        }
        
        self.policies[policy_name] = policy
        return policy
    
    def generate_lateral_movement_prevention_policy(self, tenant_name: str) -> Dict:
        """生成防止橫向移動的政策"""
        namespace = f"tenant-{tenant_name}"
        policy_name = f"lateral-movement-prevention-{tenant_name}"
        
        policy = {
            "apiVersion": "cilium.io/v2",
            "kind": "CiliumNetworkPolicy",
            "metadata": {
                "name": policy_name,
                "namespace": namespace,
                "labels": {
                    "security.policy/type": "lateral-movement-prevention",
                    "security.policy/tenant": tenant_name
                }
            },
            "spec": {
                "endpointSelector": {
                    "matchLabels": {"tenant": tenant_name}
                },
                "egress": [
                    # 明確拒絕連接到其他租戶
                    {
                        "toEndpoints": [
                            {
                                "matchExpressions": [
                                    {
                                        "key": "tenant",
                                        "operator": "NotIn",
                                        "values": [tenant_name, "system"]
                                    }
                                ]
                            }
                        ],
                        "toPorts": []  # 空的 toPorts 表示拒絕
                    },
                    # 拒絕連接到敏感系統命名空間
                    {
                        "toEndpoints": [
                            {
                                "matchLabels": {
                                    "k8s:io.kubernetes.pod.namespace": "kube-system"
                                },
                                "matchExpressions": [
                                    {
                                        "key": "k8s-app",
                                        "operator": "NotIn",
                                        "values": ["kube-dns"]
                                    }
                                ]
                            }
                        ],
                        "toPorts": []
                    },
                    # 拒絕連接到 Kubernetes API Server
                    {
                        "toCIDRSet": [
                            {"cidr": "10.96.0.1/32"}  # 典型的 K8s API Server IP
                        ],
                        "toPorts": []
                    }
                ]
            }
        }
        
        self.policies[policy_name] = policy
        return policy
    
    def generate_emergency_lockdown_policy(self, namespace: str) -> Dict:
        """生成緊急鎖定政策 - 完全隔離命名空間"""
        policy_name = f"emergency-lockdown-{namespace}"
        
        policy = {
            "apiVersion": "cilium.io/v2",
            "kind": "CiliumNetworkPolicy",
            "metadata": {
                "name": policy_name,
                "namespace": namespace,
                "labels": {
                    "security.policy/type": "emergency-lockdown",
                    "security.policy/severity": "critical",
                    "security.policy/created-at": datetime.utcnow().isoformat()
                }
            },
            "spec": {
                "endpointSelector": {},  # 套用到命名空間內所有 Pod
                "ingress": [],  # 完全阻斷入站
                "egress": []    # 完全阻斷出站
            }
        }
        
        self.policies[policy_name] = policy
        return policy
    
    def export_policies_to_yaml(self, output_file: str = "cilium-security-policies.yaml"):
        """匯出所有政策到 YAML 檔案"""
        
        def dict_to_yaml(data, indent=0):
            """簡單的字典轉 YAML 函數"""
            yaml_str = ""
            spaces = "  " * indent
            
            if isinstance(data, dict):
                for key, value in data.items():
                    if isinstance(value, (dict, list)):
                        yaml_str += f"{spaces}{key}:\n"
                        yaml_str += dict_to_yaml(value, indent + 1)
                    else:
                        yaml_str += f"{spaces}{key}: {value}\n"
            elif isinstance(data, list):
                for item in data:
                    if isinstance(item, (dict, list)):
                        yaml_str += f"{spaces}- "
                        if isinstance(item, dict):
                            yaml_str += "\n"
                            yaml_str += dict_to_yaml(item, indent + 1)
                        else:
                            yaml_str += dict_to_yaml(item, indent + 1)
                    else:
                        yaml_str += f"{spaces}- {item}\n"
            
            return yaml_str
        
        with open(output_file, 'w') as f:
            for i, (policy_name, policy) in enumerate(self.policies.items()):
                if i > 0:
                    f.write("---\n")
                f.write(dict_to_yaml(policy))
                f.write("\n")
        
        logger.info(f"✅ 已匯出 {len(self.policies)} 個 Cilium 安全政策到 {output_file}")
        return output_file
    
    def generate_comprehensive_security_policies(self, tenants: List[str]) -> str:
        """為所有租戶生成完整的安全政策"""
        logger.info(f"🔒 開始生成 {len(tenants)} 個租戶的安全政策...")
        
        # 為每個租戶生成政策
        for tenant in tenants:
            self.generate_strict_isolation_policy(tenant)
            self.generate_lateral_movement_prevention_policy(tenant)
        
        # 生成全域安全政策
        self.generate_ip_blocking_policy(["192.168.1.100", "10.0.0.50"])  # 示例惡意 IP
        
        # 匯出所有政策
        output_file = self.export_policies_to_yaml()
        
        logger.info(f"🎯 安全政策生成完成，共 {len(self.policies)} 個政策")
        return output_file

def main():
    """主函數 - 生成示例安全政策"""
    manager = CiliumSecurityManager()
    
    # 示例租戶
    tenants = ["company-a", "company-b", "company-c"]
    
    # 生成完整安全政策
    output_file = manager.generate_comprehensive_security_policies(tenants)
    
    print(f"🎉 Cilium 安全政策已生成: {output_file}")
    print("\n📋 生成的政策類型:")
    for policy_name in manager.policies.keys():
        print(f"  - {policy_name}")
    
    print(f"\n🚀 部署指令:")
    print(f"kubectl apply -f {output_file}")

if __name__ == "__main__":
    main()