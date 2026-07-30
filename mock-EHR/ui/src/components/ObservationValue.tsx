import type { Observation, Quantity } from '@medplum/fhirtypes';
import type { Resource } from '@medplum/fhirtypes';

function formatQuantity(q: Quantity | undefined): string {
  if (!q?.value) return '';
  const unit = q.unit ?? q.code ?? '';
  return `${q.value} ${unit}`.trim();
}

export function formatObservationValue(obs: Observation): string {
  if (obs.component) {
    const sys = obs.component.find((c) => c.code?.coding?.[0]?.code === '8480-6');
    const dia = obs.component.find((c) => c.code?.coding?.[0]?.code === '8462-4');
    if (sys?.valueQuantity && dia?.valueQuantity) {
      return `${sys.valueQuantity.value}/${dia.valueQuantity.value} mmHg`;
    }
    return obs.component
      .map((c) => formatQuantity(c.valueQuantity))
      .filter(Boolean)
      .join(' / ');
  }
  if (obs.valueQuantity) {
    return formatQuantity(obs.valueQuantity);
  }
  if (obs.valueString) {
    return obs.valueString;
  }
  if (obs.valueCodeableConcept) {
    return obs.valueCodeableConcept.text ?? obs.valueCodeableConcept.coding?.[0]?.display ?? '';
  }
  return '';
}

export function observationValueColumn() {
  return {
    name: 'Value',
    renderCell: (resource: Resource) => formatObservationValue(resource as Observation),
  };
}

export function observationDateColumn() {
  return {
    name: 'Date',
    renderCell: (resource: Resource) => {
      const obs = resource as Observation;
      const dt = obs.effectiveDateTime;
      if (!dt) return '';
      return new Date(dt).toLocaleDateString();
    },
  };
}
