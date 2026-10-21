// A structure island made live: 3Dmol.js and the coordinates load from the widget's own files
// when the card's tab is opened; until then, and if anything fails, the still stays.
import { useEffect, useMemo, useState } from 'react';
import { StructureView } from '../../src/components/kchat/structure/StructureView';
import { parseSource } from '../../src/components/kchat/structure/viewer';
import type { ModelSpec } from '../../src/components/kchat/structure/types';
import { accentize, useSettledAccent } from './accent';
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

async function gunzip(raw: Uint8Array): Promise<string> {
  if (raw[0] !== 0x1f || raw[1] !== 0x8b) return new TextDecoder().decode(raw);   // already undone by the server
  if (typeof DecompressionStream === 'undefined') throw new Error('this browser cannot unzip the coordinates');
  return new Response(new Blob([raw as BlobPart]).stream().pipeThrough(new DecompressionStream('gzip'))).text();
}

const prepared = new Map<string, Promise<void>>();
/** structures/<key>.json.gz, unzipped and registered as a blob: URL for the viewer to fetch. */
function prepare(m: ModelSpec): Promise<void> {
  const query = m.pdb ? `pdb=${m.pdb}` : `afdb=${m.afdb ?? ''}`;
  const key = m.pdb ? `pdb-${m.pdb.toUpperCase()}` : `afdb-${(m.afdb ?? '').toUpperCase()}`;
  let p = prepared.get(key);
  if (!p) {
    p = (async () => {
      const r = await fetch(`${where.data}structures/${key}.json.gz`);
      if (!r.ok) throw new Error(`no coordinates for ${key}`);
      const text = await gunzip(new Uint8Array(await r.arrayBuffer()));
      registerStructure(query, URL.createObjectURL(new Blob([text], { type: 'application/json' })));
    })();
    p.catch(() => prepared.delete(key));
    prepared.set(key, p);
  }
  return p;
}

export default function LiveStructure({ source, still }: { source: string; still: string }) {
  const parsed = useMemo(() => parseSource(source), [source]);
  const [acc, accKey] = useSettledAccent();
  const spec = useMemo(() => (parsed ? JSON.parse(accentize(JSON.stringify(parsed.spec), acc)) : null), [parsed, acc]);
  const [state, setState] = useState<'wait' | 'ready' | 'failed'>(() => {
    const probe = document.createElement('canvas');
    return probe.getContext('webgl2') || probe.getContext('webgl') ? 'wait' : 'failed';
  });
  useEffect(() => {
    if (!parsed || state === 'failed') return;
    let live = true;
    const timeout = new Promise<never>((_r, reject) => setTimeout(() => reject(new Error('timed out')), 25000));
    Promise.race([Promise.all([load3Dmol(), ...parsed.spec.models.map(prepare)]), timeout])
      .then(() => live && setState('ready'))
      .catch(() => live && setState('failed'));
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [parsed]);
  if (!spec || state !== 'ready') {
    return (
      <div className="pmd-still-box">
        <img className="pmd-still" src={still} alt="3D structure" />
        <span className="pmd-badge">{state === 'failed' ? 'still image: the 3D view could not load' : 'loading the 3D view …'}</span>
      </div>
    );
  }
  return <StructureView key={accKey} spec={spec} />;
}
