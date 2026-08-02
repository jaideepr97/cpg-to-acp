import { Operator } from '@medplum/core';
import { SearchControl } from '@medplum/react';
import { useParams } from 'react-router';

export function EncountersTab() {
  const { patientId } = useParams();
  return (
    <SearchControl
      search={{
        resourceType: 'Encounter',
        fields: ['type', 'status', 'date', 'class'],
        filters: [{ code: 'patient', operator: Operator.EQUALS, value: `Patient/${patientId}` }],
        sortRules: [{ code: '-_lastUpdated' }],
      }}
      hideToolbar
    />
  );
}
