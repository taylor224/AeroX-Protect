import { Mic, MicOff } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { useIntl } from 'react-intl';
import { toast } from 'sonner';

import { getIceServers } from '@/pages/live/portal.api';
import { talkOffer, talkStop } from '@/pages/live/talk.api';

/** Push-to-talk toggle: click to open a two-way audio session to the camera, click to end.
 *  Sends mic audio (sendrecv) via the backend backchannel relay; plays camera audio back. */
export function TalkButton({ cameraUuid }: { cameraUuid: string }) {
  const intl = useIntl();
  const [active, setActive] = useState(false);
  const [busy, setBusy] = useState(false);
  const pcRef = useRef<RTCPeerConnection | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  const cleanup = () => {
    pcRef.current?.close();
    pcRef.current = null;
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    if (audioRef.current) audioRef.current.srcObject = null;
  };

  useEffect(() => () => cleanup(), []);

  const stop = () => {
    cleanup();
    void talkStop(cameraUuid);
    setActive(false);
  };

  const start = async () => {
    setBusy(true);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      const pc = new RTCPeerConnection({ iceServers: await getIceServers() });
      pcRef.current = pc;
      stream.getTracks().forEach((t) => pc.addTrack(t, stream)); // sendrecv audio
      pc.ontrack = (e) => {
        if (audioRef.current) audioRef.current.srcObject = e.streams[0]; // camera audio back
      };
      const offer = await pc.createOffer();
      await pc.setLocalDescription(offer);
      const res = await talkOffer(cameraUuid, offer.sdp ?? '');
      if (!res.ok) {
        cleanup();
        toast.error(intl.formatMessage({ id: res.status === 429 ? 'talk.busy' : 'common.error' }));
        return;
      }
      if (res.sdp) await pc.setRemoteDescription({ type: 'answer', sdp: res.sdp });
      setActive(true);
    } catch {
      cleanup();
      toast.error(intl.formatMessage({ id: 'talk.mic_denied' }));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <button
        onClick={(e) => {
          e.stopPropagation();
          active ? stop() : void start();
        }}
        disabled={busy}
        aria-label="talk"
        title={intl.formatMessage({ id: active ? 'talk.stop' : 'talk.start' })}
        className={`rounded p-1.5 backdrop-blur transition-colors ${
          active ? 'bg-red-500/80 text-white' : 'bg-black/55 text-white/80 hover:text-white'
        }`}
      >
        {active ? <Mic className="h-4 w-4" /> : <MicOff className="h-4 w-4" />}
      </button>
      <audio ref={audioRef} autoPlay className="hidden" />
    </>
  );
}
