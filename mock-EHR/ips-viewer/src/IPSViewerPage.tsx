import FHIR from 'fhirclient';
import type Client from 'fhirclient/lib/Client';
import { useEffect, useState } from 'react';

interface FHIRResource {
  resourceType: string;
  id?: string;
  [key: string]: unknown;
}

interface IPSData {
  patient: FHIRResource | null;
  conditions: FHIRResource[];
  medications: FHIRResource[];
  allergies: FHIRResource[];
  observations: FHIRResource[];
}

function parseIPS(bundle: FHIRResource): IPSData {
  const entries = (bundle.entry as { resource: FHIRResource }[]) ?? [];
  const resources = entries.map((e) => e.resource);
  return {
    patient: resources.find((r) => r.resourceType === 'Patient') ?? null,
    conditions: resources.filter((r) => r.resourceType === 'Condition'),
    medications: resources.filter((r) => r.resourceType === 'MedicationRequest' || r.resourceType === 'MedicationStatement'),
    allergies: resources.filter((r) => r.resourceType === 'AllergyIntolerance'),
    observations: resources.filter((r) => r.resourceType === 'Observation'),
  };
}

function getCodeText(resource: FHIRResource): string {
  const code = resource.code as { text?: string; coding?: { display?: string }[] } | undefined;
  return code?.text ?? code?.coding?.[0]?.display ?? '?';
}

function getMedText(resource: FHIRResource): string {
  const med = resource.medicationCodeableConcept as { text?: string; coding?: { display?: string }[] } | undefined;
  return med?.text ?? med?.coding?.[0]?.display ?? '?';
}

function getObsValue(resource: FHIRResource): string {
  const components = resource.component as { code?: { coding?: { code?: string }[] }; valueQuantity?: { value?: number; unit?: string } }[] | undefined;
  if (components) {
    const sys = components.find((c) => c.code?.coding?.[0]?.code === '8480-6');
    const dia = components.find((c) => c.code?.coding?.[0]?.code === '8462-4');
    if (sys?.valueQuantity && dia?.valueQuantity) {
      return `${sys.valueQuantity.value}/${dia.valueQuantity.value} mmHg`;
    }
    return components.map((c) => `${c.valueQuantity?.value ?? '?'} ${c.valueQuantity?.unit ?? ''}`).join(', ');
  }
  const vq = resource.valueQuantity as { value?: number; unit?: string } | undefined;
  if (vq) return `${vq.value} ${vq.unit ?? ''}`.trim();
  if (resource.valueString) return resource.valueString as string;
  return '';
}

function getPatientName(patient: FHIRResource): string {
  const names = patient.name as { given?: string[]; family?: string }[] | undefined;
  if (!names?.[0]) return '?';
  return `${names[0].given?.join(' ') ?? ''} ${names[0].family ?? ''}`.trim();
}

function getPatientAge(patient: FHIRResource): string {
  const dob = patient.birthDate as string | undefined;
  if (!dob) return '?';
  const years = Math.floor((Date.now() - new Date(dob).getTime()) / (365.25 * 24 * 60 * 60 * 1000));
  return `${years}yo`;
}

export function IPSViewerPage() {
  const [ips, setIps] = useState<IPSData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    FHIR.oauth2.ready()
      .then(async (client: Client) => {
        const patientId = client.patient.id;
        if (!patientId) throw new Error('No patient context');
        const bundle = await client.request(`Patient/${patientId}/$summary`);
        setIps(parseIPS(bundle));
      })
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <div style={styles.container}><p>Loading patient summary...</p></div>;
  if (error) return <div style={styles.container}><p style={{ color: 'red' }}>Error: {error}</p></div>;
  if (!ips?.patient) return <div style={styles.container}><p>No patient data</p></div>;

  const patient = ips.patient;

  return (
    <div style={styles.container}>
      <h1 style={styles.title}>International Patient Summary</h1>

      <div style={styles.banner}>
        <strong>{getPatientName(patient)}</strong>
        <span style={styles.bannerDetail}>
          {getPatientAge(patient)} {(patient.gender as string) ?? ''} | DOB: {(patient.birthDate as string) ?? '?'}
        </span>
      </div>

      <Section title="Problem List" items={ips.conditions} renderItem={(r) => getCodeText(r)} />
      <Section title="Medications" items={ips.medications} renderItem={(r) => getMedText(r)} />
      <Section
        title="Allergies"
        items={ips.allergies}
        renderItem={(r) => {
          const code = getCodeText(r);
          const criticality = (r.criticality as string) ?? '';
          return `${code}${criticality ? ` (${criticality})` : ''}`;
        }}
      />
      <Section
        title="Vital Signs"
        items={ips.observations.filter((r) => {
          const cats = r.category as { coding?: { code?: string }[] }[] | undefined;
          return cats?.some((c) => c.coding?.some((cc) => cc.code === 'vital-signs'));
        })}
        renderItem={(r) => {
          const date = (r.effectiveDateTime as string) ?? '';
          const dateStr = date ? new Date(date).toLocaleDateString() : '';
          return `${getCodeText(r)}: ${getObsValue(r)}${dateStr ? ` (${dateStr})` : ''}`;
        }}
      />
      <Section
        title="Lab Results"
        items={ips.observations.filter((r) => {
          const cats = r.category as { coding?: { code?: string }[] }[] | undefined;
          return cats?.some((c) => c.coding?.some((cc) => cc.code === 'laboratory'));
        })}
        renderItem={(r) => {
          const date = (r.effectiveDateTime as string) ?? '';
          const dateStr = date ? new Date(date).toLocaleDateString() : '';
          return `${getCodeText(r)}: ${getObsValue(r)}${dateStr ? ` (${dateStr})` : ''}`;
        }}
      />
    </div>
  );
}

function Section({ title, items, renderItem }: { title: string; items: FHIRResource[]; renderItem: (r: FHIRResource) => string }) {
  return (
    <div style={styles.section}>
      <h2 style={styles.sectionTitle}>{title}</h2>
      {items.length === 0 ? (
        <p style={styles.empty}>(none)</p>
      ) : (
        <ul style={styles.list}>
          {items.map((item, i) => (
            <li key={item.id ?? i}>{renderItem(item)}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  container: { maxWidth: 800, margin: '0 auto', padding: 24, fontFamily: 'system-ui, sans-serif' },
  title: { fontSize: '1.5rem', fontWeight: 600, marginBottom: 16, color: '#1a5276' },
  banner: { background: '#eaf2f8', padding: '12px 16px', borderRadius: 8, marginBottom: 24, display: 'flex', justifyContent: 'space-between', alignItems: 'center' },
  bannerDetail: { color: '#555', fontSize: '0.9rem' },
  section: { marginBottom: 20 },
  sectionTitle: { fontSize: '1.1rem', fontWeight: 600, borderBottom: '1px solid #ddd', paddingBottom: 4, marginBottom: 8 },
  list: { margin: 0, paddingLeft: 20 },
  empty: { color: '#888', fontStyle: 'italic' },
};
