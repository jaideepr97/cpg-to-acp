import type { OperationOutcome, Patient } from '@medplum/fhirtypes';
import { useResource } from '@medplum/react-hooks';
import { useParams } from 'react-router';

interface UsePatientOptions {
  setOutcome?: (outcome: OperationOutcome) => void;
}

export function usePatient(options?: UsePatientOptions): Patient | undefined {
  const { patientId } = useParams();
  if (!patientId) {
    throw new Error('usePatient must be used within a /Patient/:patientId route');
  }
  return useResource<Patient>({ reference: `Patient/${patientId}` }, options?.setOutcome);
}
