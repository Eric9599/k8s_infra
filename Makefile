# Makefile for k8s-infra workspace setup
# This Makefile automates the setup of the k8s-infra workspace on Linux

.PHONY: all install-tools create-cluster install-cilium deploy-services deploy-monitoring deploy-redis deploy-litellm deploy-harbor build-mock-exporter deploy-mock-exporter run-my-infra clean

# Default target
all: install-tools create-cluster install-cilium deploy-services run-my-infra

# Install required tools
install-tools:
	@echo "Installing required tools..."
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
	# Install Docker (if not installed)
	which docker || (curl -fsSL https://get.docker.com -o get-docker.sh && sudo sh get-docker.sh && rm get-docker.sh)
	# Install Python dependencies for my_infra
	cd my_infra && pip install -r requirements.txt || pip3 install -r requirements.txt

# Create Kind cluster
create-cluster:
	@echo "Creating Kind cluster..."
	kind create cluster --config kind-config.yaml --name k8s-infra

# Install Cilium
install-cilium:
	@echo "Installing Cilium..."
	cilium install --values cilium-values.yaml
	# Wait for Cilium to be ready
	cilium status --wait

# Deploy all services
deploy-services: deploy-monitoring deploy-redis deploy-litellm deploy-harbor build-mock-exporter deploy-mock-exporter apply-network-policies

# Deploy monitoring stack
deploy-monitoring:
	@echo "Deploying monitoring stack..."
	kubectl apply -f monitoring-stack.yaml
	kubectl apply -f priority-classes.yaml

# Deploy Redis
deploy-redis:
	@echo "Deploying Redis..."
	kubectl apply -f redis-stack.yaml

# Deploy LiteLLM stack
deploy-litellm:
	@echo "Deploying LiteLLM stack..."
	kubectl apply -f litellm-stack.yaml
	kubectl apply -f litellm-gateway-final.yaml

# Deploy Harbor
deploy-harbor:
	@echo "Deploying Harbor..."
	# Add Harbor Helm repo
	helm repo add harbor https://helm.goharbor.io
	helm repo update
	# Create namespace
	kubectl create namespace harbor --dry-run=client -o yaml | kubectl apply -f -
	# Install Harbor
	helm install harbor harbor/harbor --namespace harbor --values harbor-lite-values.yaml
	# Apply network policies
	kubectl apply -f harbor-network-policy.yaml

# Build mock exporter Docker image
build-mock-exporter:
	@echo "Building mock exporter..."
	cd mock-exporter && docker build -t mock-exporter:latest .

# Apply network policies
apply-network-policies:
	@echo "Applying network policies..."
	kubectl apply -f tenant-network-policy.yaml
	kubectl apply -f harbor-network-policy.yaml

# Run my_infra Python application
run-my-infra:
	@echo "Running my_infra application..."
	cd my_infra && python main.py &
	# Or use uvicorn
	# cd my_infra && uvicorn main:app --host 0.0.0.0 --port 8000 &

# Clean up
clean:
	@echo "Cleaning up..."
	kind delete cluster --name k8s-infra
	docker system prune -f

# Quick start (assumes tools are already installed)
quick-start: create-cluster install-cilium deploy-services run-my-infra