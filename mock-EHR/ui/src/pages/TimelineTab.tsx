import { Loader } from '@mantine/core';
import type { MedplumClient, ProfileResource } from '@medplum/core';
import { createReference } from '@medplum/core';
import type { Attachment, Patient, ResourceType } from '@medplum/fhirtypes';
import { ResourceTimeline } from '@medplum/react';
import { useCallback } from 'react';
import { usePatient } from '../hooks/usePatient';

function loadTimelineResources(medplum: MedplumClient, resourceType: ResourceType, id: string) {
  const ref = `${resourceType}/${id}`;
  const _count = 100;
  return Promise.allSettled([
    medplum.readHistory('Patient', id),
    medplum.search('ClinicalImpression', { subject: ref, _count }),
    medplum.search('Communication', { subject: ref, _count }),
    medplum.search('Device', { patient: ref, _count }),
    medplum.search('DeviceRequest', { patient: ref, _count }),
    medplum.search('DiagnosticReport', { subject: ref, _count }),
    medplum.search('Encounter', { patient: ref, _count }),
    medplum.search('Media', { subject: ref, _count }),
    medplum.search('ServiceRequest', { subject: ref, _count }),
    medplum.search('Task', { subject: ref, _count }),
  ]);
}

export function TimelineTab() {
  const patient = usePatient();

  const createCommunication = useCallback(
    (resource: Patient, sender: ProfileResource, text: string) => ({
      resourceType: 'Communication' as const,
      status: 'completed' as const,
      subject: createReference(resource),
      sender: createReference(sender),
      sent: new Date().toISOString(),
      payload: [{ contentString: text }],
    }),
    []
  );

  const createMedia = useCallback(
    (resource: Patient, operator: ProfileResource, content: Attachment) => ({
      resourceType: 'Media' as const,
      status: 'completed' as const,
      subject: createReference(resource),
      operator: createReference(operator),
      issued: new Date().toISOString(),
      content,
    }),
    []
  );

  if (!patient) {
    return <Loader />;
  }

  return (
    <ResourceTimeline
      value={patient}
      loadTimelineResources={loadTimelineResources}
      createCommunication={createCommunication}
      createMedia={createMedia}
    />
  );
}
