import { useState } from 'react';
import { Outlet } from 'react-router-dom';

import { Sidebar } from '@/layouts/dashboard/Sidebar';
import { Topbar } from '@/layouts/dashboard/Topbar';
import { DoorbellWatcher } from '@/pages/doorbell/DoorbellWatcher';

export function DashboardLayout() {
  const [mobileOpen, setMobileOpen] = useState(false);

  return (
    <div className="flex h-screen overflow-hidden bg-canvas">
      {/* desktop sidebar */}
      <div className="hidden md:block">
        <Sidebar />
      </div>

      {/* mobile drawer */}
      {mobileOpen && (
        <div className="fixed inset-0 z-40 md:hidden">
          <div className="absolute inset-0 bg-canvas/60" onClick={() => setMobileOpen(false)} />
          <div className="absolute left-0 top-0 h-full">
            <Sidebar onNavigate={() => setMobileOpen(false)} />
          </div>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <Topbar onMenuClick={() => setMobileOpen(true)} />
        <main className="flex-1 overflow-auto bg-secondary p-6 md:p-8 text-foreground">
          <Outlet />
        </main>
      </div>
      <DoorbellWatcher />
    </div>
  );
}
