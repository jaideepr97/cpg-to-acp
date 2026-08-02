import { formatHumanName, formatSearchQuery, parseSearchRequest } from '@medplum/core';
import type { Patient, Resource } from '@medplum/fhirtypes';
import { Document, SearchControl } from '@medplum/react';
import { useMemo } from 'react';
import { useNavigate, useLocation } from 'react-router';

function getOfficialName(resource: Resource): string {
  const patient = resource as Patient;
  const names = patient.name ?? [];
  const official = names.find((n) => n.use === 'official') ?? names[0];
  return official ? formatHumanName(official) : '?';
}

function getDobGender(resource: Resource): string {
  const patient = resource as Patient;
  const parts: string[] = [];
  if (patient.birthDate) parts.push(patient.birthDate);
  if (patient.gender) parts.push(patient.gender);
  return parts.join(' | ');
}

const ADDITIONAL_COLUMNS = [
  { name: 'Name', renderCell: getOfficialName },
  { name: 'DOB / Gender', renderCell: getDobGender },
];

const DEFAULT_SEARCH = {
  resourceType: 'Patient' as const,
  fields: ['_lastUpdated'],
  sortRules: [{ code: '_lastUpdated', descending: true }],
  count: 20,
};

export function PatientListPage() {
  const navigate = useNavigate();
  const location = useLocation();

  const search = useMemo(() => {
    const parsed = parseSearchRequest(location.pathname + location.search);
    return parsed.resourceType === 'Patient' ? { ...DEFAULT_SEARCH, ...parsed } : DEFAULT_SEARCH;
  }, [location]);

  return (
    <Document>
      <SearchControl
        search={search}
        additionalColumns={ADDITIONAL_COLUMNS}
        onClick={(e) => navigate(`/Patient/${e.resource.id}`)?.catch(console.error)}
        onAuxClick={(e) => window.open(`/Patient/${e.resource.id}`, '_blank')}
        onChange={(e) => navigate(`/Patient${formatSearchQuery(e.definition)}`)?.catch(console.error)}
      />
    </Document>
  );
}
