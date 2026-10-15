// Adapted from Get It. (github.com/beltromatti/get-it, Apache-2.0); see NOTICE.
import { useEffect, useMemo, useRef, useState } from "react";
import type { GraphSpec } from "../../types";
import { COLORS, parseGraphData } from "./graphData";

interface Props {
  spec: GraphSpec;
  onRuntimeError?: (message: string) => void;
}

export default function GraphView({ spec, onRuntimeError }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const boxRef = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ w: 0, h: 0 });
  const onErrorRef = useRef(onRuntimeError);
  useEffect(() => { onErrorRef.current = onRuntimeError; });
  const parsed = useMemo(() => {
    try {
      return { data: parseGraphData(spec), error: null };
    } catch (e) {
      return { data: null, error: (e as Error).message };
    }
  }, [spec]);
  const error = parsed.error;

  useEffect(() => {
    if (parsed.error) onErrorRef.current?.(parsed.error);
  }, [parsed]);

  useEffect(() => {
    const box = boxRef.current;
    if (!box) return;
    const ro = new ResizeObserver(() => setSize({ w: box.clientWidth, h: box.clientHeight }));
    ro.observe(box);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    const data = parsed.data;
    if (!data) return;
    const c = canvasRef.current;
    const ctx = c?.getContext("2d");
    const { w: W, h: H } = size;
    if (!c || !ctx || !W || !H) return;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    c.width = W * dpr;
    c.height = H * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, W, H);

    const pad = { l: 48, r: 12, t: 14, b: 36 };
    const pw = W - pad.l - pad.r;
    const ph = H - pad.t - pad.b;
    const ink = "#1a1a1d";
    const muted = "#6b6e78";
    ctx.font = "11px ui-sans-serif, system-ui";

    const axisLabels = () => {
      ctx.fillStyle = muted;
      ctx.textAlign = "center";
      ctx.textBaseline = "alphabetic";
      ctx.fillText(spec.x_label || "", pad.l + pw / 2, H - 6);
      ctx.save();
      ctx.translate(12, pad.t + ph / 2);
      ctx.rotate(-Math.PI / 2);
      ctx.fillText(spec.y_label || "", 0, 0);
      ctx.restore();
    };

    if (data.kind === "bars") {
      const maxV = Math.max(...data.bars.map((b) => b.value), 0) || 1;
      const slot = pw / data.bars.length;
      ctx.textAlign = "center";
      data.bars.forEach((b, i) => {
        const bh = (Math.max(b.value, 0) / maxV) * ph;
        const x = pad.l + i * slot + slot * 0.15;
        ctx.fillStyle = COLORS[i % COLORS.length];
        ctx.fillRect(x, pad.t + ph - bh, slot * 0.7, bh);
        ctx.fillStyle = ink;
        ctx.fillText(b.label, x + slot * 0.35, pad.t + ph + 14, slot);
        ctx.fillStyle = muted;
        ctx.fillText(String(b.value), x + slot * 0.35, pad.t + ph - bh - 4);
      });
      axisLabels();
      return;
    }

    const all = data.series.flatMap((s) => s.points);
    let [x0, x1] = [Math.min(...all.map((p) => p[0])), Math.max(...all.map((p) => p[0]))];
    let [y0, y1] = [Math.min(...all.map((p) => p[1])), Math.max(...all.map((p) => p[1]))];
    if (x0 === x1) { x0 -= 1; x1 += 1; }
    if (y0 === y1) { y0 -= 1; y1 += 1; }
    const py = (y1 - y0) * 0.06;
    y0 -= py; y1 += py;
    const sx = (x: number) => pad.l + ((x - x0) / (x1 - x0)) * pw;
    const sy = (y: number) => pad.t + ph - ((y - y0) / (y1 - y0)) * ph;
    const fmt = (v: number) => (Math.abs(v) >= 1000 || (Math.abs(v) < 0.01 && v !== 0) ? v.toExponential(1) : +v.toFixed(2) + "");

    ctx.strokeStyle = "rgba(20,22,26,0.08)";
    ctx.lineWidth = 1;
    ctx.fillStyle = muted;
    for (let i = 0; i <= 4; i++) {
      const y = y0 + ((y1 - y0) * i) / 4;
      ctx.beginPath(); ctx.moveTo(pad.l, sy(y)); ctx.lineTo(pad.l + pw, sy(y)); ctx.stroke();
      ctx.textAlign = "right"; ctx.textBaseline = "middle";
      ctx.fillText(fmt(y), pad.l - 5, sy(y));
    }
    for (let i = 0; i <= 5; i++) {
      const x = x0 + ((x1 - x0) * i) / 5;
      ctx.beginPath(); ctx.moveTo(sx(x), pad.t); ctx.lineTo(sx(x), pad.t + ph); ctx.stroke();
      ctx.textAlign = "center"; ctx.textBaseline = "top";
      ctx.fillText(fmt(x), sx(x), pad.t + ph + 3);
    }

    for (const s of data.series) {
      ctx.strokeStyle = s.color;
      ctx.fillStyle = s.color;
      ctx.lineWidth = 2;
      if (spec.chart_type === "points") {
        for (const [x, y] of s.points) { ctx.beginPath(); ctx.arc(sx(x), sy(y), 3, 0, Math.PI * 2); ctx.fill(); }
      } else {
        ctx.beginPath();
        s.points.forEach(([x, y], i) => (i ? ctx.lineTo(sx(x), sy(y)) : ctx.moveTo(sx(x), sy(y))));
        ctx.stroke();
      }
    }

    if (data.series.length > 1) {
      let lx = pad.l + 8;
      ctx.textAlign = "left"; ctx.textBaseline = "middle";
      for (const s of data.series) {
        ctx.fillStyle = s.color;
        ctx.fillRect(lx, pad.t + 6, 14, 3);
        ctx.fillStyle = ink;
        ctx.fillText(s.name, lx + 18, pad.t + 8);
        lx += 28 + ctx.measureText(s.name).width;
      }
    }
    axisLabels();
  }, [spec, parsed, size]);

  return (
    <div ref={boxRef} className="relative w-full h-full">
      <canvas ref={canvasRef} className="w-full h-full" />
      {error && (
        <p className="absolute inset-x-2 bottom-2 rounded border border-rose-200 bg-rose-50 px-2 py-1 text-[11px] text-rose-700">
          {error}
        </p>
      )}
    </div>
  );
}
