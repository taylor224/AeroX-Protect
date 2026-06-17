import { useEffect, useRef } from 'react';

import { liveMp4Url } from '@/pages/live/live.api';
import type { Camera } from '@/types/axp';

/** Client-side WebGL fisheye dewarp (PLAN P6 L5). Renders the live fMP4 as a GL texture and
 *  reprojects an equidistant fisheye into a rectilinear virtual-PTZ view. Drag = pan/tilt,
 *  wheel = zoom. Server does zero extra work. */
const VERT = `attribute vec2 p; varying vec2 uv; void main(){ uv=(p+1.0)*0.5; gl_Position=vec4(p,0.0,1.0); }`;
const FRAG = `
precision highp float;
varying vec2 uv;
uniform sampler2D tex;
uniform vec2 center;   // fisheye center (0..1)
uniform float radius;  // fisheye radius (fraction of width)
uniform float pan, tilt, fov, aspect, lensFov;
const float PI = 3.14159265;
void main() {
  vec2 ndc = (uv - 0.5) * 2.0; ndc.x *= aspect;
  float t = tan(fov * 0.5);
  vec3 ray = normalize(vec3(ndc.x * t, ndc.y * t, 1.0));
  float ct = cos(tilt), st = sin(tilt);
  ray = vec3(ray.x, ct*ray.y - st*ray.z, st*ray.y + ct*ray.z);
  float cp = cos(pan), sp = sin(pan);
  ray = vec3(cp*ray.x + sp*ray.z, ray.y, -sp*ray.x + cp*ray.z);
  float theta = acos(clamp(ray.z, -1.0, 1.0));
  float phi = atan(ray.y, ray.x);
  float r = (theta / (lensFov * 0.5)) * radius;
  vec2 src = center + r * vec2(cos(phi), sin(phi));
  if (src.x < 0.0 || src.x > 1.0 || src.y < 0.0 || src.y > 1.0) { gl_FragColor = vec4(0.0,0.0,0.0,1.0); return; }
  gl_FragColor = texture2D(tex, vec2(src.x, 1.0 - src.y));
}`;

function compile(gl: WebGLRenderingContext, type: number, src: string) {
  const s = gl.createShader(type)!;
  gl.shaderSource(s, src);
  gl.compileShader(s);
  return s;
}

export function FisheyeViewer({ camera, active }: { camera: Camera; active: boolean }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const view = useRef({ pan: 0, tilt: 0, fov: 1.4 });
  const drag = useRef<{ x: number; y: number } | null>(null);

  const sub = camera.streams?.find((s) => s.is_default_live) ?? camera.streams?.[0];
  const go2rtcName = sub?.go2rtc_name ?? `cam_${camera.uuid}_sub`;
  const p = (camera.fisheye_params ?? {}) as { cx?: number; cy?: number; radius?: number; lens_fov?: number };

  useEffect(() => {
    const canvas = canvasRef.current;
    const video = videoRef.current;
    if (!canvas || !video) return;
    const gl = canvas.getContext('webgl');
    if (!gl) return;

    const prog = gl.createProgram()!;
    gl.attachShader(prog, compile(gl, gl.VERTEX_SHADER, VERT));
    gl.attachShader(prog, compile(gl, gl.FRAGMENT_SHADER, FRAG));
    gl.linkProgram(prog);
    gl.useProgram(prog);

    const buf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
    const loc = gl.getAttribLocation(prog, 'p');
    gl.enableVertexAttribArray(loc);
    gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);

    const tex = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, tex);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);

    const U = (n: string) => gl.getUniformLocation(prog, n);
    let raf = 0;
    const render = () => {
      raf = requestAnimationFrame(render);
      if (video.readyState < 2) return;
      const w = canvas.clientWidth, h = canvas.clientHeight;
      if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
      gl.viewport(0, 0, canvas.width, canvas.height);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, video);
      gl.uniform2f(U('center'), p.cx ?? 0.5, p.cy ?? 0.5);
      gl.uniform1f(U('radius'), p.radius ?? 0.5);
      gl.uniform1f(U('pan'), view.current.pan);
      gl.uniform1f(U('tilt'), view.current.tilt);
      gl.uniform1f(U('fov'), view.current.fov);
      gl.uniform1f(U('aspect'), canvas.width / Math.max(1, canvas.height));
      gl.uniform1f(U('lensFov'), p.lens_fov ?? Math.PI);
      gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
    };
    render();
    return () => cancelAnimationFrame(raf);
  }, [go2rtcName, p.cx, p.cy, p.radius, p.lens_fov]);

  return (
    <div className="relative h-full w-full overflow-hidden bg-black">
      <video ref={videoRef} src={active ? liveMp4Url(go2rtcName) : undefined} autoPlay muted playsInline className="hidden" />
      <canvas
        ref={canvasRef}
        className="h-full w-full cursor-grab active:cursor-grabbing"
        onPointerDown={(e) => { drag.current = { x: e.clientX, y: e.clientY }; (e.target as Element).setPointerCapture(e.pointerId); }}
        onPointerMove={(e) => {
          if (!drag.current) return;
          const dx = (e.clientX - drag.current.x) / 200, dy = (e.clientY - drag.current.y) / 200;
          view.current.pan -= dx;
          view.current.tilt = Math.max(-1.3, Math.min(1.3, view.current.tilt - dy));
          drag.current = { x: e.clientX, y: e.clientY };
        }}
        onPointerUp={() => (drag.current = null)}
        onWheel={(e) => { view.current.fov = Math.max(0.4, Math.min(2.6, view.current.fov + (e.deltaY > 0 ? 0.1 : -0.1))); }}
      />
    </div>
  );
}
