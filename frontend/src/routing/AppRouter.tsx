import { lazy, Suspense } from 'react';
import { Navigate, Route, Routes } from 'react-router-dom';

import { DashboardLayout } from '@/layouts/dashboard/DashboardLayout';
import { ForbiddenPage } from '@/pages/ForbiddenPage';
// Hot-path pages load eagerly; advanced/heavy pages are code-split (lazy) to keep the
// initial bundle small — they're loaded on first navigation.
import { CamerasPage } from '@/pages/cameras/CamerasPage';
import { EventsPage } from '@/pages/events/EventsPage';
import { LivePage } from '@/pages/live/LivePage';
import { LoginPage } from '@/pages/auth/LoginPage';
import { HomeRedirect } from '@/routing/HomeRedirect';
import { ProtectedRoute } from '@/routing/ProtectedRoute';
import { RequirePermission } from '@/routing/RequirePermission';

const lazyPage = <T extends Record<string, React.ComponentType<unknown>>>(
  loader: () => Promise<T>,
  name: keyof T,
) => lazy(() => loader().then((m) => ({ default: m[name] as React.ComponentType<unknown> })));

const SettingsPage = lazyPage(() => import('@/pages/SettingsPage'), 'SettingsPage');
const UsersPage = lazyPage(() => import('@/pages/UsersPage'), 'UsersPage');
const AiPage = lazyPage(() => import('@/pages/ai/AiPage'), 'AiPage');
const AutomationPage = lazyPage(() => import('@/pages/automation/AutomationPage'), 'AutomationPage');
const MonitorsPage = lazyPage(() => import('@/pages/monitors/MonitorsPage'), 'MonitorsPage');
const KioskView = lazyPage(() => import('@/pages/monitor/KioskView'), 'KioskView');
const AccessPage = lazyPage(() => import('@/pages/access/AccessPage'), 'AccessPage');
const ArchivePage = lazyPage(() => import('@/pages/archive/ArchivePage'), 'ArchivePage');
const FacesPage = lazyPage(() => import('@/pages/faces/FacesPage'), 'FacesPage');
const FederationPage = lazyPage(() => import('@/pages/federation/FederationPage'), 'FederationPage');
const LprPage = lazyPage(() => import('@/pages/lpr/LprPage'), 'LprPage');
const MapsPage = lazyPage(() => import('@/pages/maps/MapsPage'), 'MapsPage');
const SemanticSearchPage = lazyPage(() => import('@/pages/search/SemanticSearchPage'), 'SemanticSearchPage');
const ShareViewerPage = lazyPage(() => import('@/pages/share/ShareViewerPage'), 'ShareViewerPage');
const StoragePage = lazyPage(() => import('@/pages/storage/StoragePage'), 'StoragePage');

export function AppRouter() {
  return (
    <Suspense fallback={<div className="flex h-full min-h-screen items-center justify-center text-sm text-muted-foreground">…</div>}>
    <Routes>
      <Route path="/auth/login" element={<LoginPage />} />
      <Route path="/403" element={<ForbiddenPage />} />
      {/* P5 kiosk — standalone, uses its own monitor token (no app shell) */}
      <Route path="/monitor" element={<KioskView />} />
      {/* P6 R1 public share viewer — standalone, share token in URL (no session) */}
      <Route path="/s/:token" element={<ShareViewerPage />} />

      <Route element={<ProtectedRoute />}>
        <Route element={<DashboardLayout />}>
          {/* Home → first page the user can access (permission-safe). */}
          <Route index element={<HomeRedirect />} />
          <Route
            path="/users"
            element={
              <RequirePermission resource="users" action="read">
                <UsersPage />
              </RequirePermission>
            }
          />
          <Route
            path="/settings"
            element={
              <RequirePermission resource="settings" action="read">
                <SettingsPage />
              </RequirePermission>
            }
          />
          {/* P1 */}
          <Route
            path="/live"
            element={
              <RequirePermission resource="live" action="read">
                <LivePage />
              </RequirePermission>
            }
          />
          <Route
            path="/live/:dashboardUuid"
            element={
              <RequirePermission resource="live" action="read">
                <LivePage />
              </RequirePermission>
            }
          />
          <Route
            path="/cameras"
            element={
              <RequirePermission resource="cameras" action="read">
                <CamerasPage />
              </RequirePermission>
            }
          />
          {/* Dashboards are now created/managed inside the Live page; keep the old path as a redirect */}
          <Route path="/dashboards" element={<Navigate to="/live" replace />} />
          {/* P2 — recordings merged into Events; keep the old path as a redirect */}
          <Route path="/playback" element={<Navigate to="/events" replace />} />
          <Route
            path="/storage"
            element={
              <RequirePermission resource="storage" action="read">
                <StoragePage />
              </RequirePermission>
            }
          />
          {/* P6 L6 maps */}
          <Route
            path="/maps"
            element={
              <RequirePermission resource="maps" action="read">
                <MapsPage />
              </RequirePermission>
            }
          />
          {/* P6 M2 archiving */}
          <Route
            path="/archive"
            element={
              <RequirePermission resource="archive" action="read">
                <ArchivePage />
              </RequirePermission>
            }
          />
          {/* P7 A7 LPR */}
          <Route
            path="/lpr"
            element={
              <RequirePermission resource="lpr" action="read">
                <LprPage />
              </RequirePermission>
            }
          />
          {/* P7 A8 face */}
          <Route
            path="/faces"
            element={
              <RequirePermission resource="face" action="read">
                <FacesPage />
              </RequirePermission>
            }
          />
          {/* P8 multi-NVR federation */}
          <Route
            path="/federation"
            element={
              <RequirePermission resource="federation" action="read">
                <FederationPage />
              </RequirePermission>
            }
          />
          {/* P10 access control */}
          <Route
            path="/access"
            element={
              <RequirePermission resource="access" action="read">
                <AccessPage />
              </RequirePermission>
            }
          />
          {/* P3 */}
          <Route
            path="/events"
            element={
              <RequirePermission resource="events" action="read">
                <EventsPage />
              </RequirePermission>
            }
          />
          {/* P4 */}
          <Route
            path="/ai"
            element={
              <RequirePermission resource="ai" action="read">
                <AiPage />
              </RequirePermission>
            }
          />
          {/* P6 A1 semantic search */}
          <Route
            path="/search"
            element={
              <RequirePermission resource="ai" action="semantic_search">
                <SemanticSearchPage />
              </RequirePermission>
            }
          />
          {/* P5 */}
          <Route
            path="/rules"
            element={
              <RequirePermission resource="rules" action="read">
                <AutomationPage />
              </RequirePermission>
            }
          />
          <Route
            path="/monitors"
            element={
              <RequirePermission resource="monitors" action="read">
                <MonitorsPage />
              </RequirePermission>
            }
          />
        </Route>
      </Route>

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
    </Suspense>
  );
}
