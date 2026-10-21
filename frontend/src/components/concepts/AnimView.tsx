// Adapted from Get It. (github.com/beltromatti/get-it, Apache-2.0); see NOTICE.
import { useEffect, useMemo, useRef } from "react";
import type { AnimSpec } from "../../types";
import { buildSandboxDoc, SANDBOX_ATTR } from "./sandbox";

interface Props {
  spec: AnimSpec;
  /** Called once per spec if setup or a frame throws. */
  onRuntimeError?: (message: string) => void;
  /** Playback speed: 0 pauses (the last frame stays), 0.5, 1, 2. */
  speed?: number;
}

/** Runs the spec's setup_code in a sandboxed iframe (see sandbox.ts). */
export default function AnimView({ spec, onRuntimeError, speed = 1 }: Props) {
  const frameRef = useRef<HTMLIFrameElement>(null);
  const doc = useMemo(() => buildSandboxDoc(), []);
  const onErrorRef = useRef(onRuntimeError);
  useEffect(() => { onErrorRef.current = onRuntimeError; });
  const speedRef = useRef(speed);
  useEffect(() => { speedRef.current = speed; });
  const postSpeed = () =>
    frameRef.current?.contentWindow?.postMessage({ type: "concept-anim-speed", speed: speedRef.current }, "*");

  useEffect(() => {
    let reported = false;
    const send = () => {
      postSpeed();
      frameRef.current?.contentWindow?.postMessage({ type: "concept-anim-run", code: spec.setup_code }, "*");
    };
    function onMessage(ev: MessageEvent) {
      if (ev.source !== frameRef.current?.contentWindow) return;
      if (ev.data?.type === "concept-anim-ready") send();
      if (ev.data?.type === "concept-anim-error" && !reported) {
        reported = true;
        onErrorRef.current?.(String(ev.data.message));
      }
    }
    window.addEventListener("message", onMessage);
    send(); // iframe may already be loaded when only the spec changed
    return () => window.removeEventListener("message", onMessage);
  }, [spec]);

  useEffect(() => { speedRef.current = speed; postSpeed(); }, [speed]);

  return (
    <iframe
      ref={frameRef}
      title={spec.title}
      sandbox={SANDBOX_ATTR}
      srcDoc={doc}
      className="w-full h-full border-0 rounded-lg bg-white"
    />
  );
}
