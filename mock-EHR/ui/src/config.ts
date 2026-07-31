export const APP_NAME = 'CareView EHR';

export async function loadConfig(): Promise<{ medplumBaseUrl: string }> {
  try {
    const resp = await fetch('/config.json');
    if (resp.ok) {
      const config = await resp.json();
      if (config.medplumBaseUrl) return config;
    }
  } catch {
    // Config file not available — use defaults
  }

  return {
    medplumBaseUrl: import.meta.env.VITE_MEDPLUM_BASE_URL || 'http://localhost:8103/',
  };
}
