#!/usr/bin/env bash
# ── Clinical Copilot Engine — GCP VM Deployment Script ──────────────
#
# This script provisions a GCP Compute Engine VM, installs Docker,
# clones the repo, and starts the application via Docker Compose.
#
# Prerequisites:
#   - gcloud CLI installed and authenticated (gcloud auth login)
#   - A GCP project selected (gcloud config set project <PROJECT_ID>)
#   - Your repo pushed to GitHub
#
# Usage:
#   chmod +x scripts/deploy-gcp.sh
#   ./scripts/deploy-gcp.sh
#
# For GPU (vLLM) support, change MACHINE_TYPE to n1-standard-8 and
# add --accelerator=count=1,type=nvidia-tesla-t4

set -euo pipefail

# ── Configuration (edit these) ──────────────────────────────────────
PROJECT_ID="${GCP_PROJECT_ID:-your-gcp-project-id}"
ZONE="us-central1-a"
INSTANCE_NAME="clinical-copilot-vm"
MACHINE_TYPE="e2-standard-4"          # 4 vCPU, 16 GB RAM (no GPU)
# MACHINE_TYPE="n1-standard-8"        # Use this for GPU instances
BOOT_DISK_SIZE="50GB"
IMAGE_FAMILY="ubuntu-2204-lts"
IMAGE_PROJECT="ubuntu-os-cloud"
GITHUB_REPO="https://github.com/YOUR_USERNAME/clinical-copilot-engine.git"
BRANCH="main"

echo "============================================="
echo " Clinical Copilot Engine — GCP Deployment"
echo "============================================="
echo ""
echo "  Project:  $PROJECT_ID"
echo "  Zone:     $ZONE"
echo "  Instance: $INSTANCE_NAME"
echo "  Machine:  $MACHINE_TYPE"
echo ""

# ── Step 1: Create the VM ──────────────────────────────────────────
echo "[1/4] Creating GCP Compute Engine instance..."

gcloud compute instances create "$INSTANCE_NAME" \
    --project="$PROJECT_ID" \
    --zone="$ZONE" \
    --machine-type="$MACHINE_TYPE" \
    --boot-disk-size="$BOOT_DISK_SIZE" \
    --image-family="$IMAGE_FAMILY" \
    --image-project="$IMAGE_PROJECT" \
    --tags=http-server,https-server \
    --metadata=startup-script='#!/bin/bash
echo ">>> Starting VM setup..."

# Update system
apt-get update -y
apt-get upgrade -y

# Install Docker
apt-get install -y ca-certificates curl gnupg
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null
apt-get update -y
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Enable Docker for all users
systemctl enable docker
systemctl start docker

# Install git
apt-get install -y git

echo ">>> VM setup complete."
'

echo "  VM created. Waiting for startup script to finish..."
sleep 60

# ── Step 2: Open Firewall Ports ────────────────────────────────────
echo "[2/4] Configuring firewall rules..."

gcloud compute firewall-rules create allow-copilot-http \
    --project="$PROJECT_ID" \
    --allow=tcp:8000,tcp:3000 \
    --target-tags=http-server \
    --description="Allow Clinical Copilot frontend (3000) and backend (8000)" \
    2>/dev/null || echo "  Firewall rule already exists."

# ── Step 3: Clone repo and configure ───────────────────────────────
echo "[3/4] Deploying application to VM..."

gcloud compute ssh "$INSTANCE_NAME" --zone="$ZONE" --project="$PROJECT_ID" --command="
set -e

# Wait for startup script to finish Docker install
while ! command -v docker &> /dev/null; do
    echo 'Waiting for Docker installation...'
    sleep 10
done

echo '>>> Cloning repository...'
cd /opt
sudo git clone $GITHUB_REPO clinical-copilot-engine || {
    echo 'Repo exists, pulling latest...'
    cd /opt/clinical-copilot-engine
    sudo git pull origin $BRANCH
}
cd /opt/clinical-copilot-engine

# Create .env from example
if [ ! -f .env ]; then
    sudo cp .env.example .env
    echo '>>> Created .env from .env.example'
    echo '>>> IMPORTANT: Edit /opt/clinical-copilot-engine/.env with your actual values!'
fi

# Create data directories
sudo mkdir -p data/raw data/compiled

echo '>>> Building and starting containers...'
sudo docker compose up --build -d

echo ''
echo '>>> Deployment complete!'
echo '>>> Services starting up...'
"

# ── Step 4: Print access info ──────────────────────────────────────
echo ""
echo "[4/4] Getting VM external IP..."
EXTERNAL_IP=$(gcloud compute instances describe "$INSTANCE_NAME" \
    --zone="$ZONE" \
    --project="$PROJECT_ID" \
    --format='get(networkInterfaces[0].accessConfigs[0].natIP)')

echo ""
echo "============================================="
echo " Deployment Complete!"
echo "============================================="
echo ""
echo "  Frontend:  http://$EXTERNAL_IP:3000"
echo "  Backend:   http://$EXTERNAL_IP:8000"
echo "  API Docs:  http://$EXTERNAL_IP:8000/docs"
echo "  Health:    http://$EXTERNAL_IP:8000/health"
echo ""
echo "  SSH into VM:"
echo "    gcloud compute ssh $INSTANCE_NAME --zone=$ZONE"
echo ""
echo "  View logs:"
echo "    gcloud compute ssh $INSTANCE_NAME --zone=$ZONE --command='cd /opt/clinical-copilot-engine && sudo docker compose logs -f'"
echo ""
echo "  IMPORTANT: Edit .env on the VM if you need UMLS/LOINC keys:"
echo "    gcloud compute ssh $INSTANCE_NAME --zone=$ZONE --command='sudo nano /opt/clinical-copilot-engine/.env'"
echo ""
echo "  To add GPU (vLLM) later:"
echo "    1. Stop the VM"
echo "    2. Add a GPU via: gcloud compute instances add-gpu"
echo "    3. Install NVIDIA drivers"
echo "    4. Run: docker compose --profile gpu up -d"
echo ""
