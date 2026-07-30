import { Document, SearchControl } from '@medplum/react';
import { useNavigate, useLocation } from 'react-router';
import { formatSearchQuery, parseSearchRequest } from '@medplum/core';
import { useMemo } from 'react';

const DEFAULT_SEARCH = {
  resourceType: 'Patient' as const,
  fields: ['name', 'birthDate', 'gender', '_lastUpdated'],
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
        onClick={(e) => navigate(`/Patient/${e.resource.id}`)?.catch(console.error)}
        onAuxClick={(e) => window.open(`/Patient/${e.resource.id}`, '_blank')}
        onChange={(e) => navigate(`/Patient${formatSearchQuery(e.definition)}`)?.catch(console.error)}
      />
    </Document>
  );
}
