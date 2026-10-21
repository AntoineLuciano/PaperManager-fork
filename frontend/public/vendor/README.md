# public/vendor

Third-party browser libraries served as static files rather than bundled, loaded on first use.

| Folder | What | Version | Licence | Used by |
|---|---|---|---|---|
| `3dmol/` | 3Dmol.js molecular viewer (`3Dmol-min.js` from the npm package's `build/`) | 2.5.5 | BSD-3-Clause (`3dmol/LICENSE`) | `src/components/kchat/structure/`, the 3D structure cards in Knowledge Chat |

To update: `npm pack 3dmol` in a scratch folder, copy `package/build/3Dmol-min.js` here and bump the version above.
