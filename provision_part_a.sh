#!/usr/bin/env bash
# Part A — Azure resource provisioning for CS 345 / CSC 645 (Voice Memo Analyzer)
# Creates: resource group, Speech (F0), Language (F0), Log Analytics workspace,
# Application Insights. Writes keys to ./.env WITHOUT printing them.
#
# Prerequisite: run `az login` first (interactive, opens a browser).
# Safe to re-run: existing resources are reused; .env is only created if missing.

set -euo pipefail

RG="cs345-speech-rg"
LOC="northcentralus"   # eastus is blocked by this subscription's "Allowed resource deployment regions" policy
SPEECH="cs345-speech"
LANG_NAME="cs345-language"
LAW="cs345-logs"
AI="cs345-insights"
ENV_FILE=".env"

cd "$(dirname "$0")"

if ! az account show >/dev/null 2>&1; then
  echo "Not logged in. Run: az login" >&2
  exit 1
fi

echo "== A2. Resource group"
az group create --name "$RG" --location "$LOC" --output none

echo "== A3. Speech (F0)"
az cognitiveservices account create \
  --name "$SPEECH" --resource-group "$RG" \
  --kind SpeechServices --sku F0 --location "$LOC" --yes --output none

echo "== A4. Language (F0)"
az cognitiveservices account create \
  --name "$LANG_NAME" --resource-group "$RG" \
  --kind TextAnalytics --sku F0 --location "$LOC" --yes --output none

echo "== A5. Log Analytics workspace"
az monitor log-analytics workspace create \
  --resource-group "$RG" --workspace-name "$LAW" --location "$LOC" --output none

WS_ID=$(az monitor log-analytics workspace show \
  --resource-group "$RG" --workspace-name "$LAW" --query id --output tsv)

echo "== A5. Application Insights"
az extension add --name application-insights --yes --only-show-errors >/dev/null 2>&1 || true
az monitor app-insights component create \
  --app "$AI" --location "$LOC" --resource-group "$RG" \
  --workspace "$WS_ID" --output none

# Pull secrets straight into variables; never echo them.
SPEECH_KEY=$(az cognitiveservices account keys list \
  --name "$SPEECH" --resource-group "$RG" --query key1 --output tsv)
LANG_KEY=$(az cognitiveservices account keys list \
  --name "$LANG_NAME" --resource-group "$RG" --query key1 --output tsv)
LANG_ENDPOINT=$(az cognitiveservices account show \
  --name "$LANG_NAME" --resource-group "$RG" --query properties.endpoint --output tsv)
AI_CONN=$(az monitor app-insights component show \
  --app "$AI" --resource-group "$RG" --query connectionString --output tsv)

if [ -e "$ENV_FILE" ]; then
  echo "$ENV_FILE already exists — not overwriting. Compare it with the values by hand." >&2
  exit 1
fi

umask 077
{
  echo "AZURE_SPEECH_KEY=$SPEECH_KEY"
  echo "AZURE_SPEECH_REGION=$LOC"
  echo "AZURE_LANGUAGE_KEY=$LANG_KEY"
  echo "AZURE_LANGUAGE_ENDPOINT=$LANG_ENDPOINT"
  echo "APPLICATIONINSIGHTS_CONNECTION_STRING=$AI_CONN"
} > "$ENV_FILE"
chmod 600 "$ENV_FILE"

# .gitignore: make sure secrets and audio never get committed
touch .gitignore
for pat in ".env" "node_modules/" "__pycache__/" "*.pyc" "temp_audio/" "*.wav" "*.mp3"; do
  grep -qxF "$pat" .gitignore || echo "$pat" >> .gitignore
done

echo "== Verify F0 tiers (should print F0 for both)"
az cognitiveservices account show --name "$SPEECH" --resource-group "$RG" --query sku.name --output tsv
az cognitiveservices account show --name "$LANG_NAME" --resource-group "$RG" --query sku.name --output tsv

echo "Done. Wrote $ENV_FILE (keys not printed). Next: Part B."
