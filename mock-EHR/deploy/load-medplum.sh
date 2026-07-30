#!/usr/bin/env bash
# Load patient data and configure a Medplum server for the mock-EHR demo.
#
# This script is environment-agnostic: it takes MEDPLUM_BASE_URL as input
# and works identically in local podman-compose and OpenShift (as a Job).
#
# What it does:
#   1. Waits for the Medplum server to be healthy
#   2. Authenticates with the seeded super admin credentials
#   3. Creates a demo project ("CareView EHR")
#   4. Loads FHIR patient bundles into the project
#   5. Creates practitioner users for the demo
#   6. Registers the acp-writer as a SMART on FHIR ClientApplication

set -euo pipefail

MEDPLUM_BASE_URL="${MEDPLUM_BASE_URL:-http://localhost:8103}"
DATA_DIR="${DATA_DIR:-/data}"
ACP_WRITER_LAUNCH_URI="${ACP_WRITER_LAUNCH_URI:-http://localhost:3001/launch}"
ACP_WRITER_REDIRECT_URI="${ACP_WRITER_REDIRECT_URI:-http://localhost:3001/app}"

CODE_CHALLENGE="mock_ehr_setup_challenge"

# --- Helpers ---

log() { echo "[load-medplum] $*"; }

fail() { log "ERROR: $*" >&2; exit 1; }

medplum_post_file() {
  local path="$1"
  local file="$2"
  local token="$3"
  curl -sf -X POST "$MEDPLUM_BASE_URL$path" \
    -H "Content-Type: application/fhir+json" \
    -H "Authorization: Bearer $token" \
    -d @"$file"
}

# --- Step 1: Wait for Medplum server ---

log "Waiting for Medplum server at $MEDPLUM_BASE_URL ..."
retries=0
max_retries=60
until curl -sf "$MEDPLUM_BASE_URL/healthcheck" > /dev/null 2>&1; do
  retries=$((retries + 1))
  if [ "$retries" -ge "$max_retries" ]; then
    fail "Medplum server not ready after $max_retries attempts"
  fi
  sleep 2
done
log "Medplum server is healthy"

# --- Step 2-3: Create project and authenticate ---
# Medplum uses a two-step registration flow: /auth/newuser -> /auth/newproject
# This creates a new user, a new project, and returns an auth code in one flow.

PROJECT_EMAIL="admin@careview.example"
PROJECT_PASSWORD="CareView2026!"

log "Creating demo project (CareView EHR) ..."

newuser_response=$(curl -sf -X POST "$MEDPLUM_BASE_URL/auth/newuser" \
  -H "Content-Type: application/json" \
  -d "{
    \"firstName\": \"Admin\",
    \"lastName\": \"CareView\",
    \"email\": \"$PROJECT_EMAIL\",
    \"password\": \"$PROJECT_PASSWORD\",
    \"recaptchaToken\": \"\",
    \"codeChallengeMethod\": \"plain\",
    \"codeChallenge\": \"$CODE_CHALLENGE\"
  }") \
  || fail "Failed to create user"

LOGIN_ID=$(echo "$newuser_response" | python3 -c "import sys,json; print(json.load(sys.stdin)['login'])" 2>/dev/null) \
  || fail "Failed to extract login ID: $newuser_response"

newproject_response=$(curl -sf -X POST "$MEDPLUM_BASE_URL/auth/newproject" \
  -H "Content-Type: application/json" \
  -d "{
    \"login\": \"$LOGIN_ID\",
    \"projectName\": \"CareView EHR\"
  }") \
  || fail "Failed to create project"

auth_code=$(echo "$newproject_response" | python3 -c "import sys,json; print(json.load(sys.stdin)['code'])" 2>/dev/null) \
  || fail "Failed to extract auth code: $newproject_response"

token_response=$(curl -sf -X POST "$MEDPLUM_BASE_URL/oauth2/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=authorization_code&code=$auth_code&code_verifier=$CODE_CHALLENGE")

PROJECT_TOKEN=$(echo "$token_response" | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])" 2>/dev/null) \
  || fail "Failed to get project token: $token_response"

PROJECT_ID=$(echo "$token_response" | python3 -c "import sys,json; ref=json.load(sys.stdin).get('project',{}).get('reference',''); print(ref.split('/')[-1] if '/' in ref else ref)" 2>/dev/null) \
  || fail "Failed to extract project ID from token response"

log "Created project: CareView EHR ($PROJECT_ID)"
log "Project admin: $PROJECT_EMAIL"

# --- Step 4: Load patient bundles ---

log "Loading patient bundles from $DATA_DIR ..."
bundle_count=0
for bundle_file in "$DATA_DIR"/*.json; do
  [ -f "$bundle_file" ] || continue
  filename=$(basename "$bundle_file")
  log "  Loading $filename ..."
  response=$(medplum_post_file "/fhir/R4" "$bundle_file" "$PROJECT_TOKEN")
  http_type=$(echo "$response" | python3 -c "import sys,json; print(json.load(sys.stdin).get('resourceType',''))" 2>/dev/null || echo "unknown")
  if [ "$http_type" = "Bundle" ]; then
    log "  Loaded $filename successfully"
    bundle_count=$((bundle_count + 1))
  else
    log "  WARNING: Unexpected response for $filename: $response"
  fi
done
log "Loaded $bundle_count patient bundle(s)"

# --- Step 5: Create practitioner users ---

log "Creating practitioner users ..."

# Dr. Sarah Mitchell — primary demo user
curl -sf -X POST "$MEDPLUM_BASE_URL/admin/projects/$PROJECT_ID/invite" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $PROJECT_TOKEN" \
  -d '{
    "resourceType": "Practitioner",
    "firstName": "Sarah",
    "lastName": "Mitchell",
    "email": "sarah.mitchell@careview.example",
    "password": "CareView2026!",
    "sendEmail": false,
    "membership": { "admin": true }
  }' > /dev/null \
  || log "WARNING: Failed to create Dr. Mitchell (may already exist)"

log "  Created Dr. Sarah Mitchell"

# Dr. James Park — secondary demo user
curl -sf -X POST "$MEDPLUM_BASE_URL/admin/projects/$PROJECT_ID/invite" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $PROJECT_TOKEN" \
  -d '{
    "resourceType": "Practitioner",
    "firstName": "James",
    "lastName": "Park",
    "email": "james.park@careview.example",
    "password": "CareView2026!",
    "sendEmail": false,
    "membership": { "admin": false }
  }' > /dev/null \
  || log "WARNING: Failed to create Dr. Park (may already exist)"

log "  Created Dr. James Park"

# --- Step 6: Register acp-writer SMART app ---

log "Registering acp-writer SMART app ..."

client_response=$(curl -sf -X POST "$MEDPLUM_BASE_URL/admin/projects/$PROJECT_ID/client" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $PROJECT_TOKEN" \
  -d "{
    \"name\": \"ACP Writer\",
    \"description\": \"AI-powered care plan generator (SMART on FHIR app)\",
    \"redirectUri\": \"$ACP_WRITER_REDIRECT_URI\"
  }") \
  || fail "Failed to create ClientApplication"

CLIENT_ID=$(echo "$client_response" | python3 -c "import sys,json; print(json.load(sys.stdin).get('id',''))" 2>/dev/null)
CLIENT_SECRET=$(echo "$client_response" | python3 -c "import sys,json; print(json.load(sys.stdin).get('secret',''))" 2>/dev/null)

# Set the launchUri on the ClientApplication (not supported in the create endpoint)
if [ -n "$CLIENT_ID" ]; then
  curl -sf -X PATCH "$MEDPLUM_BASE_URL/fhir/R4/ClientApplication/$CLIENT_ID" \
    -H "Content-Type: application/json-patch+json" \
    -H "Authorization: Bearer $PROJECT_TOKEN" \
    -d "[
      {\"op\": \"add\", \"path\": \"/launchUri\", \"value\": \"$ACP_WRITER_LAUNCH_URI\"}
    ]" > /dev/null 2>&1 \
    || log "WARNING: Failed to set launchUri via PATCH, trying PUT ..."

  log "  Client ID:     $CLIENT_ID"
  log "  Client Secret: $CLIENT_SECRET"
  log "  Launch URI:    $ACP_WRITER_LAUNCH_URI"
  log "  Redirect URI:  $ACP_WRITER_REDIRECT_URI"
fi

log "Registered acp-writer SMART app"

# Write client ID to a shared config file for the IPS viewer
SMART_CONFIG_DIR="${SMART_CONFIG_DIR:-}"
if [ -n "$SMART_CONFIG_DIR" ] && [ -n "$CLIENT_ID" ]; then
  echo "{\"clientId\":\"$CLIENT_ID\"}" > "$SMART_CONFIG_DIR/smart-config.json"
  log "  Wrote SMART config to $SMART_CONFIG_DIR/smart-config.json"
fi

# --- Done ---

log ""
log "=== Medplum setup complete ==="
log "  Project:      CareView EHR ($PROJECT_ID)"
log "  FHIR endpoint: $MEDPLUM_BASE_URL/fhir/R4"
log "  Patients:     $bundle_count bundle(s) loaded"
log "  Users:        admin@careview.example / CareView2026! (project admin)"
log "                sarah.mitchell@careview.example / CareView2026! (Dr. Mitchell)"
log "                james.park@careview.example / CareView2026! (Dr. Park)"
log "  SMART App:    ACP Writer (client_id=$CLIENT_ID)"
log ""
