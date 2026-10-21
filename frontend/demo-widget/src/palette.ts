/**
 * The app's colour tables that are not CSS (concept graph series, structure roles and chain
 * colours) follow the settled accent. Registered before any component subscribes, so the
 * tables are updated before cards redraw.
 */
import { COLORS } from '../../src/components/concepts/graphData';
import { CHAIN_CYCLE, ROLE } from '../../src/components/kchat/structure/viewer';
import { accentize, getSettledAccent, subscribeAccent, type HSL } from './accent';

const colors0 = [...COLORS], chains0 = [...CHAIN_CYCLE], roles0 = { ...ROLE };
let last: HSL | null = null;

function apply() {
  const acc = getSettledAccent();
  if (acc === last) return;
  last = acc;
  colors0.forEach((c, i) => { COLORS[i] = accentize(c, acc); });
  chains0.forEach((c, i) => { CHAIN_CYCLE[i] = accentize(c, acc); });
  for (const k of Object.keys(roles0)) ROLE[k] = accentize(roles0[k], acc);
}

apply();
subscribeAccent(apply);
