// Stands in for src/components/kchat/ConceptBlock.tsx in the prerender: a ```concept block the
// model wrote becomes an island (a still of the card, made live in the browser).
import { useMemo } from 'react';
import { parseConcept } from '../../src/components/kchat/ConceptBlock';
import { Island } from './Island';

export default function ConceptBlock({ source }: { source: string }) {
  const parsed = useMemo(() => parseConcept(source), [source]);
  if (!parsed) return null;
  const label = parsed.spec.title || parsed.label || 'concept';
  return <Island kind="concept" type={parsed.spec.type} payload={JSON.stringify({ spec: parsed.spec, label: parsed.label })} label={`Concept card: ${label}`} />;
}
