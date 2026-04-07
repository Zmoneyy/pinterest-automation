#!/bin/bash
# Deploy Pinterest Automation to Google Cloud Run
# Usage: ./clouddeploy.sh [PROJECT_ID]
# Example: ./clouddeploy.sh my-gcp-project-id
#
# Prerequisites:
#   - gcloud CLI installed and authenticated (gcloud auth login)
#   - Docker (or gcloud builds submit handles it remotely)
#   - .env.yaml file with your environment variables
#   - Cloud Run API enabled in your project
#
# Create .env.yaml from your .env file:
#   python3 -c "
#   import re
#   lines = open('.env').readlines()
#   out = []
#   for l in lines:
#       l = l.strip()
#       if l and not l.startswith('#'):
#           k, _, v = l.partition('=')
#           out.append(f'{k}: \"{v}\"')
#   open('.env.yaml','w').write('\n'.join(out))
#   "

set -euo pipefail

PROJECT_ID=${1:-"your-project-id"}
SERVICE_NAME="pinterest-automation"
REGION="us-central1"
IMAGE="gcr.io/${PROJECT_ID}/${SERVICE_NAME}"

echo "🚀 Deploying ${SERVICE_NAME} to Cloud Run..."
echo "   Project: ${PROJECT_ID}"
echo "   Region:  ${REGION}"
echo "   Image:   ${IMAGE}"
echo ""

# Check for .env.yaml
if [ ! -f ".env.yaml" ]; then
  echo "⚠ Warning: .env.yaml not found."
  echo "  Create it with your environment variables before deploying."
  echo "  See .env.example for the full list of required variables."
  echo ""
fi

# Build and push image via Cloud Build
echo "📦 Building container image..."
gcloud builds submit \
  --tag "${IMAGE}" \
  --project "${PROJECT_ID}"

echo ""
echo "☁ Deploying to Cloud Run..."

# Build the deploy command
DEPLOY_CMD="gcloud run deploy ${SERVICE_NAME} \
  --image ${IMAGE} \
  --platform managed \
  --region ${REGION} \
  --allow-unauthenticated \
  --memory 1Gi \
  --timeout 300 \
  --max-instances 1 \
  --project ${PROJECT_ID}"

# Add env vars file if it exists
if [ -f ".env.yaml" ]; then
  DEPLOY_CMD="${DEPLOY_CMD} --env-vars-file .env.yaml"
fi

eval $DEPLOY_CMD

echo ""
echo "✅ Deployment complete!"
echo ""

# Get the service URL
SERVICE_URL=$(gcloud run services describe "${SERVICE_NAME}" \
  --region "${REGION}" \
  --project "${PROJECT_ID}" \
  --format "value(status.url)" 2>/dev/null || echo "unknown")

echo "🌐 Service URL: ${SERVICE_URL}"
echo ""
echo "Next steps:"
echo "  1. Visit ${SERVICE_URL}/setup to complete configuration"
echo "  2. Connect your Pinterest account at ${SERVICE_URL}/pinterest/connect"
echo "  3. Add your products at ${SERVICE_URL}/products"
echo "  4. The daily scheduler runs at 9 AM UTC automatically"
