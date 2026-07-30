import FHIR from 'fhirclient';
import { useEffect, useState } from 'react';

export function LaunchPage() {
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getClientId()
      .then((clientId) => {
        if (!clientId) {
          setError('No SMART client ID configured. Set VITE_SMART_CLIENT_ID or run the load script with SMART_CONFIG_DIR.');
          return;
        }
        FHIR.oauth2.authorize({
          clientId,
          scope: 'launch openid fhirUser patient/*.read',
          redirectUri: '/app',
        });
      })
      .catch((err) => setError(String(err)));
  }, []);

  if (error) return <p style={{ color: 'red', padding: 24 }}>Launch error: {error}</p>;
  return <p style={{ padding: 24 }}>Launching...</p>;
}

async function getClientId(): Promise<string | null> {
  const envId = import.meta.env.VITE_SMART_CLIENT_ID;
  if (envId) return envId;

  try {
    const resp = await fetch('/smart-config.json');
    if (resp.ok) {
      const config = await resp.json();
      return config.clientId || null;
    }
  } catch {
    // Config file not available — fall through
  }
  return null;
}
