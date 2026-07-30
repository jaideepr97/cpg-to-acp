import { Loader, ScrollArea } from '@mantine/core';
import { LinkTabs, PatientSummary, getDefaultSections } from '@medplum/react';
import { useResource } from '@medplum/react-hooks';
import type { Patient } from '@medplum/fhirtypes';
import { useMemo } from 'react';
import { Outlet, useNavigate, useParams } from 'react-router';
import { SmartLaunchButton } from '../components/SmartLaunchButton';
import { VitalsSectionCustom } from '../components/VitalsSectionCustom';

const KEEP_SECTIONS = new Set([
  'demographics',
  'allergies',
  'problemList',
  'medications',
  'vitals',
  'labs',
]);

const TABS = [
  { label: 'Timeline', value: 'timeline' },
  { label: 'Visits', value: 'Encounter' },
  { label: 'Meds', value: 'MedicationRequest' },
  { label: 'Vitals', value: 'Observation' },
  { label: 'Labs', value: 'DiagnosticReport' },
  { label: 'Allergies', value: 'AllergyIntolerance' },
  { label: 'Care Plans', value: 'CarePlan' },
];

export function PatientChartPage() {
  const { patientId } = useParams();
  const navigate = useNavigate();
  const patient = useResource<Patient>({ reference: `Patient/${patientId}` });

  const sections = useMemo(
    () =>
      getDefaultSections()
        .filter((s) => KEEP_SECTIONS.has(s.key))
        .map((s) => (s.key === 'vitals' ? VitalsSectionCustom : s)),
    []
  );

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
            navigate(`/Patient/${patientId}/${resource.resourceType}/${resource.id}`)
          }
        />
        <SmartLaunchButton patientId={patientId!} />
      </ScrollArea>
      <div style={{ flex: 1, overflow: 'auto' }}>
        <LinkTabs baseUrl={`/Patient/${patientId}`} tabs={TABS} p="sm" />
        <div style={{ padding: '0 16px 16px' }}>
          <Outlet />
        </div>
      </div>
    </div>
  );
}
