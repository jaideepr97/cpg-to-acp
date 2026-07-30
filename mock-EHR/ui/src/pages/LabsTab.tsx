import { Operator } from '@medplum/core';
import { SearchControl } from '@medplum/react';
import { useParams } from 'react-router';
import { observationValueColumn, observationDateColumn } from '../components/ObservationValue';

export function LabsTab() {
  const { patientId } = useParams();
  return (
    <SearchControl
      search={{
        resourceType: 'Observation',
        fields: ['code', 'status'],
        filters: [
          { code: 'patient', operator: Operator.EQUALS, value: `Patient/${patientId}` },
          { code: 'category', operator: Operator.EQUALS, value: 'laboratory' },
        ],
        sortRules: [{ code: '-date' }],
      }}
      additionalColumns={[observationValueColumn(), observationDateColumn()]}
      hideToolbar
    />
  );
}
