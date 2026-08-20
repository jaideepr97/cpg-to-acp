import {
  CodeBlock,
  CodeBlockCode,
  ExpandableSection,
} from "@patternfly/react-core";

export interface FhirJsonViewerProps {
  json: object | string;
  title?: string;
  collapsible?: boolean;
}

export function FhirJsonViewer({
  json,
  title = "FHIR JSON",
  collapsible = true,
}: FhirJsonViewerProps) {
  const formatted = typeof json === "string" ? json : JSON.stringify(json, null, 2);

  const codeBlock = (
    <CodeBlock>
      <CodeBlockCode>{formatted}</CodeBlockCode>
    </CodeBlock>
  );

  if (!collapsible) return codeBlock;

  return (
    <ExpandableSection toggleText={title} isIndented>
      {codeBlock}
    </ExpandableSection>
  );
}
