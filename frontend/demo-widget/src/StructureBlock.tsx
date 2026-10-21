// Stands in for src/components/kchat/structure/StructureBlock.tsx: loads 3Dmol.js and the
// conversation's coordinates from the widget's own files, then renders the app's StructureView.
import { useEffect, useMemo, useState } from 'react';
import { StructureView } from '../../src/components/kchat/structure/StructureView';
import { parseSource } from '../../src/components/kchat/structure/viewer';
import type { ModelSpec } from '../../src/components/kchat/structure/types';
import { registerStructure } from './client';
import { where } from './config';

/* eslint-disable @typescript-eslint/no-explicit-any */
let lib: Promise<void> | null = null;
function load3Dmol(): Promise<void> {
  const w = window as any;
  if (w.$3Dmol) return Promise.resolve();
  lib ??= new Promise<void>((resolve, reject) => {
    const s = document.createElement('script');
    s.src = `${where.base}vendor/3Dmol-min.js`;
    s.onload = () => (w.$3Dmol ? resolve() : reject(new Error('3Dmol did not load')));
    s.onerror = () => { lib = null; reject(new Error('could not load 3Dmol.js')); };
    document.head.appendChild(s);
  });
  return lib;
}

const prepared = new Map<string, Promise<void>>();
/** Fetch structures/<key>.json.gz, unzip it in the browser and register it as a blob: URL. */
function prepare(m: ModelSpec): Promise<void> {
  const query = m.pdb ? `pdb=${m.pdb}` : `afdb=${m.afdb ?? ''}`;
  const key = m.pdb ? `pdb-${m.pdb.toUpperCase()}` : `afdb-${(m.afdb ?? '').toUpperCase()}`;
  let p = prepared.get(key);
  if (!p) {
    p = (async () => {
      const r = await fetch(`${where.data}structures/${key}.json.gz`);
      if (!r.ok) throw new Error(`no coordinates for ${key} in this demo`);
      const raw = new Uint8Array(await r.arrayBuffer());
      // A server may already have undone the gzip (Content-Encoding); then the bytes are JSON.
      const text = raw[0] === 0x1f && raw[1] === 0x8b
        ? await new Response(new Blob([raw]).stream().pipeThrough(new DecompressionStream('gzip'))).text()
        : new TextDecoder().decode(raw);
      registerStructure(query, URL.createObjectURL(new Blob([text], { type: 'application/json' })));
    })();
    p.catch(() => prepared.delete(key));
    prepared.set(key, p);
  }
  return p;
}

export default function StructureBlock({ source }: { source: string }) {
  const parsed = useMemo(() => parseSource(source), [source]);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!parsed) return;
    let live = true;
    Promise.all([load3Dmol(), ...parsed.spec.models.map(prepare)])
      .then(() => live && setReady(true))
      .catch((e: Error) => live && setError(e.message));
    return () => { live = false; };
  }, [parsed]);
  if (!parsed) return <div className="kc-card kc-card-pending">structure …</div>;
  if (error) return <div className="kc-card kc-card-pending">{error}</div>;
  if (!ready) {
    return (
      <div className="kc-card kc-card-pending">
        <span className="kc-spinner" /> loading {parsed.spec.models.map((m) => m.pdb ?? `AF-${m.afdb}`).join(', ')} …
      </div>
    );
  }
  return <StructureView spec={parsed.spec} />;
}
