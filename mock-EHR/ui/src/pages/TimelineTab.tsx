import { Loader } from '@mantine/core';
import type { Patient } from '@medplum/fhirtypes';
import { PatientTimeline } from '@medplum/react';
import { useResource } from '@medplum/react-hooks';
import { useParams } from 'react-router';

export function TimelineTab() {
  const { patientId } = useParams();
  const patient = useResource<Patient>({ reference: `Patient/${patientId}` });
  if (!patient) {
    return <Loader />;
  }
  return <PatientTimeline patient={patient} />;
}
