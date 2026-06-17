import {
  Archive,
  Bell,
  Camera,
  DoorOpen,
  HardDrive,
  Map,
  MonitorPlay,
  Network,
  ScanFace,
  ScanLine,
  Search,
  Settings,
  Sparkles,
  Users,
  Video,
  Workflow,
  type LucideIcon,
} from 'lucide-react';

export interface NavItem {
  titleId: string;
  icon: LucideIcon;
  path: string;
  /** Required permission to see this item; omitted = always visible to any authed user. */
  resource?: string;
  action?: string;
  /** Optional feature flag that must be enabled for this item to appear. */
  flag?: string;
}

// Phases append entries here + guard their pages with <RequirePermission>.
export const NAV_ITEMS: NavItem[] = [
  { titleId: 'menu.live', icon: Video, path: '/live', resource: 'live', action: 'read' },
  { titleId: 'menu.events', icon: Bell, path: '/events', resource: 'events', action: 'read' },
  { titleId: 'menu.cameras', icon: Camera, path: '/cameras', resource: 'cameras', action: 'read' },
  { titleId: 'menu.storage', icon: HardDrive, path: '/storage', resource: 'storage', action: 'read' },
  { titleId: 'menu.archive', icon: Archive, path: '/archive', resource: 'archive', action: 'read' },
  { titleId: 'menu.monitors', icon: MonitorPlay, path: '/monitors', resource: 'monitors', action: 'read' },
  { titleId: 'menu.maps', icon: Map, path: '/maps', resource: 'maps', action: 'read' },
  { titleId: 'menu.rules', icon: Workflow, path: '/rules', resource: 'rules', action: 'read' },
  { titleId: 'menu.ai', icon: Sparkles, path: '/ai', resource: 'ai', action: 'read' },
  { titleId: 'menu.search', icon: Search, path: '/search', resource: 'ai', action: 'semantic_search' },
  { titleId: 'menu.lpr', icon: ScanLine, path: '/lpr', resource: 'lpr', action: 'read' },
  { titleId: 'menu.faces', icon: ScanFace, path: '/faces', resource: 'face', action: 'read' },
  { titleId: 'menu.federation', icon: Network, path: '/federation', resource: 'federation', action: 'read', flag: 'federation' },
  { titleId: 'menu.access', icon: DoorOpen, path: '/access', resource: 'access', action: 'read' },
  { titleId: 'menu.users', icon: Users, path: '/users', resource: 'users', action: 'read' },
  { titleId: 'menu.settings', icon: Settings, path: '/settings', resource: 'settings', action: 'read' },
];
