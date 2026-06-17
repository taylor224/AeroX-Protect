import { api } from '@/lib/axios';
import type { ApiResponse } from '@/types/api';

export interface GeneralSettings {
  timezone: string;
  /** Base URL for public share links (blank → use the current browser origin). */
  public_base_url: string;
  /** Site default UI language for new users / first visit. */
  default_language: 'ko' | 'en';
  /** Server LAN IP advertised as a WebRTC ICE candidate (blank → WebRTC off, MSE fallback). */
  webrtc_candidate_ip: string;
}

export async function getGeneralSettings(): Promise<GeneralSettings> {
  const { data } = await api.get<ApiResponse<GeneralSettings>>('/settings/general');
  return data.data as GeneralSettings;
}

export async function updateGeneralSettings(body: Partial<GeneralSettings>): Promise<GeneralSettings> {
  const { data } = await api.put<ApiResponse<GeneralSettings>>('/settings/general', body);
  return data.data as GeneralSettings;
}

/** Twilio SMS account status. The auth token is write-only — never returned, only `has_token`. */
export interface TwilioStatus {
  account_sid: string | null;
  from_number: string | null;
  has_token: boolean;
  configured: boolean;
  source: 'db' | 'env' | 'none';
}

export interface TwilioUpdate {
  account_sid?: string;
  auth_token?: string;   // omit = leave as-is, '' = clear
  from_number?: string;
}

export async function getTwilioConfig(): Promise<TwilioStatus> {
  const { data } = await api.get<ApiResponse<TwilioStatus>>('/settings/twilio');
  return data.data as TwilioStatus;
}

export async function updateTwilioConfig(body: TwilioUpdate): Promise<TwilioStatus> {
  const { data } = await api.put<ApiResponse<TwilioStatus>>('/settings/twilio', body);
  return data.data as TwilioStatus;
}

/** A practical list of site timezones; the browser's own zone is added on top at runtime. */
export const COMMON_TIMEZONES = [
  'UTC',
  'Asia/Seoul', 'Asia/Tokyo', 'Asia/Shanghai', 'Asia/Hong_Kong', 'Asia/Singapore',
  'Asia/Bangkok', 'Asia/Kolkata', 'Asia/Dubai',
  'Europe/London', 'Europe/Paris', 'Europe/Berlin', 'Europe/Moscow',
  'America/New_York', 'America/Chicago', 'America/Denver', 'America/Los_Angeles', 'America/Sao_Paulo',
  'Australia/Sydney',
];
