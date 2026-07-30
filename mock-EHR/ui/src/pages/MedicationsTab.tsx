import { Operator } from '@medplum/core';
import { SearchControl } from '@medplum/react';
import { useParams } from 'react-router';

export function MedicationsTab() {
  const { patientId } = useParams();
  return (
    <SearchControl
      search={{
        resourceType: 'MedicationRequest',
        fields: ['medication', 'status', 'intent', 'authored-on'],
        filters: [{ code: 'patient', operator: Operator.EQUALS, value: `Patient/${patientId}` }],
        sortRules: [{ code: '-_lastUpdated' }],
      }}
      hideToolbar
    />
  );
}
