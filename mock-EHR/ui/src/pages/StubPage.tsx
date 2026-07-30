import type { ResourceType } from '@medplum/fhirtypes';
import { Document, SearchControl } from '@medplum/react';

interface StubPageProps {
  resourceType: ResourceType;
}

export function StubPage({ resourceType }: StubPageProps) {
  return (
    <Document>
      <SearchControl
        search={{
          resourceType,
          fields: ['_id', '_lastUpdated'],
          sortRules: [{ code: '-_lastUpdated' }],
          count: 20,
        }}
        hideToolbar
      />
    </Document>
  );
}
