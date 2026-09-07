#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${GCP_PROJECT_ID:?Set GCP_PROJECT_ID first}"
REGION="${GCP_REGION:-europe-west4}"
FUNCTION_NAME="job-tracker-pipeline"
SHEET_ID="${TRACKER_SHEET_ID:?Set TRACKER_SHEET_ID first}"

gcloud functions deploy "$FUNCTION_NAME" \
  --quiet \
  --gen2 \
  --project="$PROJECT_ID" \
  --region="$REGION" \
  --runtime=python312 \
  --source=. \
  --entry-point=handle_request \
  --trigger-http \
  --no-allow-unauthenticated \
  --memory=256Mi \
  --timeout=120s \
  --set-env-vars="TRACKER_SHEET_ID=$SHEET_ID" \
  --set-secrets="GMAIL_OAUTH_TOKEN=gmail-sheets-oauth-token:latest,GEMINI_API_KEY=gemini-api-key:latest"
