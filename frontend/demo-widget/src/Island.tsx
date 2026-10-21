// A card in the prerendered page: a still image of it, and what the browser needs to make it live.
import { where } from './config';
import { keyOf, stillUrl } from './keys';

export function Island({ kind, type, payload, label }: { kind: 'concept' | 'structure'; type?: string; payload: string; label: string }) {
  const key = keyOf(payload);
  const size = where.sizes[key];
  return (
    <div className={`pmd-island pmd-island-${kind}`} data-kind={kind} data-type={type ?? kind} data-key={key} data-payload={payload}>
      <img className="pmd-still" src={stillUrl(key)} width={size?.w} height={size?.h} alt={label} loading="lazy" decoding="async" />
    </div>
  );
}
