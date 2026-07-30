import FHIR from 'fhirclient';
import { useEffect } from 'react';

const CLIENT_ID = import.meta.env.VITE_SMART_CLIENT_ID || '';

export function LaunchPage() {
  useEffect(() => {
    FHIR.oauth2.authorize({
      clientId: CLIENT_ID,
      scope: 'launch openid fhirUser patient/*.read',
      redirectUri: '/app',
    });
  }, []);

  return <p>Launching...</p>;
}
