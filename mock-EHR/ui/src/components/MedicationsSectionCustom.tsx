import { Badge, Flex, Text } from '@mantine/core';
import { formatCodeableConcept } from '@medplum/core';
import type { MedicationRequest } from '@medplum/fhirtypes';
import type { PatientSummarySectionConfig } from '@medplum/react';
import { ResourceName } from '@medplum/react';

function MedName({ mr }: { mr: MedicationRequest }) {
  if (mr.medicationCodeableConcept) {
    return <>{formatCodeableConcept(mr.medicationCodeableConcept)}</>;
  }
  if (mr.medicationReference) {
    return <ResourceName value={mr.medicationReference} />;
  }
  return <>?</>;
}

const STATUS_COLORS: Record<string, string> = {
  active: 'green',
  stopped: 'red',
  'on-hold': 'yellow',
  cancelled: 'red',
  completed: 'blue',
  'entered-in-error': 'red',
  draft: 'gray',
};

function MedicationsComponent({
  results,
}: {
  patient: unknown;
  onClickResource?: (r: unknown) => void;
  results: Record<string, unknown[]>;
}) {
  const requests = (results['medicationRequests'] as MedicationRequest[]) ?? [];

  if (requests.length === 0) {
    return (
      <div style={{ padding: '8px 0' }}>
        <Text fw={600} size="sm" mb={4}>Medications</Text>
        <Text c="dimmed">(none)</Text>
      </div>
    );
  }

  return (
    <div style={{ padding: '8px 0' }}>
      <Text fw={600} size="sm" mb={8}>Medications</Text>
      <Flex direction="column" gap={8}>
        {requests.map((mr) => (
          <div key={mr.id}>
            <Text fw={500} size="sm" truncate>
              <MedName mr={mr} />
            </Text>
            {mr.status && (
              <Badge
                size="xs"
                variant="light"
                color={STATUS_COLORS[mr.status] ?? 'gray'}
                mt={2}
              >
                {mr.status}
              </Badge>
            )}
          </div>
        ))}
      </Flex>
    </div>
  );
}

export const MedicationsSectionCustom: PatientSummarySectionConfig = {
  key: 'medications',
  title: 'Medications',
  searches: [
    {
      key: 'medicationRequests',
      resourceType: 'MedicationRequest',
      patientParam: 'subject',
    },
  ],
  component: MedicationsComponent as PatientSummarySectionConfig['component'],
};
