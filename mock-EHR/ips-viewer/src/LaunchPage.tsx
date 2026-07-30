import { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router';

export function LaunchPage() {
  const [error, setError] = useState<string | null>(null);
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();

  useEffect(() => {
    const iss = searchParams.get('iss');
    const launch = searchParams.get('launch');

    if (!iss || !launch) {
      setError('Missing iss or launch parameter. This app must be launched from the EHR.');
      return;
    }

    sessionStorage.setItem('ips_iss', iss);
    sessionStorage.setItem('ips_launch', launch);

    resolveLaunch(iss, launch)
      .then(({ token, patientId }) => {
        sessionStorage.setItem('ips_token', token);
        sessionStorage.setItem('ips_patient_id', patientId);
        navigate('/app');
      })
      .catch((err) => setError(String(err)));
  }, [searchParams, navigate]);

  if (error) return <p style={{ color: 'red', padding: 24 }}>Launch error: {error}</p>;
  return <p style={{ padding: 24 }}>Launching...</p>;
}

async function getSmartConfig(): Promise<{ clientId: string; clientSecret: string }> {
  const envId = import.meta.env.VITE_SMART_CLIENT_ID;
  const envSecret = import.meta.env.VITE_SMART_CLIENT_SECRET;
  if (envId && envSecret) return { clientId: envId, clientSecret: envSecret };

  const resp = await fetch('/smart-config.json');
  if (!resp.ok) throw new Error('No SMART config available');
  const config = await resp.json();
  if (!config.clientId || !config.clientSecret) throw new Error('SMART config missing clientId or clientSecret');
  return { clientId: config.clientId, clientSecret: config.clientSecret };
}

async function resolveLaunch(iss: string, launchId: string): Promise<{ token: string; patientId: string }> {
  const { clientId, clientSecret } = await getSmartConfig();

  const tokenResp = await fetch(`${iss.replace(/\/fhir\/R4\/?$/, '')}/oauth2/token`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: `grant_type=client_credentials&client_id=${clientId}&client_secret=${clientSecret}`,
  });
  if (!tokenResp.ok) throw new Error(`Token request failed: ${tokenResp.status}`);
  const tokenData = await tokenResp.json();
  const token = tokenData.access_token;

  const launchResp = await fetch(`${iss}SmartAppLaunch/${launchId}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!launchResp.ok) throw new Error(`SmartAppLaunch lookup failed: ${launchResp.status}`);
  const launchResource = await launchResp.json();

  const patientRef = launchResource.patient?.reference;
  if (!patientRef) throw new Error('No patient context in SmartAppLaunch');
  const patientId = patientRef.replace('Patient/', '');

  return { token, patientId };
}
