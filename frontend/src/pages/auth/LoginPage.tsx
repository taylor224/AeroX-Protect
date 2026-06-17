import { zodResolver } from '@hookform/resolvers/zod';
import { AxiosError } from 'axios';
import { useForm } from 'react-hook-form';
import { useIntl } from 'react-intl';
import { Navigate, useLocation, useNavigate } from 'react-router-dom';
import { toast } from 'sonner';
import { z } from 'zod';

import { useAuthContext } from '@/auth/useAuthContext';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';

const schema = z.object({
  login_id: z.string().min(1),
  password: z.string().min(1),
});
type FormValues = z.infer<typeof schema>;

interface LocationState {
  from?: { pathname?: string };
}

export function LoginPage() {
  const intl = useIntl();
  const navigate = useNavigate();
  const location = useLocation();
  const { login, isAuthenticated, loading } = useAuthContext();

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { login_id: '', password: '' },
  });

  if (!loading && isAuthenticated) return <Navigate to="/" replace />;

  const onSubmit = async (values: FormValues) => {
    try {
      await login(values.login_id, values.password);
      const to = (location.state as LocationState | null)?.from?.pathname ?? '/';
      navigate(to, { replace: true });
    } catch (error) {
      const status = (error as AxiosError).response?.status;
      toast.error(
        intl.formatMessage({ id: status === 429 ? 'auth.login.locked' : 'auth.login.error' }),
      );
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-canvas px-4">
      <div className="w-full max-w-sm rounded-lg border border-border bg-background p-8">
        <div className="mb-8 text-center">
          <div className="text-xl font-semibold tracking-tight text-foreground">AeroX Protect</div>
          <div className="mt-1 text-xs text-muted-foreground">
            {intl.formatMessage({ id: 'app.tagline' })}
          </div>
        </div>

        <form onSubmit={handleSubmit(onSubmit)} className="space-y-6" noValidate>
          <div className="space-y-1.5">
            <Label htmlFor="login_id">{intl.formatMessage({ id: 'auth.login.id' })}</Label>
            <Input
              id="login_id"
              autoComplete="username"
              autoFocus
              placeholder={intl.formatMessage({ id: 'auth.login.id.placeholder' })}
              aria-invalid={!!errors.login_id}
              {...register('login_id')}
            />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="password">{intl.formatMessage({ id: 'auth.login.password' })}</Label>
            <Input
              id="password"
              type="password"
              autoComplete="current-password"
              placeholder={intl.formatMessage({ id: 'auth.login.password.placeholder' })}
              aria-invalid={!!errors.password}
              {...register('password')}
            />
          </div>

          <Button type="submit" className="mt-2 w-full" disabled={isSubmitting}>
            {intl.formatMessage({ id: 'auth.login.submit' })}
          </Button>
        </form>
      </div>
    </div>
  );
}
