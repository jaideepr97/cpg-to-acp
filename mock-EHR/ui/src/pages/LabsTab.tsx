import { Operator } from '@medplum/core';
import { SearchControl } from '@medplum/react';
import { useParams } from 'react-router';

export function LabsTab() {
  const { patientId } = useParams();
  return (
    <SearchControl
      search={{
        resourceType: 'DiagnosticReport',
        fields: ['code', 'status', 'issued'],
        filters: [{ code: 'patient', operator: Operator.EQUALS, value: `Patient/${patientId}` }],
        sortRules: [{ code: '-_lastUpdated' }],
      }}
      hideToolbar
    />
  );
}
