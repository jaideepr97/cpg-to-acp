import { Operator } from '@medplum/core';
import { SearchControl } from '@medplum/react';
import { useParams } from 'react-router';

export function CarePlansTab() {
  const { patientId } = useParams();
  return (
    <SearchControl
      search={{
        resourceType: 'CarePlan',
        fields: ['status', 'intent', 'category', '_lastUpdated'],
        filters: [{ code: 'patient', operator: Operator.EQUALS, value: `Patient/${patientId}` }],
        sortRules: [{ code: '-_lastUpdated' }],
      }}
      hideToolbar
    />
  );
}
