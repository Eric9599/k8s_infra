# k8s-infra Workspace Setup

This workspace contains a complete Kubernetes infrastructure setup for AI/ML workloads with multi-tenancy support.

## Quick Start on Linux

### Option 1: Using the Setup Script (Recommended)

1. Make the script executable:
   ```bash
   chmod +x setup.sh
   ```

2. Run the complete setup:
   ```bash
   ./setup.sh all
   ```

Or run individual steps:
```bash
./setup.sh install-tools    # Install kind, kubectl, helm, cilium-cli, docker
./setup.sh create-cluster   # Create Kind cluster
./setup.sh install-cilium   # Install Cilium CNI
./setup.sh deploy-services  # Deploy all services (monitoring, redis, litellm, harbor, mock-exporter)
./setup.sh run-my-infra     # Start the Python API server
```

### Option 2: Using Makefile

1. Install tools manually or run:
   ```bash
   make install-tools
   ```

2. Run complete setup:
   ```bash
   make all
   ```

Or individual targets:
```bash
make create-cluster
make install-cilium
make deploy-services
make run-my-infra
```

## Components

- **Kind Cluster**: Local Kubernetes cluster
- **Cilium**: CNI with network policies and Hubble observability
- **Harbor**: Container registry
- **LiteLLM Stack**: AI gateway with Redis and PostgreSQL
- **Monitoring**: Prometheus stack with custom GPU metrics
- **Mock Exporter**: Simulated GPU metrics exporter
- **My Infra API**: FastAPI application for tenant management

## Access Points

- Harbor UI: http://localhost:8080
- Hubble UI: Run `cilium hubble ui` and access the provided URL
- My Infra API: http://localhost:8000 (when running)
- Kubernetes Dashboard: Run `kubectl proxy` and access http://localhost:8001/api/v1/namespaces/kubernetes-dashboard/services/https:kubernetes-dashboard:/proxy/

## Cleanup

To clean up the entire setup:
```bash
./setup.sh clean
# or
make clean
```

## Prerequisites

- Linux environment
- sudo access for installing tools
- At least 4GB RAM and 2 CPU cores recommended
- Internet connection for downloading images and tools

## Notes

- The setup uses minimal resource limits to run on modest hardware
- Port mappings: 80/443/3000 on host map to cluster
- All services are configured for local development