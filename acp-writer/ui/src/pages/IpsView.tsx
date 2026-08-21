import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Button,
  Card,
  CardBody,
  DataList,
  DataListCell,
  DataListItem,
  DataListItemCells,
  DataListItemRow,
  DescriptionList,
  DescriptionListDescription,
  DescriptionListGroup,
  DescriptionListTerm,
  FileUpload,
  Flex,
  FlexItem,
  Label,
  PageSection,
  Stack,
  StackItem,
  Title,
} from "@patternfly/react-core";
import { FhirJsonViewer } from "@app/components/FhirJsonViewer";
import { createRun } from "@app/services/api";
import { SMART_SESSION_KEY } from "@app/pages/SmartLaunchPage";

interface FhirResource {
  resourceType: string;
  [key: string]: unknown;
}

interface FhirBundle {
  resourceType: "Bundle";
  entry?: Array<{ resource: FhirResource }>;
  [key: string]: unknown;
}

function getResources(bundle: FhirBundle, type: string): FhirResource[] {
  return (bundle.entry ?? [])
    .map((e) => e.resource)
    .filter((r) => r.resourceType === type);
}

function PatientSection({ patient }: { patient: FhirResource }) {
  const name = (patient.name as Array<{ given?: string[]; family?: string }>)?.[0];
  const displayName = name
    ? `${(name.given ?? []).join(" ")} ${name.family ?? ""}`.trim()
    : "Unknown";
  return (
    <Card>
      <CardBody>
        <Title headingLevel="h3">Demographics</Title>
        <DescriptionList isHorizontal>
          <DescriptionListGroup>
            <DescriptionListTerm>Name</DescriptionListTerm>
            <DescriptionListDescription>{displayName}</DescriptionListDescription>
          </DescriptionListGroup>
          <DescriptionListGroup>
            <DescriptionListTerm>Date of Birth</DescriptionListTerm>
            <DescriptionListDescription>
              {(patient.birthDate as string) ?? "Unknown"}
            </DescriptionListDescription>
          </DescriptionListGroup>
          <DescriptionListGroup>
            <DescriptionListTerm>Gender</DescriptionListTerm>
            <DescriptionListDescription>
              {(patient.gender as string) ?? "Unknown"}
            </DescriptionListDescription>
          </DescriptionListGroup>
        </DescriptionList>
      </CardBody>
    </Card>
  );
}

function ResourceListSection({
  title,
  resources,
  displayFn,
}: {
  title: string;
  resources: FhirResource[];
  displayFn: (r: FhirResource) => { label: string; detail?: string };
}) {
  return (
    <Card>
      <CardBody>
        <Title headingLevel="h3">{title}</Title>
        {resources.length === 0 ? (
          <p>(none recorded)</p>
        ) : (
          <DataList aria-label={title} isCompact>
            {resources.map((r, i) => {
              const { label, detail } = displayFn(r);
              return (
                <DataListItem key={i}>
                  <DataListItemRow>
                    <DataListItemCells
                      dataListCells={[
                        <DataListCell key="label">{label}</DataListCell>,
                        detail ? (
                          <DataListCell key="detail">
                            <Label isCompact>{detail}</Label>
                          </DataListCell>
                        ) : null,
                      ].filter(Boolean)}
                    />
                  </DataListItemRow>
                </DataListItem>
              );
            })}
          </DataList>
        )}
      </CardBody>
    </Card>
  );
}

function codingDisplay(r: FhirResource): { label: string; detail?: string } {
  const code = (r.code as { text?: string; coding?: Array<{ display?: string; code?: string; system?: string }> }) ?? {};
  const label = code.text ?? code.coding?.[0]?.display ?? "Unknown";
  const detail = code.coding?.[0]?.code;
  return { label, detail };
}

export function IpsView() {
  const [bundle, setBundle] = useState<FhirBundle | null>(null);
  const [smartLaunched, setSmartLaunched] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();

  useEffect(() => {
    const stored = sessionStorage.getItem(SMART_SESSION_KEY);
    if (stored) {
      try {
        const parsed = JSON.parse(stored) as FhirBundle;
        if (parsed.resourceType === "Bundle") {
          setBundle(parsed);
          setSmartLaunched(true);
        }
      } catch { /* ignore malformed data */ }
      sessionStorage.removeItem(SMART_SESSION_KEY);
    }
  }, []);

  const handleFileUpload = async (_: unknown, file: File) => {
    setUploading(true);
    setError(null);
    try {
      const text = await file.text();
      const parsed = JSON.parse(text) as FhirBundle;
      if (parsed.resourceType !== "Bundle") {
        setError("File must be a FHIR Bundle");
        return;
      }
      setBundle(parsed);
    } catch {
      setError("Invalid JSON file");
    } finally {
      setUploading(false);
    }
  };

  const handleGenerate = async () => {
    if (!bundle) return;
    setGenerating(true);
    setError(null);
    try {
      const result = await createRun(bundle);
      navigate(`/runs/${result.runId}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Generation failed");
      setGenerating(false);
    }
  };

  const patients = bundle ? getResources(bundle, "Patient") : [];
  const conditions = bundle ? getResources(bundle, "Condition") : [];
  const medications = bundle
    ? [
        ...getResources(bundle, "MedicationStatement"),
        ...getResources(bundle, "MedicationRequest"),
      ]
    : [];
  const allergies = bundle ? getResources(bundle, "AllergyIntolerance") : [];
  const observations = bundle ? getResources(bundle, "Observation") : [];
  const immunizations = bundle ? getResources(bundle, "Immunization") : [];

  return (
    <>
      <PageSection>
        <Flex
          direction={{ default: "row" }}
          alignItems={{ default: "alignItemsCenter" }}
          justifyContent={{ default: "justifyContentSpaceBetween" }}
        >
          <FlexItem>
            <Title headingLevel="h1">Care Plan Generator</Title>
            <p>
              {smartLaunched
                ? "Patient data loaded from EHR. Review the summary below and generate a care plan."
                : "Upload a FHIR IPS Bundle to generate a patient-specific care plan."}
            </p>
          </FlexItem>
        </Flex>
      </PageSection>

      <PageSection isFilled>
        {!smartLaunched && (
          <Flex gap={{ default: "gapMd" }} alignItems={{ default: "alignItemsCenter" }} style={{ marginBottom: "1rem" }}>
            <FlexItem grow={{ default: "grow" }}>
              <FileUpload
                id="ips-upload"
                accept=".json"
                filename={bundle ? "IPS Bundle loaded" : ""}
                onFileInputChange={handleFileUpload}
                isLoading={uploading}
                browseButtonText="Upload IPS Bundle"
              />
            </FlexItem>
          </Flex>
        )}
        {error && <p style={{ color: "var(--pf-t--global--color--status--danger--default)" }}>{error}</p>}

        {bundle && (
          <Stack hasGutter>
            <StackItem>
              <Title headingLevel="h2">Patient International Patient Summary (IPS)</Title>
              <p>This data will be sent to generate the care plan.</p>
            </StackItem>

            {patients[0] && <StackItem><PatientSection patient={patients[0]} /></StackItem>}

            <StackItem>
              <ResourceListSection title="Active Conditions" resources={conditions} displayFn={codingDisplay} />
            </StackItem>
            <StackItem>
              <ResourceListSection title="Medications" resources={medications} displayFn={codingDisplay} />
            </StackItem>
            <StackItem>
              <ResourceListSection
                title="Allergies"
                resources={allergies}
                displayFn={(r) => ({ label: (r.code as { text?: string })?.text ?? "Unknown" })}
              />
            </StackItem>
            <StackItem>
              <ResourceListSection title="Observations / Vitals" resources={observations} displayFn={codingDisplay} />
            </StackItem>
            <StackItem>
              <ResourceListSection
                title="Immunizations"
                resources={immunizations}
                displayFn={(r) => ({ label: (r.vaccineCode as { text?: string })?.text ?? "Unknown" })}
              />
            </StackItem>

            <StackItem>
              <Flex gap={{ default: "gapMd" }}>
                <FlexItem>
                  <Button variant="primary" onClick={handleGenerate} isLoading={generating} isDisabled={generating}>
                    Generate Care Plan
                  </Button>
                </FlexItem>
              </Flex>
            </StackItem>
            <StackItem>
              <FhirJsonViewer json={bundle} title="View FHIR Bundle JSON" />
            </StackItem>
          </Stack>
        )}
      </PageSection>
    </>
  );
}
