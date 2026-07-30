# Mock Electronic Health Record

A mock EHR built on [Medplum](https://www.medplum.com/) that provides a clinical-feeling environment for demoing the acp-writer SMART on FHIR app.

## Architecture

The mock-EHR uses Medplum as the FHIR server, replacing the previous HAPI FHIR setup. Medplum provides FHIR R4, OAuth, and SMART on FHIR App Launch out of the box.

| Component | Image | Port | Purpose |
|---|---|---|---|
| PostgreSQL | `postgres:16` | 5432 | Medplum data store |
| Redis | `redis:7` | 6379 | Medplum cache/queue |
| Medplum Server | `medplum/medplum-server:5.1.27` | 8103 | FHIR R4 + OAuth + SMART |
| Mock-EHR App | (Phase 2) | 3000 | Clinical EHR UI |

## Getting Started

Start the Medplum stack from the repository root:

```bash
podman-compose up -d medplum-postgres medplum-redis medplum-server
```

Wait for the server to be healthy, then run the data loader:

```bash
podman-compose up medplum-loader
```

Or start everything at once (loader waits for server automatically):

```bash
podman-compose up
```

## Patient Data

Hand-crafted FHIR Transaction Bundles in `data/`:

| Bundle | Patient | Scenario | Expected DMN Path |
|---|---|---|---|
| `patient-bundle-medication.json` | James Reynolds, 55yo M | Hypertension (BP 142/92) + Type 2 Diabetes, on Metformin | `start_medication` |
| `patient-bundle-lifestyle.json` | Maria Chen, 45yo F | Hypertension (BP 125/80), no comorbidities | `lifestyle_only` |

## Data Loading

The `deploy/load-medplum.sh` script automates the full Medplum setup:

1. Waits for the Medplum server to be healthy
2. Authenticates with the seeded super admin (`admin@example.com` / `medplum_admin`)
3. Creates a "CareView EHR" project
4. Loads all patient bundles from `data/`
5. Creates demo practitioner users
6. Registers the acp-writer as a SMART on FHIR app

The script is environment-agnostic — it takes `MEDPLUM_BASE_URL` as input and works in both local podman-compose and OpenShift (as a Job).

## Demo Users

After loading:

| User | Email | Password | Role |
|---|---|---|---|
| Super Admin | `admin@example.com` | `medplum_admin` | Server admin |
| Dr. Sarah Mitchell | `sarah.mitchell@careview.example` | `CareView2026!` | Primary demo practitioner |
| Dr. James Park | `james.park@careview.example` | `CareView2026!` | Secondary demo practitioner |

## Verifying

After the data is loaded:

```bash
# Authenticate (get a token)
CODE=$(curl -sf -X POST http://localhost:8103/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@example.com","password":"medplum_admin","codeChallengeMethod":"plain","codeChallenge":"verify"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['code'])")

TOKEN=$(curl -sf -X POST http://localhost:8103/oauth2/token \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=authorization_code&code=$CODE&code_verifier=verify" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# List patients
curl -sf http://localhost:8103/fhir/R4/Patient \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool

# Patient 1 conditions (hypertension + diabetes)
curl -sf "http://localhost:8103/fhir/R4/Condition?patient=patient-1" \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool

# Patient 1 blood pressure (142/92)
curl -sf "http://localhost:8103/fhir/R4/Observation?patient=patient-1&category=vital-signs" \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool

# Patient IPS (International Patient Summary)
curl -sf "http://localhost:8103/fhir/R4/Patient/patient-1/\$summary" \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

## SMART on FHIR

The acp-writer is registered as a SMART on FHIR ClientApplication during data loading. The SMART launch flow is:

1. Clinician opens the mock-EHR UI and selects a patient
2. Clicks "Generate Care Plan"
3. Medplum's OAuth server handles the authorization flow
4. The acp-writer opens with the patient context
5. After care plan approval, it writes back to Medplum's FHIR endpoint

## Version Pinning

All Medplum components are pinned to version **5.1.27**. See `dev_docs/ui/mock-ehr-design.md` for the version pinning rationale and upgrade process.
