// Stands in for src/components/kchat/structure/StructureBlock.tsx in the prerender: a ```structure
// block becomes an island (a still of the card; the 3D viewer loads when its tab is opened).
import { useMemo } from 'react';
import { parseSource } from '../../src/components/kchat/structure/viewer';
import { Island } from './Island';

export default function StructureBlock({ source }: { source: string }) {
  const parsed = useMemo(() => parseSource(source), [source]);
  if (!parsed) return null;
  return <Island kind="structure" payload={source} label={`3D structure: ${parsed.spec.title ?? 'structure'}`} />;
}
