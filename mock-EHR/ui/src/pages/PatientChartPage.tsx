import { Loader, ScrollArea } from '@mantine/core';
import type { OperationOutcome } from '@medplum/fhirtypes';
import { isOk } from '@medplum/core';
import { Document, LinkTabs, OperationOutcomeAlert, PatientSummary, getDefaultSections } from '@medplum/react';
import { useMemo, useState } from 'react';
import { Outlet, useNavigate, useParams } from 'react-router';
import { SmartLaunchButton } from '../components/SmartLaunchButton';
import { VitalsSectionCustom } from '../components/VitalsSectionCustom';
import { usePatient } from '../hooks/usePatient';

const KEEP_SECTIONS = new Set([
  'demographics',
  'allergies',
  'problemList',
  'medications',
  'vitals',
  'labs',
]);

const TABS = [
  { label: 'Activity', value: 'timeline' },
  { label: 'Visits', value: 'encounters' },
  { label: 'Meds', value: 'medications' },
  { label: 'Vitals', value: 'vitals' },
  { label: 'Labs', value: 'labs' },
  { label: 'Allergies', value: 'allergies' },
  { label: 'Care Plans', value: 'careplans' },
];

export function PatientChartPage() {
  const { patientId } = useParams();
  const navigate = useNavigate();
  const [outcome, setOutcome] = useState<OperationOutcome>();
  const patient = usePatient({ setOutcome });

  const sections = useMemo(
    () =>
      getDefaultSections()
        .filter((s) => KEEP_SECTIONS.has(s.key))
        .map((s) => {
          if (s.key === 'vitals') return VitalsSectionCustom;
          if (s.key === 'medications' && s.searches) {
            return {
              ...s,
              searches: s.searches.map((search) =>
                search.resourceType === 'MedicationRequest'
                  ? {
                      key: search.key,
                      resourceType: search.resourceType,
                      patientParam: search.patientParam,
                      query: { _include: 'MedicationRequest:medication' },
                    }
                  : search
              ),
            };
          }
          return s;
        }),
    []
  );

  if (outcome && !isOk(outcome)) {
    return (
      <Document>
        <OperationOutcomeAlert outcome={outcome} />
      </Document>
    );
  }

  if (!patient) {
    return <Loader />;
  }

  return (
    <div style={{ display: 'flex', height: '100%' }}>
      <ScrollArea style={{ width: 350, flexShrink: 0, borderRight: '1px solid var(--mantine-color-gray-3)' }} p="sm">
        <PatientSummary
          patient={patient}
          sections={sections}
          onClickResource={(resource) =>
            navigate(`/Patient/${patientId}/${resource.resourceType}/${resource.id}`)?.catch(console.error)
          }
        />
      </ScrollArea>
      <div style={{ flex: 1, overflow: 'auto' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '8px 16px' }}>
          <LinkTabs baseUrl={`/Patient/${patientId}`} tabs={TABS} />
          <SmartLaunchButton patientId={patientId!} />
        </div>
        <div style={{ padding: '0 16px 16px' }}>
          <Outlet />
        </div>
      </div>
    </div>
  );
}
