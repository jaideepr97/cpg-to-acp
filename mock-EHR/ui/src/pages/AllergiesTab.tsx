import { Operator } from '@medplum/core';
import { SearchControl } from '@medplum/react';
import { useParams } from 'react-router';

export function AllergiesTab() {
  const { patientId } = useParams();
  return (
    <SearchControl
      search={{
        resourceType: 'AllergyIntolerance',
        fields: ['code', 'clinical-status', 'criticality', 'type'],
        filters: [{ code: 'patient', operator: Operator.EQUALS, value: `Patient/${patientId}` }],
        sortRules: [{ code: '-_lastUpdated' }],
      }}
      hideToolbar
    />
  );
}
