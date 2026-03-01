#!/bin/bash

# setup.sh - One-click setup script for k8s-infra workspace on Linux

set -e

echo "Starting k8s-infra setup..."

# Function to install tools
install_tools() {
    echo "Installing required tools..."

    # Install kind
    curl -Lo ./kind https://kind.sigs.k8s.io/dl/v0.29.0/kind-linux-amd64
    chmod +x ./kind
    sudo mv ./kind /usr/local/bin/kind

    # Install kubectl
    curl -LO "https://dl.k8s.io/release/v1.32.6/bin/linux/amd64/kubectl"
    chmod +x kubectl
    sudo mv kubectl /usr/local/bin/kubectl

    # Install Helm
    curl https://get.helm.sh/helm-v4.0.0-linux-amd64.tar.gz -o helm.tar.gz
    tar -zxvf helm.tar.gz
    sudo mv linux-amd64/helm /usr/local/bin/helm
    rm -rf linux-amd64 helm.tar.gz

    # Install Cilium CLI
    curl -L --remote-name-all https://github.com/cilium/cilium-cli/releases/download/v0.19.0/cilium-linux-amd64.tar.gz
    tar xzvf cilium-linux-amd64.tar.gz
    sudo mv cilium /usr/local/bin/cilium
    rm cilium-linux-amd64.tar.gz

    # Install Docker if not installed
    if ! command -v docker &> /dev/null; then
        curl -fsSL https://get.docker.com -o get-docker.sh
        sudo sh get-docker.sh
        rm get-docker.sh
    fi

    # Install Python dependencies
    cd my_infra
    pip install -r requirements.txt || pip3 install -r requirements.txt
    cd ..
}

# Function to create cluster
create_cluster() {
    echo "Creating Kind cluster..."
    kind create cluster --config kind-config.yaml --name k8s-infra
}

# Function to install Cilium
install_cilium() {
    echo "Installing Cilium..."
    cilium install --values cilium-values.yaml
    cilium status --wait
}

# Function to deploy services
deploy_services() {
    echo "Deploying monitoring stack..."
    kubectl apply -f monitoring-stack.yaml
    kubectl apply -f priority-classes.yaml

    echo "Deploying Redis..."
    kubectl apply -f redis-stack.yaml

    echo "Deploying LiteLLM stack..."
    kubectl apply -f litellm-stack.yaml
    kubectl apply -f litellm-gateway-final.yaml

    echo "Deploying Harbor..."
    helm repo add harbor https://helm.goharbor.io || true
    helm repo update
    kubectl create namespace harbor --dry-run=client -o yaml | kubectl apply -f -
    helm install harbor harbor/harbor --namespace harbor --values harbor-lite-values.yaml
    kubectl apply -f harbor-network-policy.yaml

    echo "Building and deploying mock exporter..."
    cd mock-exporter
    docker build -t mock-exporter:latest .
    cd ..
    kind load docker-image mock-exporter:latest --name k8s-infra
    kubectl apply -f mock-exporter-deployment.yaml

    echo "Applying network policies..."
    kubectl apply -f tenant-network-policy.yaml
}

# Function to run my_infra
run_my_infra() {
    echo "Running my_infra application..."
    cd my_infra
    python main.py &
    cd ..
}

# Function to clean up
cleanup() {
    echo "Cleaning up..."
    kind delete cluster --name k8s-infra || true
    docker system prune -f || true
}

# Main script
case "$1" in
    install-tools)
        install_tools
        ;;
    create-cluster)
        create_cluster
        ;;
    install-cilium)
        install_cilium
        ;;
    deploy-services)
        deploy_services
        ;;
    run-my-infra)
        run_my_infra
        ;;
    clean)
        cleanup
        ;;
    all)
        install_tools
        create_cluster
        install_cilium
        deploy_services
        run_my_infra
        ;;
    *)
        echo "Usage: $0 {install-tools|create-cluster|install-cilium|deploy-services|run-my-infra|clean|all}"
        echo "Run '$0 all' for complete setup"
        exit 1
esac

echo "Setup complete!"