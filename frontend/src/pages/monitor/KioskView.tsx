import { useEffect, useState } from 'react';

import { env } from '@/config/env';

const KIOSK_KEY = 'axp-monitor-token';

interface MonitorMe {
  monitor: { uuid: string; name: string; settings: Record<string, unknown> | null };
  dashboard: { uuid: string; layout: { tiles?: { camera_uuid?: string }[] } } | null;
  cameras: { uuid: string; name: string; streams: { role: string; go2rtc_name: string }[] }[];
}

/** Kiosk display (PLAN P5 §8.5). Standalone route /monitor — its own monitor token, no app
 * shell. Pairing screen until paired, then a full-screen dashboard camera grid. Live WebRTC
 * reuse under monitor scope is a follow-up (§14 Q7); MVP renders the bound camera grid. */
export function KioskView() {
  const [token, setToken] = useState<string | null>(() => localStorage.getItem(KIOSK_KEY));
  const [me, setMe] = useState<MonitorMe | null>(null);

  useEffect(() => {
    if (!token) {
      setMe(null);
      return;
    }
    let alive = true;
    const load = async () => {
      try {
        const res = await fetch(`${env.apiUrl}/monitor/me`, { headers: { Authorization: `Bearer ${token}` } });
        if (res.status === 401) {
          localStorage.removeItem(KIOSK_KEY);
          if (alive) setToken(null);
          return;
        }
        const json = await res.json();
        if (alive) setMe(json.data);
      } catch {
        /* retry on next heartbeat */
      }
    };
    void load();
    const hb = setInterval(() => {
      fetch(`${env.apiUrl}/monitor/heartbeat`, { method: 'POST', headers: { Authorization: `Bearer ${token}` } })
        .then((r) => { if (r.status === 401) { localStorage.removeItem(KIOSK_KEY); setToken(null); } })
        .catch(() => {});
      void load();
    }, 30000);
    return () => { alive = false; clearInterval(hb); };
  }, [token]);

  if (!token || !me) {
    return <PairingScreen onPaired={(t) => { localStorage.setItem(KIOSK_KEY, t); setToken(t); }} />;
  }
  return <KioskGrid me={me} />;
}

function PairingScreen({ onPaired }: { onPaired: (token: string) => void }) {
  const [code, setCode] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (code.length !== 6) return;
    setBusy(true);
    setError('');
    try {
      const res = await fetch(`${env.apiUrl}/pairing/claim`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ code }),
      });
      const json = await res.json();
      if (res.ok && json.data?.access_token) onPaired(json.data.access_token);
      else setError('코드가 올바르지 않거나 만료되었습니다.');
    } catch {
      setError('연결에 실패했습니다.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex h-screen w-screen flex-col items-center justify-center bg-[#171A20] text-white">
      <div className="mb-8 text-lg tracking-wide text-white/70">AeroX Protect 모니터</div>
      <input
        value={code}
        onChange={(e) => setCode(e.target.value.replace(/[^0-9]/g, '').slice(0, 6))}
        onKeyDown={(e) => e.key === 'Enter' && submit()}
        inputMode="numeric"
        autoFocus
        placeholder="------"
        className="w-72 rounded-lg border border-white/15 bg-transparent text-center font-mono text-5xl tracking-[0.4em] text-white outline-none focus:border-[#3E6AE1]"
      />
      <p className="mt-6 text-sm text-white/40">관리자 화면의 6자리 코드를 입력하세요</p>
      {error && <p className="mt-3 text-sm text-red-400">{error}</p>}
      <button onClick={submit} disabled={busy || code.length !== 6}
        className="mt-8 rounded bg-[#3E6AE1] px-8 py-2.5 text-sm font-medium text-white disabled:opacity-40">
        연결
      </button>
    </div>
  );
}

function KioskGrid({ me }: { me: MonitorMe }) {
  const cams = me.cameras;
  const cols = cams.length <= 1 ? 1 : cams.length <= 4 ? 2 : 3;
  return (
    <div className="h-screen w-screen bg-black p-1">
      <div className="grid h-full w-full gap-1" style={{ gridTemplateColumns: `repeat(${cols}, 1fr)` }}>
        {cams.map((c) => (
          <div key={c.uuid} className="relative flex items-center justify-center overflow-hidden rounded bg-[#0c0d10]">
            <span className="text-sm text-white/30">{c.name}</span>
            <span className="absolute left-2 top-2 rounded bg-black/50 px-2 py-0.5 text-xs text-white/70">{c.name}</span>
          </div>
        ))}
        {cams.length === 0 && (
          <div className="flex items-center justify-center text-white/40">{me.dashboard ? '카메라가 없습니다' : '대시보드 없음'}</div>
        )}
      </div>
    </div>
  );
}
