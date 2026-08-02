import { Operator } from '@medplum/core';
import type { MedicationRequest, Resource } from '@medplum/fhirtypes';
import { ResourceName, SearchControl } from '@medplum/react';
import { useParams } from 'react-router';

function renderMedName(resource: Resource) {
  const mr = resource as MedicationRequest;
  if (mr.medicationCodeableConcept) {
    return mr.medicationCodeableConcept.text ?? mr.medicationCodeableConcept.coding?.[0]?.display ?? '?';
  }
  if (mr.medicationReference) {
    return <ResourceName value={mr.medicationReference} />;
  }
  return '?';
}

const ADDITIONAL_COLUMNS = [
  { name: 'Medication', renderCell: renderMedName },
  { name: 'Status', renderCell: (r: Resource) => (r as MedicationRequest).status ?? '' },
  { name: 'Authored', renderCell: (r: Resource) => (r as MedicationRequest).authoredOn ?? '' },
];

export function MedicationsTab() {
  const { patientId } = useParams();
  return (
    <SearchControl
      search={{
        resourceType: 'MedicationRequest',
        fields: ['_lastUpdated'],
        filters: [{ code: 'patient', operator: Operator.EQUALS, value: `Patient/${patientId}` }],
        sortRules: [{ code: '-_lastUpdated' }],
      }}
      additionalColumns={ADDITIONAL_COLUMNS}
      hideToolbar
    />
  );
}
