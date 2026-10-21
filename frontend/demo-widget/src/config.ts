/**
 * Where the bundle and the demo's data live, and whether this render is the static one
 * (prerendered into the page) or the live one (cards mounted in the browser).
 */
export const where = {
  base: '',
  /** The data directory: cards/ (stills) and structures/ (coordinates). */
  data: '',
  static: false,
  sizes: {} as Record<string, { w: number; h: number }>,
};
