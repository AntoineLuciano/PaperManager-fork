// Ported from the thesis desk's structure card; coordinates come from the backend's
// cached RCSB / AlphaFold DB proxy (GET /knowledge-chat/structures).
/**
 * The spec of a ```structure block. JSON, or shorthand: a bare PDB id (`6SC6`) or an
 * AlphaFold DB model (`AF-P69905`).
 *
 * {
 *   "title": "HOIP RBR held by two dAb3 copies",
 *   "models": [
 *     { "pdb": "6SC6", "label": "dAb3-bound", "chainColors": { "A": "antigen", "B": "heavy", "C": "light" } },
 *     { "pdb": "5EDV", "chains": ["A"], "color": "grey", "opacity": 0.6,
 *       "align": { "to": 0, "chain": "A", "resi": "795-845" } }
 *   ],
 *   "highlights": [
 *     { "label": "IBR", "model": 0, "chain": "A", "resi": "795-845", "color": "#0B4FC0" },
 *     { "label": "C885", "chain": "A", "resi": 885, "style": "sticks", "color": "warm" }
 *   ],
 *   "focus": "IBR",
 *   "caption": "…"
 * }
 *
 * A multi-model entry (e.g. an NMR ensemble) can play its models as frames (`frames`).
 */

/** Residue numbers: 885, "795-845", "770,775,798-855", or a list of those. Author numbering. */
export type Resi = number | string | (number | string)[];

export type Selection = {
  /** Index into `models`; every model when omitted. */
  model?: number;
  chain?: string | string[];
  resi?: Resi;
  resn?: string | string[];
  /** Atom names, e.g. "CA" or ["N", "CA", "C", "O"]. */
  atom?: string | string[];
  /** Only het groups (ligands, ions); waters are never shown. */
  hetero?: boolean;
};

export type ModelSpec = {
  /** An RCSB entry, fetched once and cached by the backend. */
  pdb?: string;
  /** An AlphaFold DB prediction by UniProt accession; its B-factors hold pLDDT. */
  afdb?: string;
  label?: string;
  /** Chains to show; all when omitted. */
  chains?: string[];
  /** The whole model in one colour (hex or palette role), "chain" (default), "plddt" (from B-factors) or "spectrum". */
  color?: string;
  /** Colour per chain, overriding `color`. */
  chainColors?: Record<string, string>;
  opacity?: number;
  /**
   * Play a multi-model PDB (a trajectory) frame by frame. On by default for a
   * PDB with two or more MODEL records; false shows the first model only. Each frame is fitted on frame 0
   * by its Cα (or on the `align` target, when given); `dt` and `unit` label the frames with time.
   */
  frames?: boolean | { dt?: number; unit?: string; fps?: number; fit?: boolean };
  /** Superpose this model on another by Cα pairs with equal residue numbers. */
  align?: {
    to?: number;           // target model index, default 0
    chain?: string;        // chain in this model
    toChain?: string;      // chain in the target, default `chain`
    resi?: Resi;           // residues used for the fit, default all paired
    offset?: number;       // added to this model's numbering before pairing (renumbered predictions)
  };
};

export type Highlight = Selection & {
  label: string;
  color?: string;
  /** "cartoon" recolours the backbone (default), "sticks" / "spheres" add atoms, "surface" a patch. */
  style?: 'cartoon' | 'sticks' | 'spheres' | 'surface';
  hidden?: boolean;
};

/**
 * A distance followed through a trajectory, drawn as a strip chart under the player: between the atoms
 * of selection `a` and those of `b` (the centroid when a selection matches several atoms). Both must lie
 * in the same model, so the frame fit cannot change it. `threshold` draws a dashed line (an H-bond cut).
 *   { "label": "3-OH – His40 NE2", "a": { "model": 1, "resn": "KMP", "atom": "O1" },
 *     "b": { "model": 1, "chain": "A", "resi": 40, "atom": "NE2" }, "threshold": 3.5 }
 */
export type Distance = { label: string; a: Selection; b: Selection; color?: string; threshold?: number };

export type StructureSpec = {
  title?: string;
  caption?: string;
  models: ModelSpec[];
  highlights?: Highlight[];
  /** Highlight label or index to zoom to at the start. */
  focus?: string | number;
  /** Show het groups (ligands, ions) as ball and stick; default true. */
  ligands?: boolean;
  /** Grey the parts no highlight covers. */
  dim?: boolean;
  /** "cartoon" (default) or "surface". */
  representation?: 'cartoon' | 'surface';
  /** Distances per frame, shown under the trajectory player (needs a multi-model model). */
  distances?: Distance[];
  /** Stage height in pixels; default 380. */
  height?: number;
};
