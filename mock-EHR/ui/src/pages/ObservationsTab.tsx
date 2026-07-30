import { Operator } from '@medplum/core';
import { SearchControl } from '@medplum/react';
import { useParams } from 'react-router';

export function ObservationsTab() {
  const { patientId } = useParams();
  return (
    <SearchControl
      search={{
        resourceType: 'Observation',
        fields: ['code', 'value-quantity', 'status', 'date'],
        filters: [
          { code: 'patient', operator: Operator.EQUALS, value: `Patient/${patientId}` },
          { code: 'category', operator: Operator.EQUALS, value: 'vital-signs' },
        ],
        sortRules: [{ code: '-date' }],
      }}
      hideToolbar
    />
  );
}
