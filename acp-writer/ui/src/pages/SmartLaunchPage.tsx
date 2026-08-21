import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import {
  Bullseye,
  EmptyState,
  EmptyStateBody,
  Spinner,
} from "@patternfly/react-core";
import { ExclamationCircleIcon } from "@patternfly/react-icons";
import { createRun } from "@app/services/api";

async function getSmartConfig(): Promise<{
  clientId: string;
  clientSecret: string;
}> {
  const envId = import.meta.env.VITE_SMART_CLIENT_ID;
  const envSecret = import.meta.env.VITE_SMART_CLIENT_SECRET;
  if (envId && envSecret) return { clientId: envId, clientSecret: envSecret };

  const resp = await fetch("/smart-config.json");
  if (!resp.ok) throw new Error("No SMART config available");
  const config = await resp.json();
  if (!config.clientId || !config.clientSecret)
    throw new Error("SMART config missing clientId or clientSecret");
  return { clientId: config.clientId, clientSecret: config.clientSecret };
}

async function resolveLaunch(
  iss: string,
  launchId: string,
): Promise<{ token: string; patientId: string }> {
  const { clientId, clientSecret } = await getSmartConfig();

  const tokenResp = await fetch(
    `${iss.replace(/\/fhir\/R4\/?$/, "")}/oauth2/token`,
    {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: `grant_type=client_credentials&client_id=${encodeURIComponent(clientId)}&client_secret=${encodeURIComponent(clientSecret)}`,
    },
  );
  if (!tokenResp.ok)
    throw new Error(`Token request failed: ${tokenResp.status}`);
  const tokenData = await tokenResp.json();
  const token: string = tokenData.access_token;

  const launchResp = await fetch(`${iss}SmartAppLaunch/${launchId}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!launchResp.ok)
    throw new Error(`SmartAppLaunch lookup failed: ${launchResp.status}`);
  const launchResource = await launchResp.json();

  const patientRef: string | undefined =
    launchResource.patient?.reference;
  if (!patientRef) throw new Error("No patient context in SmartAppLaunch");
  const patientId = patientRef.replace("Patient/", "");

  return { token, patientId };
}

async function fetchIpsSummary(
  iss: string,
  token: string,
  patientId: string,
): Promise<Record<string, unknown>> {
  const resp = await fetch(`${iss}Patient/${patientId}/$summary`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!resp.ok)
    throw new Error(`Patient/$summary failed: ${resp.status}`);
  return resp.json();
}

export function SmartLaunchPage() {
  const [error, setError] = useState<string | null>(null);
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();

  useEffect(() => {
    const iss = searchParams.get("iss");
    const launch = searchParams.get("launch");

    if (!iss || !launch) {
      setError(
        "Missing iss or launch parameter. This app must be launched from the EHR.",
      );
      return;
    }

    resolveLaunch(iss, launch)
      .then(async ({ token, patientId }) => {
        const ipsBundle = await fetchIpsSummary(iss, token, patientId);
        const result = await createRun(ipsBundle);
        navigate(`/runs/${result.runId}`);
      })
      .catch((err) => setError(String(err)));
  }, [searchParams, navigate]);

  if (error) {
    return (
      <Bullseye>
        <EmptyState
          titleText="Launch Error"
          headingLevel="h1"
          icon={ExclamationCircleIcon}
          status="danger"
        >
          <EmptyStateBody>{error}</EmptyStateBody>
        </EmptyState>
      </Bullseye>
    );
  }

  return (
    <Bullseye>
      <EmptyState titleText="Launching..." headingLevel="h1">
        <EmptyStateBody>
          <Spinner size="xl" />
          <p style={{ marginTop: "1rem" }}>
            Resolving patient context from EHR...
          </p>
        </EmptyStateBody>
      </EmptyState>
    </Bullseye>
  );
}
