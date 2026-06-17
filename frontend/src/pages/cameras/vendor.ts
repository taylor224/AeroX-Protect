/** Map stored vendor codes (lowercase) to proper manufacturer display names. */
const VENDOR_NAMES: Record<string, string> = {
  hikvision: 'Hikvision',
  hanwha: 'Hanwha Vision',
  dahua: 'Dahua',
  axis: 'Axis Communications',
  reolink: 'Reolink',
  uniview: 'Uniview',
  bosch: 'Bosch',
  vivotek: 'VIVOTEK',
  onvif: 'ONVIF (generic)',
  unknown: 'Unknown',
};

export function vendorLabel(vendor: string | null | undefined): string {
  if (!vendor) return VENDOR_NAMES.unknown;
  return VENDOR_NAMES[vendor.toLowerCase()] ?? vendor;
}
