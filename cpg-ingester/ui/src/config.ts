interface AppConfig {
  apiUrl: string;
}

let config: AppConfig | null = null;

export async function loadConfig(): Promise<AppConfig> {
  if (config) return config;

  try {
    const response = await fetch('/config.json');
    if (response.ok) {
      config = await response.json();
      return config!;
    }
  } catch {
    // Fall through to env var / default
  }

  config = {
    apiUrl: import.meta.env.VITE_API_URL ?? '',
  };
  return config;
}

export function getConfig(): AppConfig {
  if (!config) {
    throw new Error('Config not loaded — call loadConfig() first');
  }
  return config;
}
