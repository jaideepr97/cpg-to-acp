import type { Observation } from '@medplum/fhirtypes';
import type { PatientSummarySectionConfig } from '@medplum/react';

function formatDate(obs: Observation): string {
  const dt = obs.effectiveDateTime;
  if (!dt) return '';
  return new Date(dt).toLocaleDateString();
}

function formatVital(obs: Observation): string {
  if (obs.component) {
    const sys = obs.component.find((c) => c.code?.coding?.[0]?.code === '8480-6');
    const dia = obs.component.find((c) => c.code?.coding?.[0]?.code === '8462-4');
    if (sys?.valueQuantity && dia?.valueQuantity) {
      return `${sys.valueQuantity.value}/${dia.valueQuantity.value} mmHg`;
    }
  }
  if (obs.valueQuantity) {
    return `${obs.valueQuantity.value} ${obs.valueQuantity.unit ?? ''}`.trim();
  }
  return '';
}

function VitalsComponent({
  results,
}: {
  patient: unknown;
  onClickResource?: (r: unknown) => void;
  results: Record<string, unknown[]>;
}) {
  const observations = (results['observations'] as Observation[]) ?? [];

  if (observations.length === 0) {
    return (
      <div style={{ padding: '8px 0' }}>
        <div style={{ fontWeight: 600, marginBottom: 4 }}>Vitals</div>
        <div style={{ color: 'var(--mantine-color-dimmed)' }}>(none)</div>
      </div>
    );
  }

  return (
    <div style={{ padding: '8px 0' }}>
      <div style={{ fontWeight: 600, marginBottom: 8 }}>Vitals</div>
      {observations.map((obs) => (
        <div key={obs.id} style={{ display: 'flex', justifyContent: 'space-between', padding: '2px 0' }}>
          <span>
            <span style={{ color: 'var(--mantine-color-dimmed)', marginRight: 8 }}>
              {obs.code?.text ?? obs.code?.coding?.[0]?.display ?? '?'}
            </span>
            <strong>{formatVital(obs)}</strong>
          </span>
          <span style={{ color: 'var(--mantine-color-dimmed)', fontSize: '0.85em' }}>
            {formatDate(obs)}
          </span>
        </div>
      ))}
    </div>
  );
}

export const VitalsSectionCustom: PatientSummarySectionConfig = {
  key: 'vitals',
  title: 'Vitals',
  searches: [
    {
      key: 'observations',
      resourceType: 'Observation',
      patientParam: 'subject',
      query: { category: 'vital-signs' },
    },
  ],
  component: VitalsComponent as PatientSummarySectionConfig['component'],
};
