import type { MedicationRequest } from '@medplum/fhirtypes';
import type { PatientSummarySectionConfig } from '@medplum/react';
import { ResourceName } from '@medplum/react';

function MedName({ mr }: { mr: MedicationRequest }) {
  if (mr.medicationCodeableConcept) {
    return <>{mr.medicationCodeableConcept.text ?? mr.medicationCodeableConcept.coding?.[0]?.display ?? '?'}</>;
  }
  if (mr.medicationReference) {
    return <ResourceName value={mr.medicationReference} />;
  }
  return <>?</>;
}

function MedicationsComponent({
  results,
}: {
  patient: unknown;
  onClickResource?: (r: unknown) => void;
  results: Record<string, unknown[]>;
}) {
  const requests = (results['medicationRequests'] as MedicationRequest[]) ?? [];
  const active = requests.filter((r) => r.status === 'active');

  return (
    <div style={{ padding: '8px 0' }}>
      <div style={{ fontWeight: 600, marginBottom: 8 }}>Medications</div>
      {active.length === 0 ? (
        <div style={{ color: 'var(--mantine-color-dimmed)' }}>(none active)</div>
      ) : (
        active.map((mr) => (
          <div key={mr.id} style={{ padding: '2px 0', fontSize: '0.9em' }}>
            <MedName mr={mr} />
          </div>
        ))
      )}
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
      patientParam: 'patient',
      query: { status: 'active' },
    },
  ],
  component: MedicationsComponent as PatientSummarySectionConfig['component'],
};
