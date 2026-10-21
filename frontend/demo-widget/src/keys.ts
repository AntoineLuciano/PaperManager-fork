// Keys and URLs of the card stills, shared by the prerender and the browser side.
import { where } from './config';

/** A short stable key for a card's payload (FNV-1a); names its still image. */
export function keyOf(s: string): string {
  let h = 0x811c9dc5;
  for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 0x01000193); }
  return (h >>> 0).toString(36);
}

export const stillUrl = (key: string) => `${where.data}cards/${key}.webp`;
