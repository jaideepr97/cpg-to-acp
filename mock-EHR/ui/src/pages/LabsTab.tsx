import { Operator } from '@medplum/core';
import type { DiagnosticReport } from '@medplum/fhirtypes';
import { DiagnosticReportDisplay, SearchControl } from '@medplum/react';
import { useResource } from '@medplum/react-hooks';
import { useState } from 'react';
import { useParams } from 'react-router';

export function LabsTab() {
  const { patientId } = useParams();
  const [selectedId, setSelectedId] = useState<string>();
  const selectedReport = useResource<DiagnosticReport>(
    selectedId ? { reference: `DiagnosticReport/${selectedId}` } : undefined
  );

  return (
    <div style={{ display: 'flex', gap: 16 }}>
      <div style={{ width: 300, flexShrink: 0 }}>
        <SearchControl
          search={{
            resourceType: 'DiagnosticReport',
            fields: ['code', 'status', 'issued'],
            filters: [
              { code: 'patient', operator: Operator.EQUALS, value: `Patient/${patientId}` },
              { code: 'category', operator: Operator.EQUALS, value: 'LAB' },
            ],
            sortRules: [{ code: '-issued' }],
          }}
          onClick={(e) => setSelectedId(e.resource.id)}
          hideToolbar
        />
      </div>
      <div style={{ flex: 1 }}>
        {selectedReport ? (
          <DiagnosticReportDisplay value={selectedReport} />
        ) : (
          <div style={{ color: 'var(--mantine-color-dimmed)', padding: 16 }}>
            Select a lab report to view results
          </div>
        )}
      </div>
    </div>
  );
}
