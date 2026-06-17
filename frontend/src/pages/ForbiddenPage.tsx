import { useIntl } from 'react-intl';
import { Link } from 'react-router-dom';

import { Button } from '@/components/ui/button';

export function ForbiddenPage() {
  const intl = useIntl();
  return (
    <div className="flex h-screen flex-col items-center justify-center gap-4 bg-canvas px-6 text-center">
      <div className="text-5xl font-medium text-white">403</div>
      <div className="text-lg text-white">{intl.formatMessage({ id: 'error.forbidden.title' })}</div>
      <p className="max-w-sm text-sm text-white/60">{intl.formatMessage({ id: 'error.forbidden.desc' })}</p>
      <Button asChild>
        <Link to="/">{intl.formatMessage({ id: 'error.back_home' })}</Link>
      </Button>
    </div>
  );
}
