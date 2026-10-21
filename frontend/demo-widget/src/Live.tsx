// The live cards that replace the prerendered stills, and the still shown when one cannot run.
import { lazy, useState } from 'react';
import ConceptCard from '../../src/components/kchat/ConceptCard';
import type { ConceptSpec } from '../../src/types';
import { accentSpec, useSettledAccent } from './accent';

/** The 3D card: its own chunk, loaded with the first structure. */
export const LiveStructure = lazy(() => import('./LiveStructure'));

export function Still({ src, note }: { src: string; note?: string }) {
  return (
    <div className="pmd-still-box">
      <img className="pmd-still" src={src} alt="" />
      {note && <span className="pmd-badge">{note}</span>}
    </div>
  );
}

export function LiveConcept({ spec, label, foot, still }: { spec: ConceptSpec; label?: string; foot?: boolean; still: string }) {
  const [acc, accKey] = useSettledAccent();
  const [failed, setFailed] = useState(false);
  if (failed) return <Still src={still} />;
  return (
    <ConceptCard key={accKey} spec={accentSpec(spec, acc)} label={label}
      onRuntimeError={() => setFailed(true)} footnote={foot ? 'made from this answer' : undefined} />
  );
}
