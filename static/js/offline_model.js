// static/js/offline_model.js — runs FRIDAY's fine-tuned persona model
// entirely inside the browser tab via wllama (llama.cpp compiled to
// WebAssembly, vendored at static/vendor/wllama/ -- see that directory's
// origin/version). No server involved once the model is cached: this is
// what actually answers when hud.js's real /command request fails.
//
// The model itself is NOT bundled in this repo (a multi-GB GGUF has no
// business living in git or being served off Render's disk/bandwidth) --
// it's fetched once, on demand, from wherever the boss hosts their
// exported fine-tune (see routes/offline.py's FRIDAY_OFFLINE_MODEL_URL),
// then cached by wllama itself (OPFS-backed) so every load after the
// first works with zero network.

let _wllama = null;
let _loadingPromise = null;
let _configPromise = null;

function getOfflineConfig() {
  if (!_configPromise) {
    _configPromise = fetch('/friday/offline/config')
      .then((r) => r.json())
      .catch(() => ({ enabled: false, model_url: '', system_prompt: '' }));
  }
  return _configPromise;
}

async function ensureOfflineModelLoaded(onProgress) {
  if (_wllama) return _wllama;
  if (_loadingPromise) return _loadingPromise;

  _loadingPromise = (async () => {
    const config = await getOfflineConfig();
    if (!config.enabled || !config.model_url) {
      throw new Error('Offline model not configured (FRIDAY_OFFLINE_MODEL_URL unset).');
    }

    const { Wllama } = await import('/static/vendor/wllama/wllama.min.js');
    const wllama = new Wllama({ default: '/static/vendor/wllama/wllama.wasm' }, {
      allowOffline: true,
    });

    await wllama.loadModelFromUrl(config.model_url, {
      useCache: true,
      allowOffline: true,
      progressCallback: onProgress
        ? ({ loaded, total }) => onProgress(total ? loaded / total : 0)
        : undefined,
    });

    _wllama = wllama;
    return wllama;
  })();

  try {
    return await _loadingPromise;
  } catch (e) {
    _loadingPromise = null; // allow a retry on the next call instead of caching the failure forever
    throw e;
  }
}

// history: array of {role: 'user'|'assistant', content: string}, oldest
// first, NOT including the new prompt -- generateOffline appends it.
async function generateOffline(history, prompt, onProgress) {
  const config = await getOfflineConfig();
  const wllama = await ensureOfflineModelLoaded(onProgress);

  const messages = [
    { role: 'system', content: config.system_prompt },
    ...history.slice(-6), // small model, small context -- keep recent turns only
    { role: 'user', content: prompt },
  ];

  const result = await wllama.createChatCompletion({
    messages,
    max_tokens: 200,
    temperature: 0.7,
    top_k: 40,
    top_p: 0.9,
  });
  return result.choices[0].message.content;
}

window.FridayOffline = { getOfflineConfig, ensureOfflineModelLoaded, generateOffline };
