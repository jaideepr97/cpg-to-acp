import { Button } from '@mantine/core';
import type { ClientApplication } from '@medplum/fhirtypes';
import { SmartAppLaunchLink } from '@medplum/react';
import { useMedplum } from '@medplum/react-hooks';
import { IconSparkles } from '@tabler/icons-react';
import { useEffect, useState } from 'react';

const SMART_APP_NAME = 'ACP Writer';

interface SmartLaunchButtonProps {
  patientId: string;
}

export function SmartLaunchButton({ patientId }: SmartLaunchButtonProps) {
  const medplum = useMedplum();
  const [client, setClient] = useState<ClientApplication | null>(null);

  useEffect(() => {
    medplum
      .searchOne('ClientApplication', { name: SMART_APP_NAME })
      .then((result) => setClient(result ?? null))
      .catch(() => setClient(null));
  }, [medplum]);

  if (!client) {
    return (
      <Button
        size="md"
        variant="filled"
        leftSection={<IconSparkles size={18} />}
        disabled
        title="SMART app not configured"
      >
        Generate Care Plan
      </Button>
    );
  }

  return (
    <SmartAppLaunchLink
      client={client}
      patient={{ reference: `Patient/${patientId}` }}
      style={{ textDecoration: 'none' }}
    >
      <Button
        size="md"
        variant="filled"
        leftSection={<IconSparkles size={18} />}
        component="span"
      >
        Generate Care Plan
      </Button>
    </SmartAppLaunchLink>
  );
}
