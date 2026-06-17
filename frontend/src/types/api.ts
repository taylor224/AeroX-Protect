export type ApiStatus =
  | 'success'
  | 'bad_request'
  | 'no_permission'
  | 'forbidden'
  | 'not_found'
  | 'conflict'
  | 'too_many_requests'
  | 'internal_server_error';

export interface ApiResponse<T = unknown> {
  status: ApiStatus;
  data?: T;
  message?: string;
  time: string;
}

export type PermissionMap = Record<string, string[]>;

export interface User {
  uuid: string;
  login_id: string;
  name: string;
  email: string | null;
  role: string | null;
  language: 'ko' | 'en';
  permissions: PermissionMap;
}

export interface MenuItem {
  title: string;
  icon: string;
  path: string;
}

export interface LoginResponse {
  access_token: string;
  token_type: 'Bearer';
  expires_in: number;
  user: User;
}

export interface MeResponse {
  user: User;
  permissions: PermissionMap;
  menus: MenuItem[];
}

export interface Pagination {
  page: number;
  items_per_page: number;
  total: number;
  total_pages: number;
}

export interface PageResult<T> {
  items: T[];
  pagination: Pagination;
}

export interface UserRow {
  id: string;
  uuid: string;
  login_id: string;
  name: string;
  email: string | null;
  phone_number: string | null;
  role: string | null;
  role_id: string;
  permissions: PermissionMap;
  language: string;
  is_active: boolean;
  locked_until: number | null;
  last_login_at: number | null;
  created_at: number | null;
  updated_at: number | null;
}

export interface Role {
  id: string;
  name: string;
  display_name: string;
  description: string | null;
  permissions: PermissionMap;
  is_system: boolean;
}

export interface PermissionCatalogItem {
  id: string;
  resource: string;
  action: string;
  description: string | null;
}
