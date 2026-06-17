import { api } from '@/lib/axios';

/** Trigger a doorbell ring (SIP/ONVIF adapters call this; also used to demo the call UI). */
export async function ringDoorbell(cameraUuid: string): Promise<void> {
  await api.post(`/cameras/${cameraUuid}/doorbell`, {});
}
