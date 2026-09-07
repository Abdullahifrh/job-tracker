#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${GCP_PROJECT_ID:?Set GCP_PROJECT_ID first}"
REGION="${GCP_REGION:-europe-west4}"
FUNCTION_NAME="job-tracker-pipeline"
SCHEDULER_JOB_NAME="job-tracker-schedule"
INVOKER_SA="job-tracker-invoker@${PROJECT_ID}.iam.gserviceaccount.com"

FUNCTION_URL=$(gcloud functions describe "$FUNCTION_NAME" \
  --gen2 --project="$PROJECT_ID" --region="$REGION" \
  --format="value(serviceConfig.uri)")

gcloud scheduler jobs create http "$SCHEDULER_JOB_NAME" \
  --project="$PROJECT_ID" \
  --location="$REGION" \
  --schedule="0 */2 * * *" \
  --uri="$FUNCTION_URL" \
  --http-method=POST \
  --oidc-service-account-email="$INVOKER_SA" \
  --oidc-token-audience="$FUNCTION_URL"
