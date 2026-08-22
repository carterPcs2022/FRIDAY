Vendored from `@wllama/wllama` v3.6.0 (npm), ESM build.

- `wllama.min.js` <- `esm/index.min.js`
- `wllama.wasm` <- `esm/wasm/wllama.wasm`

Vendored (not loaded from a CDN) so offline mode stays genuinely
self-contained -- the whole point is these files work with zero network
once the service worker has cached them once.

To update: `npm install @wllama/wllama` somewhere scratch, then copy
those two files here and bump the version above. Check `esm/wllama.d.ts`
in the new version for any API changes before touching
`static/js/offline_model.js`.
