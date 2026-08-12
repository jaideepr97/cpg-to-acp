import {
  ActionGroup,
  Alert,
  Button,
  FileUpload,
  Form,
  FormGroup,
  PageSection,
  Title,
} from '@patternfly/react-core';
import { useMutation } from '@tanstack/react-query';
import { useState } from 'react';
import { useNavigate } from 'react-router';

import { api } from '../api/client';

const MAX_FILE_SIZE = 50 * 1024 * 1024; // 50 MB

export function UploadPage() {
  const navigate = useNavigate();
  const [file, setFile] = useState<File | null>(null);
  const [filename, setFilename] = useState('');
  const [validationError, setValidationError] = useState('');

  const uploadMutation = useMutation({
    mutationFn: (f: File) => api.uploadCpg(f),
    onSuccess: (data) => {
      navigate(`/runs/${data.runId}`);
    },
  });

  function handleFileChange(_: unknown, f: File) {
    setValidationError('');

    if (f.type && f.type !== 'application/pdf') {
      setValidationError('Only PDF files are accepted.');
      setFile(null);
      setFilename('');
      return;
    }

    if (f.size > MAX_FILE_SIZE) {
      setValidationError(`File is too large (${(f.size / 1024 / 1024).toFixed(1)} MB). Maximum size is 50 MB.`);
    }

    setFile(f);
    setFilename(f.name);
  }

  function handleClear() {
    setFile(null);
    setFilename('');
    setValidationError('');
    uploadMutation.reset();
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!file) return;
    uploadMutation.mutate(file);
  }

  return (
    <>
      <PageSection>
        <Title headingLevel="h1">Upload Clinical Practice Guideline</Title>
      </PageSection>
      <PageSection>
        <Form onSubmit={handleSubmit} style={{ maxWidth: 600 }}>
          {uploadMutation.isError && (
            <Alert
              variant="danger"
              title="Upload failed"
              isInline
            >
              {uploadMutation.error instanceof Error
                ? uploadMutation.error.message
                : 'An unexpected error occurred.'}
            </Alert>
          )}

          {validationError && (
            <Alert variant="warning" title={validationError} isInline />
          )}

          <FormGroup label="CPG PDF file" isRequired fieldId="cpg-pdf">
            <FileUpload
              id="cpg-pdf"
              type="text"
              value={file ?? undefined}
              filename={filename}
              filenamePlaceholder="Drag a PDF here or click to upload"
              onFileInputChange={handleFileChange}
              onClearClick={handleClear}
              browseButtonText="Browse"
              accept=".pdf"
              isLoading={uploadMutation.isPending}
            />
          </FormGroup>

          <ActionGroup>
            <Button
              variant="primary"
              type="submit"
              isDisabled={!file || uploadMutation.isPending}
              isLoading={uploadMutation.isPending}
            >
              Start Pipeline
            </Button>
            <Button variant="link" onClick={() => navigate('/')}>
              Cancel
            </Button>
          </ActionGroup>
        </Form>
      </PageSection>
    </>
  );
}
