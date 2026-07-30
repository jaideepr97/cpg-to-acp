import { AppShell } from '@medplum/react';
import { useMedplumProfile } from '@medplum/react-hooks';
import {
  IconCalendarEvent,
  IconClipboardCheck,
  IconMail,
  IconStethoscope,
  IconUsers,
} from '@tabler/icons-react';
import { Navigate, Route, Routes, useLocation, useSearchParams } from 'react-router';
import { APP_NAME } from './config';
import { AllergiesTab } from './pages/AllergiesTab';
import { CarePlansTab } from './pages/CarePlansTab';
import { EncountersTab } from './pages/EncountersTab';
import { LabsTab } from './pages/LabsTab';
import { MedicationsTab } from './pages/MedicationsTab';
import { PatientChartPage } from './pages/PatientChartPage';
import { PatientListPage } from './pages/PatientListPage';
import { SignInPage } from './pages/SignInPage';
import { StubPage } from './pages/StubPage';
import { TimelineTab } from './pages/TimelineTab';

export function App() {
  const profile = useMedplumProfile();
  const location = useLocation();
  const [searchParams] = useSearchParams();

  if (!profile) {
    return (
      <Routes>
        <Route path="/signin" element={<SignInPage />} />
        <Route path="*" element={<Navigate to="/signin" replace />} />
      </Routes>
    );
  }

  return (
    <AppShell
      logo={
        <>
          <IconStethoscope size={24} />
          <span style={{ marginLeft: 8, fontWeight: 600 }}>{APP_NAME}</span>
        </>
      }
      pathname={location.pathname}
      searchParams={searchParams}
      resourceTypeSearchDisabled
      headerSearchDisabled
      menus={[
        {
          title: 'Navigation',
          links: [
            { icon: <IconUsers />, label: 'Patients', href: '/Patient' },
            { icon: <IconCalendarEvent />, label: 'Schedule', href: '/Schedule' },
            { icon: <IconMail />, label: 'Messages', href: '/Communication' },
            { icon: <IconClipboardCheck />, label: 'Tasks', href: '/Task' },
          ],
        },
      ]}
    >
      <Routes>
        <Route path="/" element={<Navigate to="/Patient" replace />} />
        <Route path="/signin" element={<Navigate to="/Patient" replace />} />
        <Route path="/Patient" element={<PatientListPage />} />
        <Route path="/Patient/:patientId" element={<PatientChartPage />}>
          <Route index element={<TimelineTab />} />
          <Route path="timeline" element={<TimelineTab />} />
          <Route path="MedicationRequest" element={<MedicationsTab />} />
          <Route path="DiagnosticReport" element={<LabsTab />} />
          <Route path="AllergyIntolerance" element={<AllergiesTab />} />
          <Route path="CarePlan" element={<CarePlansTab />} />
          <Route path="Encounter" element={<EncountersTab />} />
        </Route>
        <Route path="/Schedule" element={<StubPage resourceType="Schedule" />} />
        <Route path="/Communication" element={<StubPage resourceType="Communication" />} />
        <Route path="/Task" element={<StubPage resourceType="Task" />} />
      </Routes>
    </AppShell>
  );
}
