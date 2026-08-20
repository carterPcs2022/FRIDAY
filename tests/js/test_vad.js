// Node harness for static/js/hud.js's VAD logic, run via tests/test_vad_js.py
// as part of the regular pytest suite. Runs the real
// file (not a copy) inside a minimal DOM/browser-API stub so the whole
// script loads without errors, then drives watchVoiceActivity() with a
// fake AnalyserNode + a controllable clock/rAF to verify the actual state
// machine: speech-start debouncing, trailing-silence stop, no-speech
// give-up, and the hard max-duration cap. This is the one piece of the
// voice work that's genuinely testable outside a browser -- mic/speaker
// behavior itself is not, and needs the user's own hands-on testing.
const fs = require('fs');
const path = require('path');
const vm = require('vm');

let now = 0;
let rafQueue = [];

function fakeRAF(cb) {
  const id = rafQueue.length + 1;
  rafQueue.push({ id, cb });
  return id;
}
function fakeCancelRAF(id) {
  rafQueue = rafQueue.filter(x => x.id !== id);
}
function tick(ms) {
  now += ms;
  const due = rafQueue;
  rafQueue = [];
  for (const { cb } of due) cb();
}

class FakeAnalyser {
  constructor() { this.fftSize = 512; this._vol = 0; }
  // Fills a Uint8Array around 128 (silence) or with a swing proportional
  // to this._vol to approximate a given RMS after the file's own
  // rmsVolume() normalizes it back down.
  getByteTimeDomainData(arr) {
    const amplitude = Math.round(this._vol * 128 * Math.SQRT2);
    for (let i = 0; i < arr.length; i++) {
      arr[i] = 128 + (i % 2 === 0 ? amplitude : -amplitude);
    }
  }
}

class FakeAudioContext {
  constructor() { this.closed = false; }
  createMediaStreamSource() { return { connect() {}, disconnect() {} }; }
  createAnalyser() { return new FakeAnalyser(); }
  close() { this.closed = true; }
}

// Any DOM element access the file makes (style, classList, .value, event
// listeners, .focus(), etc.) -- this is only loaded to let the whole
// script evaluate without throwing so the VAD functions inside it become
// callable; the stub doesn't need to behave like a real element, just not
// crash when touched.
function fakeElement() {
  const el = {
    style: {},
    classList: { toggle() {}, add() {}, remove() {}, contains: () => false },
    value: '',
    textContent: '',
    innerHTML: '',
    appendChild() {},
    addEventListener() {},
    removeEventListener() {},
    focus() {},
    remove() {},
  };
  return new Proxy(el, {
    get(target, prop) {
      if (prop in target) return target[prop];
      return () => fakeElement();
    },
  });
}

const documentStub = {
  getElementById: () => fakeElement(),
  createElement: () => fakeElement(),
  body: fakeElement(),
};
const document = new Proxy(documentStub, {
  get(target, prop) {
    if (prop in target) return target[prop];
    return () => fakeElement();
  },
});

const sandbox = {
  window: {},
  document,
  navigator: { mediaDevices: { getUserMedia: async () => ({ getTracks: () => [] }) } },
  console,
  Math,
  Date: class {
    static now() { return now; }
    toLocaleTimeString() { return ''; }
  },
  requestAnimationFrame: fakeRAF,
  cancelAnimationFrame: fakeCancelRAF,
  setInterval: () => 0,
  setTimeout: (fn, ms) => { return { fn, ms }; }, // not driven in this harness; VAD path doesn't need it
  clearTimeout: () => {},
  Uint8Array,
  Audio: function () { return { addEventListener() {}, play: async () => {} }; },
  SpeechSynthesisUtterance: function () {},
};
sandbox.window.AudioContext = FakeAudioContext;
sandbox.window.speechSynthesis = { cancel() {} };
sandbox.window.SpeechRecognition = function () {};
sandbox.self = sandbox.window;
vm.createContext(sandbox);

const HUD_JS = path.join(__dirname, '..', '..', 'static', 'js', 'hud.js');
const src = fs.readFileSync(HUD_JS, 'utf8');
vm.runInContext(src, sandbox, { filename: 'hud.js' });

function assert(cond, msg) {
  if (!cond) { console.error('FAIL:', msg); process.exitCode = 1; }
  else console.log('ok  :', msg);
}

// ── Test 1: speech-start fires after sustainMs of above-threshold volume,
// and trailing silence after silenceMs stops it. ─────────────────────────
(function testSpeechStartAndTrailingSilence() {
  now = 0;
  const analyser = new FakeAnalyser();
  const fakeSource = { _analyser: analyser };
  const fakeStream = {};
  // Monkeypatch createMediaStreamSource/createAnalyser to hand back the
  // same analyser instance we can drive volume on directly.
  sandbox.window.AudioContext = function () {
    return {
      createMediaStreamSource: () => ({ connect() {}, disconnect() {} }),
      createAnalyser: () => analyser,
      close() {},
    };
  };

  let speechStarted = false;
  let silenceFired = false;
  const stop = sandbox.watchVoiceActivity(fakeStream, {
    threshold: 0.045, sustainMs: 150, silenceMs: 900, noSpeechTimeoutMs: 2500, maxMs: 20000,
    onSpeechStart: () => { speechStarted = true; },
    onSilence: () => { silenceFired = true; },
  });
  assert(typeof stop === 'function', 'watchVoiceActivity returns a stop() handle');

  // Loud for 200ms (> sustainMs=150) -- should trigger onSpeechStart.
  analyser._vol = 0.3;
  for (let i = 0; i < 4; i++) tick(50); // 4 * 50ms = 200ms
  assert(speechStarted === true, 'onSpeechStart fires after sustained volume above threshold');
  assert(silenceFired === false, 'onSilence has not fired yet while still speaking');

  // Now quiet for 950ms (> silenceMs=900) -- should trigger onSilence.
  analyser._vol = 0.0;
  for (let i = 0; i < 19; i++) tick(50); // 19 * 50ms = 950ms
  assert(silenceFired === true, 'onSilence fires after real trailing silence following speech');
})();

// ── Test 2: never speaking at all gives up after noSpeechTimeoutMs. ──────
(function testNoSpeechTimeout() {
  now = 0;
  const analyser = new FakeAnalyser();
  sandbox.window.AudioContext = function () {
    return {
      createMediaStreamSource: () => ({ connect() {}, disconnect() {} }),
      createAnalyser: () => analyser,
      close() {},
    };
  };
  let silenceFired = false;
  sandbox.watchVoiceActivity({}, {
    threshold: 0.045, sustainMs: 150, silenceMs: 900, noSpeechTimeoutMs: 2500, maxMs: 20000,
    onSpeechStart: () => {},
    onSilence: () => { silenceFired = true; },
  });
  analyser._vol = 0.0;
  for (let i = 0; i < 51; i++) tick(50); // 2550ms of silence, past the 2500ms give-up
  assert(silenceFired === true, 'onSilence fires via noSpeechTimeoutMs when speech never starts (the follow-up-window case)');
})();

// ── Test 3: continuous speech past the old fixed 2.5s cutoff keeps going
// (this is the actual bug VAD replaces -- a real command that takes longer
// than 2.5s to say must not get cut off mid-sentence anymore). ───────────
(function testLongSpeechIsNotCutOff() {
  now = 0;
  const analyser = new FakeAnalyser();
  sandbox.window.AudioContext = function () {
    return {
      createMediaStreamSource: () => ({ connect() {}, disconnect() {} }),
      createAnalyser: () => analyser,
      close() {},
    };
  };
  let silenceFired = false;
  sandbox.watchVoiceActivity({}, {
    threshold: 0.045, sustainMs: 150, silenceMs: 900, noSpeechTimeoutMs: 2500, maxMs: 20000,
    onSpeechStart: () => {},
    onSilence: () => { silenceFired = true; },
  });
  analyser._vol = 0.3;
  // Talk continuously for 5 full seconds -- well past the old fixed 2.5s
  // timer that used to cut every long command off.
  for (let i = 0; i < 100; i++) tick(50); // 5000ms
  assert(silenceFired === false, 'onSilence has NOT fired after 5s of continuous speech (old fixed timer would have cut this off at 2.5s)');
})();

// ── Test 4: the hard max-duration cap still fires even if speech never
// stops (safety net against a stuck-open/very loud mic). ─────────────────
(function testMaxCap() {
  now = 0;
  const analyser = new FakeAnalyser();
  sandbox.window.AudioContext = function () {
    return {
      createMediaStreamSource: () => ({ connect() {}, disconnect() {} }),
      createAnalyser: () => analyser,
      close() {},
    };
  };
  let silenceFired = false;
  sandbox.watchVoiceActivity({}, {
    threshold: 0.045, sustainMs: 150, silenceMs: 900, noSpeechTimeoutMs: 2500, maxMs: 3000,
    onSpeechStart: () => {},
    onSilence: () => { silenceFired = true; },
  });
  analyser._vol = 0.3;
  for (let i = 0; i < 62; i++) tick(50); // 3100ms of continuous speech, past maxMs=3000
  assert(silenceFired === true, 'onSilence fires via maxMs cap even with continuous uninterrupted speech');
})();

// ── Test 5: no Web Audio support -> returns null, caller falls back. ─────
(function testNoWebAudioFallback() {
  const savedAC = sandbox.window.AudioContext;
  sandbox.window.AudioContext = undefined;
  sandbox.window.webkitAudioContext = undefined;
  const result = sandbox.watchVoiceActivity({}, { threshold: 0.045, sustainMs: 150, onSpeechStart: () => {} });
  assert(result === null, 'watchVoiceActivity returns null when Web Audio is unavailable, so callers know to fall back');
  sandbox.window.AudioContext = savedAC;
})();

console.log(process.exitCode ? '\nSOME TESTS FAILED' : '\nALL VAD TESTS PASSED');
