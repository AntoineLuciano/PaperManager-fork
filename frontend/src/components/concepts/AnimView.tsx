// Adapted from Get It. (github.com/beltromatti/get-it, Apache-2.0); see NOTICE.
import { useEffect, useMemo, useRef } from "react";
import type { AnimSpec } from "../../types";
import { buildSandboxDoc, SANDBOX_ATTR } from "./sandbox";

interface Props {
  spec: AnimSpec;
  /** Called once per spec if setup or a frame throws. */
  onRuntimeError?: (message: string) => void;
}

/** Runs the spec's setup_code in a sandboxed iframe (see sandbox.ts). */
export default function AnimView({ spec, onRuntimeError }: Props) {
  const frameRef = useRef<HTMLIFrameElement>(null);
  const doc = useMemo(() => buildSandboxDoc(), []);
  const onErrorRef = useRef(onRuntimeError);
  useEffect(() => { onErrorRef.current = onRuntimeError; });

  useEffect(() => {
    let reported = false;
    const send = () =>
      frameRef.current?.contentWindow?.postMessage({ type: "concept-anim-run", code: spec.setup_code }, "*");
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
