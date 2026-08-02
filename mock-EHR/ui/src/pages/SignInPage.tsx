import { Title } from '@mantine/core';
import { SignInForm } from '@medplum/react';
import { IconStethoscope } from '@tabler/icons-react';
import { useNavigate, useSearchParams } from 'react-router';
import { APP_NAME } from '../config';

export function SignInPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();

  return (
    <SignInForm
      projectId={searchParams.get('project') || undefined}
      disableGoogleAuth
      onSuccess={() => navigate('/')}
    >
      <IconStethoscope size={32} />
      <Title order={3}>Sign in to {APP_NAME}</Title>
    </SignInForm>
  );
}
