const BASE = '';
let muted = false, recording = false;
let currentAudio = null;
let leftOpen = false, rightOpen = false;
// Offline mode: set once a real /command request has failed to reach the
// network and the local in-browser model (static/js/offline_model.js) has
// answered instead. While true, pollState() backs off so its 5s poll
// doesn't fight this badge back to "DEGRADED" every cycle -- see send().
let offlineModeActive = false;
let offlineHistory = [];

if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/service-worker.js').catch((e) => {
      console.warn('Service worker registration failed:', e);
    });
  });
}

// .top-bar wraps to however many rows a given phone's width forces (a
// wide phone: one row; a narrow one with VOICE OFF/ENROLL/HELMET VIEW
// all present: three or four) -- no fixed breakpoint value can predict
// that height, which is exactly what caused HELMET VIEW/gear/diamond to
// render on top of the LOCK/PWR readout on a real device instead of
// below it. Measuring the actual rendered box and driving
// --top-bar-clearance (static/css/hud.css) from it replaces guessing
// with fact, and keeps working if the bar's content ever changes again.
function syncTopBarClearance() {
  const bar = document.querySelector('.top-bar');
  if (!bar) return;
  const height = bar.getBoundingClientRect().height;
  if (height > 0) {
    document.documentElement.style.setProperty('--top-bar-clearance', `${Math.ceil(height) + 8}px`);
  }
}
if (typeof window !== 'undefined' && typeof window.addEventListener === 'function') {
  if ('ResizeObserver' in window) {
    window.addEventListener('load', () => {
      const bar = document.querySelector('.top-bar');
      if (bar) new ResizeObserver(syncTopBarClearance).observe(bar);
    });
  } else {
    window.addEventListener('load', syncTopBarClearance);
    window.addEventListener('resize', syncTopBarClearance);
    window.addEventListener('orientationchange', syncTopBarClearance);
  }
}

(function() {
  const container = document.getElementById('particles');
  for (let i = 0; i < 30; i++) {
    const p = document.createElement('div');
    p.className = 'particle';
    p.style.left = Math.random() * 100 + '%';
    p.style.animationDuration = (8 + Math.random() * 12) + 's';
    p.style.animationDelay = (Math.random() * 10) + 's';
    p.style.opacity = Math.random() * 0.5;
    container.appendChild(p);
  }
})();

function tick() {
  document.getElementById('clock').textContent = new Date().toLocaleTimeString('en-US', {hour12: false});
}
setInterval(tick, 1000); tick();

function toggleLeft() {
  leftOpen = !leftOpen;
  document.getElementById('panel-left').classList.toggle('open', leftOpen);
  document.getElementById('backdrop').classList.toggle('on', leftOpen || rightOpen);
  if (leftOpen && rightOpen) toggleRight();
}
function toggleRight() {
  rightOpen = !rightOpen;
  document.getElementById('panel-right').classList.toggle('open', rightOpen);
  document.getElementById('backdrop').classList.toggle('on', leftOpen || rightOpen);
  if (rightOpen && leftOpen) toggleLeft();
}
function closeAll() {
  leftOpen = rightOpen = false;
  document.getElementById('panel-left').classList.remove('open');
  document.getElementById('panel-right').classList.remove('open');
  document.getElementById('backdrop').classList.remove('on');
}

async function send() {
  const inp = document.getElementById('chat-inp');
  const text = inp.value.trim();
  if (!text) return;
  inp.value = '';
  addMsg('user', 'YOU', text);
  showThinking();
  try {
    // A short client-side timeout, not just relying on the fetch ever
    // rejecting -- a request into a dead network (ship wifi, dropped
    // connection) can hang far longer than it's worth waiting before
    // falling back to the local model.
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 8000);
    let r;
    try {
      r = await fetch(`${BASE}/command`, {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({prompt: text}),
        signal: controller.signal,
      });
    } finally {
      clearTimeout(timer);
    }
    const d = await r.json();
    hideThinking();
    setOfflineBadge(false);
    addMsg('fri', 'FRIDAY', d.response || '...', {model: d.model || '', ms: d.ms || 0, emotion: d.emotion, file: d.file, clarify: d.clarify});
    showFace();
    if (!muted && d.has_audio && d.audio_file) playAudio(d.audio_file);
  } catch(e) {
    await sendOffline(text);
  }
}

async function sendOffline(text) {
  if (!window.FridayOffline) {
    hideThinking();
    addMsg('sys', 'SYSTEM', 'Connection issue, boss.');
    return;
  }
  setOfflineBadge(true);
  try {
    const reply = await window.FridayOffline.generateOffline(offlineHistory, text, (frac) => {
      showThinking(`LOADING LOCAL MODEL ${Math.round(frac * 100)}%`);
    });
    hideThinking();
    offlineHistory.push({role: 'user', content: text}, {role: 'assistant', content: reply});
    addMsg('fri', 'FRIDAY', reply, {model: 'local (offline)', ms: 0});
    showFace();
  } catch (e) {
    hideThinking();
    addMsg('sys', 'SYSTEM',
      "Can't reach the server, and the local model isn't set up on this device, boss.");
  }
}

function setOfflineBadge(active) {
  offlineModeActive = active;
  const pill = document.getElementById('status-pill');
  if (!pill) return;
  if (active) {
    pill.textContent = 'OFFLINE · LOCAL';
    pill.className = 'pill warn';
  } else {
    pill.textContent = 'ONLINE';
    pill.className = 'pill online';
  }
}

function quickSend(text) {
  document.getElementById('chat-inp').value = text;
  send();
}

// Forces the local-model path on demand, without waiting for a real
// network failure -- lets the boss verify the whole offline pipeline
// (model download, wllama load, actual inference) while still on wifi,
// instead of finding out it's broken only after losing signal for real.
async function testOfflineMode() {
  const inp = document.getElementById('chat-inp');
  const text = inp.value.trim() || "Status check, boss.";
  inp.value = '';
  addMsg('user', 'YOU (OFFLINE TEST)', text);
  showThinking();
  await sendOffline(text);
}

function escapeHtml(s) {
  const div = document.createElement('div');
  div.textContent = s;
  return div.innerHTML;
}

function addMsg(type, label, text, meta = {}) {
  const area = document.getElementById('messages');
  hideThinking();
  const wrap = document.createElement('div');
  wrap.className = `msg-wrap ${type}`;
  const clean = escapeHtml(text)
    .replace(/\[Confidence:\s*\d+%\]/gi, '')
    .replace(/_FYI:.*?_/gi, '')
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.*?)\*/g, '<em>$1</em>');
  let metaHtml = '';
  if (meta.model || meta.ms) {
    metaHtml = `<div class="msg-meta">
      ${meta.model ? `<span class="msg-model-badge">${meta.model.toUpperCase().slice(0,20)}</span>` : ''}
      ${meta.ms ? `<span class="msg-ms">${meta.ms}ms</span>` : ''}
      ${meta.emotion && meta.emotion !== 'neutral' ? `<span class="msg-emotion">${meta.emotion}</span>` : ''}
    </div>`;
  }
  wrap.innerHTML = `<div class="msg-who">${label}</div><div class="msg-bubble">${clean}</div>${metaHtml}`;
  // Built via DOM APIs rather than string-interpolated into innerHTML --
  // meta.file.name can be whatever the boss said ("create a file called
  // <anything>"), and textContent/addEventListener keep that safe no
  // matter what it contains, instead of trusting it inside HTML/attrs.
  if (meta.file && meta.file.name) {
    const btn = document.createElement('button');
    btn.className = 'msg-file-btn';
    btn.textContent = `⬇ ${meta.file.name}`;
    btn.addEventListener('click', () => downloadGeneratedFile(meta.file.name, meta.file.content || ''));
    wrap.appendChild(btn);
  }
  // A small enumerable set of answers (see server.py's _clarify()) --
  // render real clickable chips instead of leaving the boss to type a
  // free-text reply to a question that only ever has a few valid
  // answers. Same DOM-construction-not-innerHTML reasoning as the file
  // button above: an option's label/value is server data that can
  // originate from the boss's own prior input (a file name they typed),
  // so it goes through textContent, never string-interpolated HTML.
  if (meta.clarify && Array.isArray(meta.clarify.options) && meta.clarify.options.length) {
    const row = document.createElement('div');
    row.className = 'msg-clarify-row';
    meta.clarify.options.forEach((opt) => {
      const btn = document.createElement('button');
      btn.className = 'msg-clarify-btn';
      btn.textContent = opt.label != null ? String(opt.label) : String(opt.value ?? '');
      btn.addEventListener('click', () => {
        row.querySelectorAll('button').forEach((b) => { b.disabled = true; });
        quickSend(opt.value != null ? String(opt.value) : btn.textContent);
      });
      row.appendChild(btn);
    });
    wrap.appendChild(row);
  }
  area.appendChild(wrap);
  area.scrollTop = area.scrollHeight;
}

function downloadGeneratedFile(name, content) {
  const blob = new Blob([content], { type: 'text/plain' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

let thinkEl = null;
function showThinking(label) {
  const area = document.getElementById('messages');
  if (thinkEl) {
    // Re-used for progress updates (e.g. local model download %) rather
    // than stacking a new bubble on every callback tick.
    thinkEl.querySelector('.thinking-text').textContent = label || 'FRIDAY IS THINKING';
    return;
  }
  thinkEl = document.createElement('div');
  thinkEl.className = 'thinking-bubble';
  thinkEl.innerHTML = `<div class="think-dots-wrap"><div class="tdot"></div><div class="tdot"></div><div class="tdot"></div></div><span class="thinking-text">${label || 'FRIDAY IS THINKING'}</span>`;
  area.appendChild(thinkEl);
  area.scrollTop = area.scrollHeight;
}
function hideThinking() { if (thinkEl) { thinkEl.remove(); thinkEl = null; } }

function playAudio(file) {
  if (muted) return;
  if (currentAudio) { currentAudio.pause(); currentAudio = null; }
  const url = `${BASE}/friday/voice/audio?file=${encodeURIComponent(file)}&t=${Date.now()}`;
  currentAudio = new Audio(url);
  // Same page as the arc reactor canvas, so no server round-trip needed —
  // these real play/ended/pause events are the reactor's actual signal.
  currentAudio.addEventListener('play', () => {
    if (window.onFridaySpeak) window.onFridaySpeak();
    if (window.onFridaySpeakFace) window.onFridaySpeakFace();
    startBargeInWatch();
  });
  currentAudio.addEventListener('ended', () => {
    if (window.onFridayDone) window.onFridayDone();
    if (window.onFridayDoneFace) window.onFridayDoneFace();
    stopBargeInWatch();
    openConversationWindow();
  });
  currentAudio.addEventListener('pause', () => {
    if (window.onFridayDone) window.onFridayDone();
    if (window.onFridayDoneFace) window.onFridayDoneFace();
    stopBargeInWatch();
  });
  currentAudio.play().catch(() => {});
}

let faceHideTimer = null;
function showFace() {
  const el = document.getElementById('friday-face');
  if (!el) return;
  el.classList.add('on');
  if (faceHideTimer) clearTimeout(faceHideTimer);
  faceHideTimer = setTimeout(() => el.classList.remove('on'), 4000);
}

async function uploadVisionImage(event) {
  const file = event.target.files[0];
  event.target.value = '';
  if (!file) return;
  const reader = new FileReader();
  reader.onload = async () => {
    // reader.result is "data:image/...;base64,XXXX" — strip the prefix,
    // the vision route only wants the raw base64 payload.
    const b64 = reader.result.split(',')[1];
    addMsg('user', 'YOU', `[image: ${file.name}]`);
    showThinking();
    try {
      const r = await fetch(`${BASE}/friday/vision/analyze`, {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({image: b64, question: ''}),
      });
      const d = await r.json();
      hideThinking();
      addMsg('fri', 'FRIDAY', d.analysis || d.error || "Couldn't make sense of that, boss.");
      showFace();
    } catch (e) {
      hideThinking();
      addMsg('sys', 'SYSTEM', 'Vision analysis failed, boss.');
    }
  };
  reader.readAsDataURL(file);
}

async function uploadIdentifyImage(event) {
  const file = event.target.files[0];
  event.target.value = '';
  if (!file) return;
  const reader = new FileReader();
  reader.onload = async () => {
    const b64 = reader.result.split(',')[1];
    addMsg('sys', 'SYSTEM', 'Identifying...');
    try {
      await fetch(`${BASE}/friday/vision/identify`, {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ image: b64 }),
      });
      // Response intentionally unused here — the server already queued
      // an AR widget for this result (services/friday_hud.py), and this
      // page's own pollWidgets() loop picks it up within ~1s and renders
      // it. Reading/rendering the response here too would just be a
      // second copy racing the one the poll loop is about to deliver.
    } catch (e) {
      addMsg('sys', 'SYSTEM', 'Identify failed, boss.');
    }
  };
  reader.readAsDataURL(file);
}

function toggleMute() {
  muted = !muted;
  const btn = document.getElementById('mute-float');
  btn.innerHTML = muted ? '&#128263;' : '&#128266;';
  btn.classList.toggle('on', muted);
  if (muted && currentAudio) currentAudio.pause();
}

function toggleMic() {
  recording = !recording;
  document.getElementById('mic-btn').classList.toggle('on', recording);
}

// ── Wake-word ("FRIDAY") + hands-free command capture ─────────────────────
// Separate from mic-btn/toggleMic() above (that's an unrelated pre-existing
// stub) — this is continuous background listening for the wake word using
// the browser's free Web Speech API, then MediaRecorder to grab the actual
// command as audio and ship it to the server for real Whisper transcription
// (Web Speech's own transcript is unreliable enough across browsers that we
// don't trust it for the command itself, only for wake-word spotting).
const WAKE_WORD = 'friday';
const FOLLOWUP_MS = 6000;
let voiceModeOn = false;
let wakeRecognition = null;
let commandRecorder = null;
let commandChunks = [];
let silenceTimer = null;
let awaitingCommand = false;

// ── Voice Activity Detection (VAD) ──────────────────────────────────────────
// Two things this adds on top of the wake-word flow above:
//  1. Real end-of-command detection during capture, replacing the old fixed
//     resetSilenceTimer() timeout -- that timer fired once at a hardcoded
//     delay regardless of whether the boss was still mid-sentence, so any
//     command that took longer than ~2.5s to say got cut off. VAD instead
//     watches actual mic volume and only stops once real trailing silence
//     follows detected speech (falls back to the old fixed timer on
//     browsers without Web Audio support).
//  2. True barge-in: speaking over FRIDAY while she's talking interrupts
//     her immediately, without repeating the wake word first (extending
//     the existing "wake word mid-response interrupts" behavior in
//     beginCommandCapture() to "just start talking" too).
// Untestable end-to-end in a sandbox with no mic/speakers -- verified here
// only as far as syntax validity and the fallback path when Web Audio is
// unavailable. Needs real hands-on tuning of the threshold constants below
// against an actual mic/room before relying on it.
const VAD_SPEECH_THRESHOLD = 0.045;   // RMS 0..1 -- above this counts as voice, not room noise
const VAD_SPEECH_SUSTAIN_MS = 150;    // must stay above threshold this long (debounces clicks/pops)
const VAD_TRAILING_SILENCE_MS = 900;  // real silence after speech = utterance done
const VAD_MAX_CAPTURE_MS = 20000;     // hard cap so a stuck-open mic can't record forever
const VAD_BARGE_SUSTAIN_MS = 200;     // slightly longer than speech-start, to avoid a stray
                                       // noise cutting FRIDAY off mid-sentence for nothing

let bargeStream = null;      // persistent mic stream, open only while voice mode is on
let bargeInStop = null;      // active VAD watcher stopper while FRIDAY is speaking
let commandVadStop = null;   // active VAD watcher stopper during command capture

function getAudioContextClass() {
  return window.AudioContext || window.webkitAudioContext || null;
}

function rmsVolume(analyser, data) {
  analyser.getByteTimeDomainData(data);
  let sumSquares = 0;
  for (let i = 0; i < data.length; i++) {
    const norm = (data[i] - 128) / 128;
    sumSquares += norm * norm;
  }
  return Math.sqrt(sumSquares / data.length);
}

// Watches `stream` for voice activity. Calls onSpeechStart() once, the
// first time volume stays above `threshold` for `sustainMs`. If
// `silenceMs` is set, once speech has started, `silenceMs` of continuous
// quiet afterward calls onSilence() and stops. If `noSpeechTimeoutMs` is
// set, giving up on speech ever starting (still silent after that long)
// also calls onSilence() and stops. `maxMs`, if set, is a hard cap on
// total watch time regardless of activity. Returns a stop() function for
// external/early cancellation (which does NOT call onSilence -- that's
// only for the watcher's own natural end conditions).
function watchVoiceActivity(stream, opts) {
  const AC = getAudioContextClass();
  if (!AC || !stream) return null;
  const { threshold, sustainMs, silenceMs, noSpeechTimeoutMs, maxMs, onSpeechStart, onSilence } = opts;

  let ctx;
  try { ctx = new AC(); } catch (e) { return null; }
  const source = ctx.createMediaStreamSource(stream);
  const analyser = ctx.createAnalyser();
  analyser.fftSize = 512;
  source.connect(analyser);
  const data = new Uint8Array(analyser.fftSize);

  let aboveSince = null;
  let belowSince = null;
  let speechStarted = false;
  let rafId = null;
  const startedAt = Date.now();

  function teardown() {
    if (rafId) cancelAnimationFrame(rafId);
    rafId = null;
    try { source.disconnect(); } catch (e) {}
    try { ctx.close(); } catch (e) {}
  }

  function finish() {
    teardown();
    if (onSilence) onSilence();
  }

  function loop() {
    const vol = rmsVolume(analyser, data);
    const now = Date.now();

    if (maxMs && now - startedAt > maxMs) { finish(); return; }
    if (!speechStarted && noSpeechTimeoutMs && now - startedAt > noSpeechTimeoutMs) { finish(); return; }

    if (vol >= threshold) {
      belowSince = null;
      if (aboveSince === null) aboveSince = now;
      if (!speechStarted && now - aboveSince >= sustainMs) {
        speechStarted = true;
        if (onSpeechStart) onSpeechStart();
      }
    } else {
      aboveSince = null;
      if (speechStarted && silenceMs) {
        if (belowSince === null) belowSince = now;
        if (now - belowSince >= silenceMs) { finish(); return; }
      }
    }
    rafId = requestAnimationFrame(loop);
  }

  rafId = requestAnimationFrame(loop);
  return teardown;
}

// echoCancellation matters more here than anywhere else the mic gets
// opened: this stream stays live specifically WHILE FRIDAY's own TTS is
// playing through the speakers, so without it the mic can pick up her own
// voice and barge-in on itself. Most browsers default this to true
// already, but it's requested explicitly rather than relied on -- and it
// still isn't perfect on setups where the mic and speakers are far apart
// (e.g. external speakers), which is part of why VAD_SPEECH_THRESHOLD /
// VAD_BARGE_SUSTAIN_MS above are deliberately not hair-trigger.
const MIC_CONSTRAINTS = { audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } };

async function ensureBargeStream() {
  if (bargeStream) return bargeStream;
  try {
    bargeStream = await navigator.mediaDevices.getUserMedia(MIC_CONSTRAINTS);
  } catch (e) {
    bargeStream = null;
  }
  return bargeStream;
}

function releaseBargeStream() {
  stopBargeInWatch();
  if (bargeStream) { bargeStream.getTracks().forEach(t => t.stop()); bargeStream = null; }
}

// Armed only while FRIDAY's audio is actually playing (see playAudio()) --
// sustained voice energy during that window means "stop talking, I'm
// talking to you now," same intent as the existing wake-word interrupt,
// just without needing the wake word repeated.
function startBargeInWatch() {
  if (!voiceModeOn || awaitingCommand || !bargeStream) return;
  bargeInStop = watchVoiceActivity(bargeStream, {
    threshold: VAD_SPEECH_THRESHOLD,
    sustainMs: VAD_BARGE_SUSTAIN_MS,
    onSpeechStart: () => {
      stopBargeInWatch();
      if (currentAudio && !currentAudio.paused) { currentAudio.pause(); currentAudio.currentTime = 0; }
      try { window.speechSynthesis.cancel(); } catch (e) {}
      beginCommandCapture(false);
    },
  });
}

function stopBargeInWatch() {
  if (bargeInStop) { bargeInStop(); bargeInStop = null; }
}

function getSpeechRecognition() {
  return window.SpeechRecognition || window.webkitSpeechRecognition || null;
}

// Floating "listening" pill, distinct from the status-orb color change
// beginCommandCapture() already does — a persistent state readable at a
// glance beats scanning the chat log mid-sentence.
function showListeningIndicator(active, symbol) {
  let el = document.getElementById('voice-listening-indicator');
  if (!el) {
    el = document.createElement('div');
    el.id = 'voice-listening-indicator';
    el.style.cssText = `
      position: fixed; top: 70px; left: 50%; transform: translateX(-50%);
      padding: 8px 20px; border-radius: 20px; font-size: 11px;
      letter-spacing: 2px; z-index: 100; display: none;
      backdrop-filter: blur(10px); transition: all 0.2s;
    `;
    document.body.appendChild(el);
  }
  if (!active) { el.style.display = 'none'; return; }
  el.style.display = 'block';
  if (symbol === '?') {
    el.style.background = 'rgba(255,204,0,0.15)';
    el.style.border = '1px solid rgba(255,204,0,0.4)';
    el.style.color = '#ffcc00';
    el.textContent = '? DID YOU MEAN ME?';
  } else {
    el.style.background = 'rgba(72,202,228,0.15)';
    el.style.border = '1px solid rgba(72,202,228,0.4)';
    el.style.color = '#48cae4';
    el.textContent = '● LISTENING...';
  }
}

// Local browser TTS for an instant ack on ambiguous wake-word detections —
// no server round trip for a reflexive "Yes, boss?".
function speakQuick(text) {
  try {
    const u = new SpeechSynthesisUtterance(text);
    u.rate = 1.1; u.volume = 0.8;
    window.speechSynthesis.speak(u);
  } catch (e) {}
}

function toggleVoiceMode() {
  const SR = getSpeechRecognition();
  if (!SR) {
    addMsg('sys', 'SYSTEM', "This browser doesn't support wake-word listening, boss.");
    return;
  }
  voiceModeOn = !voiceModeOn;
  const btn = document.getElementById('voice-mode-btn');
  btn.textContent = voiceModeOn ? 'VOICE ON' : 'VOICE OFF';
  btn.classList.toggle('on', voiceModeOn);
  document.getElementById('voice-hint').style.display = voiceModeOn ? 'block' : 'none';
  if (voiceModeOn) {
    startWakeListening();
    ensureBargeStream(); // best-effort -- barge-in just won't work if this fails
  } else {
    stopWakeListening();
    releaseBargeStream();
  }
}

function startWakeListening() {
  const SR = getSpeechRecognition();
  wakeRecognition = new SR();
  wakeRecognition.continuous = true;
  wakeRecognition.interimResults = true;
  wakeRecognition.lang = 'en-US';

  wakeRecognition.onresult = (event) => {
    if (awaitingCommand) return;
    const last = event.results[event.results.length - 1];
    const transcript = Array.from(event.results)
      .map(r => r[0].transcript)
      .join(' ')
      .toLowerCase();
    if (!transcript.includes(WAKE_WORD)) return;

    // confidence is 0/unset on some browsers for interim results — treat
    // that the same as high confidence rather than silently dropping every
    // wake word on browsers that don't report it.
    const confidence = last[0].confidence || 0;
    if (confidence > 0 && confidence < 0.35) return; // background noise — ignored

    if (confidence > 0 && confidence < 0.65) {
      beginCommandCapture(true);
    } else {
      beginCommandCapture(false);
    }
  };

  // Web Speech recognizers stop themselves periodically (silence, browser
  // policy, etc.) — restart automatically so "continuous" listening actually
  // stays continuous while VOICE ON is toggled on.
  wakeRecognition.onend = () => {
    if (voiceModeOn && !awaitingCommand) {
      try { wakeRecognition.start(); } catch (e) {}
    }
  };
  wakeRecognition.onerror = () => {
    if (voiceModeOn && !awaitingCommand) {
      try { wakeRecognition.start(); } catch (e) {}
    }
  };

  try { wakeRecognition.start(); } catch (e) {}
}

function stopWakeListening() {
  awaitingCommand = false;
  if (wakeRecognition) {
    wakeRecognition.onend = null;
    wakeRecognition.onerror = null;
    try { wakeRecognition.stop(); } catch (e) {}
    wakeRecognition = null;
  }
  if (commandRecorder && commandRecorder.state !== 'inactive') {
    try { commandRecorder.stop(); } catch (e) {}
  }
  clearTimeout(silenceTimer);
  if (commandVadStop) { commandVadStop(); commandVadStop = null; }
}

async function beginCommandCapture(ambiguous, timeoutMs) {
  if (awaitingCommand) return;
  awaitingCommand = true;
  try { wakeRecognition.stop(); } catch (e) {}

  // Interrupt: wake word heard mid-response means "stop talking, I'm
  // talking to you now" — harmless to call when nothing is playing.
  if (currentAudio && !currentAudio.paused) { currentAudio.pause(); currentAudio.currentTime = 0; }
  try { window.speechSynthesis.cancel(); } catch (e) {}

  if (ambiguous) {
    showListeningIndicator(true, '?');
    speakQuick('Yes, boss?');
  } else {
    showListeningIndicator(true, '●');
  }
  document.getElementById('status-orb-dot').style.background = 'var(--warn)';

  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia(MIC_CONSTRAINTS);
  } catch (e) {
    addMsg('sys', 'SYSTEM', "Couldn't access the microphone, boss.");
    showListeningIndicator(false);
    awaitingCommand = false;
    if (voiceModeOn) try { wakeRecognition.start(); } catch (e2) {}
    return;
  }

  commandChunks = [];
  commandRecorder = new MediaRecorder(stream);
  commandRecorder.ondataavailable = (e) => { if (e.data.size > 0) commandChunks.push(e.data); };
  commandRecorder.onstop = async () => {
    stream.getTracks().forEach(t => t.stop());
    clearTimeout(silenceTimer);
    if (commandVadStop) { commandVadStop(); commandVadStop = null; }
    showListeningIndicator(false);
    const blob = new Blob(commandChunks, { type: 'audio/webm' });
    await sendCommandAudio(blob);
    awaitingCommand = false;
    if (voiceModeOn) { try { wakeRecognition.start(); } catch (e) {} }
  };

  commandRecorder.start();

  // Real VAD: keep recording as long as the boss keeps talking, stop
  // shortly after genuine trailing silence -- not the fixed-length timer
  // resetSilenceTimer() used to be (see its comment below for why that
  // was a real bug, not just a simplification). Falls back to the old
  // fixed timer wherever Web Audio isn't available.
  commandVadStop = watchVoiceActivity(stream, {
    threshold: VAD_SPEECH_THRESHOLD,
    sustainMs: VAD_SPEECH_SUSTAIN_MS,
    silenceMs: VAD_TRAILING_SILENCE_MS,
    noSpeechTimeoutMs: timeoutMs || 2500,
    maxMs: VAD_MAX_CAPTURE_MS,
    onSilence: () => {
      if (commandRecorder && commandRecorder.state !== 'inactive') commandRecorder.stop();
    },
  });
  if (!commandVadStop) resetSilenceTimer(timeoutMs);
}

function resetSilenceTimer(timeoutMs) {
  clearTimeout(silenceTimer);
  // Fallback only, for browsers without Web Audio support -- fixed-length
  // cutoff regardless of whether the boss is still mid-sentence. Real
  // capture uses watchVoiceActivity() above instead, which extends the
  // recording for as long as speech continues and only stops after actual
  // trailing silence.
  silenceTimer = setTimeout(() => {
    if (commandRecorder && commandRecorder.state !== 'inactive') commandRecorder.stop();
  }, timeoutMs || 2500);
}

// ── Conversation continuity ─────────────────────────────────────────────────
// After FRIDAY finishes speaking, keep listening briefly without requiring
// the wake word again, so "and what about tomorrow" works as a natural
// follow-up instead of every turn needing "friday" repeated.
function openConversationWindow() {
  if (!voiceModeOn || awaitingCommand) return;
  beginCommandCapture(false, FOLLOWUP_MS);
}

async function sendCommandAudio(blob) {
  if (blob.size < 500) return; // near-empty capture (e.g. an unanswered follow-up window) — not worth a transcribe call
  const form = new FormData();
  form.append('audio', blob, 'command.webm');
  try {
    const r = await fetch(`${BASE}/friday/voice/transcribe`, { method: 'POST', body: form });
    const d = await r.json();
    // Confirmed non-enrolled speaker (TV, another person) — stay silent,
    // not an error: this is what actually stops background audio from
    // hijacking the conversation continuity window.
    if (d.rejected) return;
    let text = (d.text || '').trim();
    if (!text) return;
    // Strip a leading wake word so "friday what's my status" becomes
    // "what's my status" before it hits the normal send() path.
    const wakeRe = new RegExp(`^\\s*${WAKE_WORD}\\s*[,:]?\\s*`, 'i');
    text = text.replace(wakeRe, '').trim();
    if (!text) return;
    document.getElementById('chat-inp').value = text;
    send();
  } catch (e) {
    addMsg('sys', 'SYSTEM', 'Voice transcription failed, boss.');
  }
}

// ── Voice enrollment ─────────────────────────────────────────────────────────
// Five ~3.5s samples (rather than one) give Resemblyzer enough voiceprint
// variety to set a usable match threshold on the bridge side.
// Enrollment state lives across separate clicks (one click = one sample,
// no auto-continue) — a prior version looped all 5 samples automatically
// inside one call with the button never disabled, so a single impatient
// re-click mid-loop spawned a second concurrent enrollVoice() run; with
// two loops racing, 28 POSTs in under a minute (instead of 5) was the
// observed result, each capturing whatever partial/garbage audio was
// mid-flight at the moment of the second click.
let enrollSampleCount = 0;
let enrollInFlight = false;
const ENROLL_TARGET = 5;
const ENROLL_SAMPLE_MS = 3500;

async function enrollVoice() {
  const btn = document.getElementById('enroll-voice-btn');
  if (enrollInFlight || enrollSampleCount >= ENROLL_TARGET) return;
  enrollInFlight = true;
  btn.disabled = true;

  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch (e) {
    btn.textContent = '⚠ MIC ACCESS DENIED';
    enrollInFlight = false;
    btn.disabled = false;
    return;
  }

  const chunks = [];
  const recorder = new MediaRecorder(stream);
  recorder.ondataavailable = (e) => { if (e.data.size > 0) chunks.push(e.data); };
  const recordingDone = new Promise((resolve) => { recorder.onstop = resolve; });

  // Visible countdown — unambiguous "safe to speak now" vs "done, uploading".
  let remaining = Math.round(ENROLL_SAMPLE_MS / 1000);
  btn.textContent = `🔴 RECORDING... ${remaining}`;
  const countdown = setInterval(() => {
    remaining -= 1;
    if (remaining > 0) btn.textContent = `🔴 RECORDING... ${remaining}`;
  }, 1000);

  recorder.start();
  await new Promise((resolve) => setTimeout(resolve, ENROLL_SAMPLE_MS));
  recorder.stop();
  await recordingDone;
  clearInterval(countdown);
  stream.getTracks().forEach(t => t.stop());

  btn.textContent = '⏳ Uploading...';
  const blob = new Blob(chunks, { type: 'audio/webm' });
  const form = new FormData();
  form.append('audio', blob, 'enroll.webm');
  form.append('profile', 'default');

  try {
    const r = await fetch(`${BASE}/friday/voice/enroll`, { method: 'POST', body: form });
    const d = await r.json();
    if (!r.ok || d.error) {
      btn.textContent = '⚠ ERROR — CLICK TO RETRY';
      enrollInFlight = false;
      btn.disabled = false;
      return;
    }
    // Trust the server's real count over a local increment — if a
    // request genuinely failed to register server-side, the two could
    // otherwise drift apart silently.
    enrollSampleCount = d.sample_count || enrollSampleCount + 1;
  } catch (e) {
    btn.textContent = '⚠ ERROR — CLICK TO RETRY';
    enrollInFlight = false;
    btn.disabled = false;
    return;
  }

  enrollInFlight = false;
  if (enrollSampleCount >= ENROLL_TARGET) {
    btn.textContent = '✓ VOICE ENROLLED';
    btn.disabled = true; // permanent — no more samples needed
  } else {
    btn.textContent = `🎤 ENROLL MY VOICE (${enrollSampleCount}/${ENROLL_TARGET}) — CLICK TO CONTINUE`;
    btn.disabled = false;
  }
}

async function resetVoiceEnrollment() {
  const resetBtn = document.getElementById('reset-voice-btn');
  const enrollBtn = document.getElementById('enroll-voice-btn');
  resetBtn.disabled = true;
  try {
    await fetch(`${BASE}/friday/voice/reset`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({profile: 'default'}),
    });
  } catch (e) {
    // Even if the reset call itself failed to reach the bridge, still
    // reset local state below — worst case the boss re-enrolls over a
    // profile that didn't actually get wiped, which is a no-op on the
    // bridge side (enroll appends samples, doesn't require a clean slate).
  }
  enrollSampleCount = 0;
  enrollInFlight = false;
  enrollBtn.disabled = false;
  enrollBtn.textContent = '🎤 ENROLL MY VOICE';
  resetBtn.disabled = false;
}

async function setMode(mode) {
  document.querySelectorAll('.mode-btn').forEach(b => {
    b.classList.toggle('active', b.textContent.toLowerCase() === mode);
  });
  await fetch(`${BASE}/mode`, {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({mode}),
  }).catch(() => {});
}

async function runProto(n) {
  const r = await fetch(`${BASE}/friday/protocols/${n}`, {method: 'POST'}).catch(() => null);
  if (r && r.ok) {
    const d = await r.json();
    addMsg('sys', 'SYSTEM', `Protocol ${n}: ${d.name || d.status || 'executed'}.`);
  }
}

async function pollState() {
  if (offlineModeActive) return; // let the offline badge stand until send() clears it
  try {
    const r = await fetch(`${BASE}/state`);
    const d = await r.json();

    const pill = document.getElementById('status-pill');
    if (d.status === 'online') { pill.textContent = 'ONLINE'; pill.className = 'pill online'; }
    else { pill.textContent = 'DEGRADED'; pill.className = 'pill warn'; }

    const jp = document.getElementById('jarvis-pill');
    jp.textContent = d.jarvis_online ? 'JARVIS ON' : 'JARVIS OFF';
    jp.className = d.jarvis_online ? 'pill online' : 'pill warn';

    document.getElementById('cov-banner').className = d.coverage_mode ? 'cov-banner on' : 'cov-banner';
    document.getElementById('model-pill').textContent = (d.voice_mode || 'normal').toUpperCase();
    document.getElementById('status-orb-dot').style.background = d.status === 'online' ? 'var(--green)' : 'var(--warn)';

    const up = d.uptime || 0;
    const h = Math.floor(up/3600), m = Math.floor((up%3600)/60);
    document.getElementById('p-uptime').textContent = h ? `${h}h ${m}m` : `${m}m`;
    document.getElementById('p-jarvis').textContent = d.jarvis_online ? 'ONLINE' : 'OFFLINE';
    document.getElementById('p-jarvis').className = 'info-val ' + (d.jarvis_online ? 'green' : 'danger');
    document.getElementById('p-coverage').textContent = d.coverage_mode ? 'ACTIVE' : 'STANDBY';
    document.getElementById('p-mode').textContent = (d.voice_mode || 'normal').toUpperCase();

    const b = d.budget || {};
    document.getElementById('p-calls').textContent = `${b.calls||0} / ${b.calls_limit||'-'}`;

    if (d.cpu_pct !== undefined && d.cpu_pct !== null) {
      document.getElementById('p-cpu').textContent = `${d.cpu_pct}%`;
      document.getElementById('p-cpu-bar').style.width = `${d.cpu_pct}%`;
      const pwrEl = document.getElementById('hud-pwr');
      if (pwrEl) pwrEl.textContent = `${Math.max(0, Math.round(100 - d.cpu_pct))}%`;
    }
    if (d.ram_pct !== undefined && d.ram_pct !== null) {
      document.getElementById('p-ram').textContent = `${d.ram_pct}%`;
      document.getElementById('p-ram-bar').style.width = `${d.ram_pct}%`;
      document.getElementById('p-ram-bar').className = d.ram_pct > 80 ? 'stat-bar-fill warn' : 'stat-bar-fill';
    }

    const sec = d.security || {};
    document.getElementById('p-threats').textContent = sec.threats || 0;
    document.getElementById('p-blocked').textContent = sec.blocked_ips || 0;

    // HUD edge-strip + reticle labels — real telemetry, not placeholders.
    const rangeLabel = (d.range_level || '---').toUpperCase();
    const threatsLabel = `${sec.threats || 0} THR`;
    const lockLabel = d.locked ? 'ENGAGED' : 'CLEAR';
    const hudRangeEl = document.getElementById('hud-range');
    if (hudRangeEl) hudRangeEl.textContent = rangeLabel;
    const hudThreatsEl = document.getElementById('hud-threats');
    if (hudThreatsEl) hudThreatsEl.textContent = sec.threats || 0;
    const hudLockEl = document.getElementById('hud-lock');
    if (hudLockEl) hudLockEl.textContent = lockLabel;
    window.hudRangeLabel = rangeLabel;
    window.hudThreatsLabel = threatsLabel;
    window.hudLockLabel = lockLabel;

    const hb = d.hulkbuster || {};
    if (typeof setHudThreatState === 'function') {
      setHudThreatState(!!d.locked || !!hb.deployed);
    }

    const training = d.training || {};
    document.getElementById('p-training').textContent = training.facts_learned !== undefined ? training.facts_learned : '-';

    const trend = d.emotional_trend || {};
    if (Object.keys(trend).length) {
      document.getElementById('p-emotions').innerHTML = Object.entries(trend)
        .sort((a,b) => b[1]-a[1]).slice(0,5)
        .map(([e,c]) => `<div class="emotion-badge">${e} (${c})</div>`).join('');
    }
  } catch(e) {
    document.getElementById('status-pill').className = 'pill warn';
  }
}

async function pollVeronica() {
  try {
    const r = await fetch(`${BASE}/friday/veronica/status`);
    const d = await r.json();
    document.getElementById('v-backed').textContent = d.components_backed_up !== undefined ? d.components_backed_up : '-';
    document.getElementById('v-repairs').textContent = d.repairs_performed || 0;
  } catch(e) {}
}

async function pollTrust() {
  try {
    const r = await fetch(`${BASE}/friday/trust`);
    const d = await r.json();
    document.getElementById('trust-tier').textContent = (d.tier || '-').replace('_', ' ').toUpperCase();
    document.getElementById('trust-bar').style.width = `${d.trust || 0}%`;
  } catch(e) {}
}

// ── AR widget system ─────────────────────────────────────────────────────
// spawnWidget(type, content, audioUrl) is exposed on window so any future
// caller (console, or a WebSocket upgrade later) can trigger it directly.
// Backend-initiated spawns arrive via short-poll (pollWidgets below) since
// this Flask process has no WebSocket — see services/friday_hud.py.
const WIDGET_LIFETIME_MS = 9000;
const widgetStage = document.getElementById('widget-stage');

function widgetEscapeHtml(s) {
  const d = document.createElement('div');
  d.textContent = s == null ? '' : s;
  return d.innerHTML;
}

function renderWidgetBody(type, content) {
  if (type === 'data') {
    const rows = (content.rows || []).map(r =>
      `<div class="ar-widget-row"><span class="ar-widget-row-name">${widgetEscapeHtml(r.name)}</span><span class="ar-widget-row-val">${widgetEscapeHtml(String(r.state))}</span></div>`
    ).join('');
    return `<div class="ar-widget-rows">${rows || '<span style="color:var(--muted)">No data.</span>'}</div>`;
  }
  return `<div class="ar-widget-body">${widgetEscapeHtml(content.body || '')}</div>`;
}

function spawnWidget(type, content, audioUrl) {
  const el = document.createElement('div');
  el.className = 'ar-widget';
  el.innerHTML = `
    <div class="ar-widget-title">${widgetEscapeHtml(content.title || type.toUpperCase())}</div>
    ${renderWidgetBody(type, content)}
    ${audioUrl ? '<div class="ar-widget-audio-bar"><div class="ar-widget-audio-fill"></div></div>' : ''}
  `;
  widgetStage.appendChild(el);

  const remove = () => {
    el.classList.add('exiting');
    setTimeout(() => el.remove(), 380);
  };

  if (audioUrl) {
    // Own Audio instance (not the shared currentAudio/playAudio()) so a
    // widget's removal timing is driven by its own line finishing, not
    // whatever else FRIDAY happens to be saying concurrently — but still
    // fires the same face-reactivity hooks so she visibly reacts to it.
    const audio = new Audio(audioUrl);
    const fill = el.querySelector('.ar-widget-audio-fill');
    audio.addEventListener('play', () => {
      if (window.onFridaySpeakFace) window.onFridaySpeakFace();
    });
    audio.addEventListener('timeupdate', () => {
      if (audio.duration) fill.style.width = `${(audio.currentTime / audio.duration) * 100}%`;
    });
    audio.addEventListener('ended', () => {
      if (window.onFridayDoneFace) window.onFridayDoneFace();
      setTimeout(remove, 600);
    });
    audio.addEventListener('error', () => setTimeout(remove, WIDGET_LIFETIME_MS));
    audio.play().catch(() => {});
  } else {
    setTimeout(remove, WIDGET_LIFETIME_MS);
  }
}
window.spawnWidget = spawnWidget;

async function pollWidgets() {
  try {
    const r = await fetch(`${BASE}/friday/hud/poll`);
    const d = await r.json();
    for (const w of (d.widgets || [])) {
      const audioUrl = w.audio_file ? `${BASE}/friday/voice/audio?file=${encodeURIComponent(w.audio_file)}&t=${Date.now()}` : null;
      spawnWidget(w.type, w.content, audioUrl);
    }
  } catch (e) { /* transient network blip — next poll retries */ }
}
setInterval(pollWidgets, 1000);
pollWidgets();

pollState();
pollVeronica();
pollTrust();
setInterval(pollState, 5000);
setInterval(pollVeronica, 30000);
setInterval(pollTrust, 30000);
document.getElementById('chat-inp').focus();

document.addEventListener('keydown', e => {
  if (e.key === 'Escape') closeAll();
  if (e.ctrlKey && e.key === '/') { document.getElementById('chat-inp').focus(); e.preventDefault(); }
});

// FRIDAY arc reactor (blue tinted) — voice-reactive: surges when she
// speaks. window.onFridaySpeak/onFridayDone are called from playAudio()'s
// real Audio play/ended/pause listeners above, same page, no server
// round-trip needed (unlike JARVIS's globe, FRIDAY's HUD has no separate
// page that needs cross-window sync).
(function() {
  const c   = document.getElementById('friday-arc');
  if (!c) return;
  const ctx = c.getContext('2d');
  const W = 32, H = 32, CX = 16, CY = 16;
  let t = 0;
  let speakIntensity = 0;
  let speaking = false;

  window.onFridaySpeak = function() {
    speaking = true;
    speakIntensity = 0;
  };
  window.onFridayDone = function() {
    speaking = false;
  };

  function drawFriday() {
    ctx.clearRect(0, 0, W, H);

    if (speaking) speakIntensity = Math.min(1, speakIntensity + 0.08);
    else          speakIntensity = Math.max(0, speakIntensity - 0.04);

    const glow  = 0.5 + Math.sin(t * 2) * 0.3 + speakIntensity * 0.5;
    const speed = 1 + speakIntensity * 4;

    // Outer ring
    ctx.beginPath();
    ctx.arc(CX, CY, 14, 0, Math.PI * 2);
    ctx.strokeStyle = `rgba(72,202,228,${glow * 0.8})`;
    ctx.lineWidth   = speaking ? 2 : 1.5;
    ctx.shadowColor = '#00b4d8';
    ctx.shadowBlur  = speaking ? 8 * speakIntensity : 0;
    ctx.stroke();
    ctx.shadowBlur  = 0;

    ctx.save();
    ctx.translate(CX, CY);
    ctx.rotate(t * 0.5 * speed);
    for (let i = 0; i < 6; i++) {
      const a1 = (i/6)*Math.PI*2;
      const a2 = a1 + Math.PI/6*(0.7 + speakIntensity*0.3);
      ctx.beginPath();
      ctx.arc(0, 0, 10, a1, a2);
      ctx.strokeStyle = `rgba(0,180,216,${glow*0.7})`;
      ctx.lineWidth   = 2 + speakIntensity * 1.5;
      ctx.stroke();
    }
    ctx.restore();

    ctx.save();
    ctx.translate(CX, CY);
    ctx.rotate(-t * 0.8 * speed);
    for (let i = 0; i < 4; i++) {
      const a1 = (i/4)*Math.PI*2;
      const a2 = a1 + Math.PI/4*(0.6 + speakIntensity*0.4);
      ctx.beginPath();
      ctx.arc(0, 0, 7, a1, a2);
      ctx.strokeStyle = `rgba(0,150,199,${glow*0.6})`;
      ctx.lineWidth   = 1.5 + speakIntensity;
      ctx.stroke();
    }
    ctx.restore();

    // Blue triangle core
    ctx.save();
    ctx.translate(CX, CY);
    ctx.rotate(t * 0.1 * speed);
    const ts = 1 + speakIntensity * 0.3;
    ctx.scale(ts, ts);
    ctx.beginPath();
    for (let i = 0; i < 3; i++) {
      const angle = (i/3)*Math.PI*2 - Math.PI/6;
      const x = Math.cos(angle)*5;
      const y = Math.sin(angle)*5;
      if (i===0) ctx.moveTo(x,y);
      else ctx.lineTo(x,y);
    }
    ctx.closePath();
    ctx.strokeStyle = `rgba(144,224,239,${glow*0.9})`;
    ctx.lineWidth   = 1.5 + speakIntensity;
    ctx.shadowColor = '#48cae4';
    ctx.shadowBlur  = speakIntensity * 6;
    ctx.stroke();
    ctx.shadowBlur  = 0;
    ctx.restore();

    // Blue center glow
    const sz = 4 + speakIntensity * 3;
    const cg = ctx.createRadialGradient(CX,CY,0,CX,CY,sz);
    cg.addColorStop(0, `rgba(200,240,255,${glow})`);
    cg.addColorStop(0.5, `rgba(72,202,228,${glow*0.6})`);
    cg.addColorStop(1, 'rgba(0,168,255,0)');
    ctx.beginPath();
    ctx.arc(CX, CY, sz, 0, Math.PI*2);
    ctx.fillStyle = cg;
    ctx.fill();

    // Pulse ring while speaking
    if (speaking && Math.sin(t * 8) > 0.7) {
      ctx.beginPath();
      ctx.arc(CX, CY, 14 + speakIntensity * 4, 0, Math.PI*2);
      ctx.strokeStyle = `rgba(72,202,228,${speakIntensity * 0.3})`;
      ctx.lineWidth   = 1;
      ctx.stroke();
    }

    t += 0.015;
    requestAnimationFrame(drawFriday);
  }
  drawFriday();
})();

// Holographic face — a separate canvas from friday-arc (that one stays the
// small top-bar reactor); this one is the big centered projection that
// fades in on every response via showFace() above. Kept intentionally
// simple (arcs + lines, no image assets) since it redraws every frame on
// every page load, not just while actively speaking.
(function() {
  const c = document.getElementById('friday-face');
  if (!c) return;
  const ctx = c.getContext('2d');
  const W = 220, H = 220, CX = 110, CY = 100;
  let t = 0;
  let speaking = false;
  let mouthOpen = 0;

  window.onFridaySpeakFace = function() { speaking = true; };
  window.onFridayDoneFace = function() { speaking = false; };

  function drawFace() {
    ctx.clearRect(0, 0, W, H);

    // Jaw / face outline — an open hexagonal contour, not a closed mask,
    // so it reads as a HUD wireframe rather than a solid head.
    ctx.beginPath();
    ctx.moveTo(CX - 55, CY - 40);
    ctx.lineTo(CX - 60, CY + 10);
    ctx.lineTo(CX - 35, CY + 55);
    ctx.lineTo(CX, CY + 70);
    ctx.lineTo(CX + 35, CY + 55);
    ctx.lineTo(CX + 60, CY + 10);
    ctx.lineTo(CX + 55, CY - 40);
    ctx.strokeStyle = 'rgba(72,202,228,0.45)';
    ctx.lineWidth = 1.2;
    ctx.stroke();

    // Scan lines — slow vertical sweep across the face box.
    const scanY = CY - 70 + ((t * 20) % 150);
    ctx.beginPath();
    ctx.moveTo(CX - 65, scanY);
    ctx.lineTo(CX + 65, scanY);
    ctx.strokeStyle = 'rgba(72,202,228,0.15)';
    ctx.lineWidth = 1;
    ctx.stroke();

    // Eyes — glow pulses gently at rest, brighter and slightly wider while
    // speaking so the face doesn't look inert during a response.
    const glow = 0.55 + Math.sin(t * 2) * 0.25 + (speaking ? 0.2 : 0);
    for (const ex of [CX - 22, CX + 22]) {
      const grad = ctx.createRadialGradient(ex, CY - 5, 0, ex, CY - 5, 9);
      grad.addColorStop(0, `rgba(210,245,255,${glow})`);
      grad.addColorStop(0.5, `rgba(72,202,228,${glow * 0.7})`);
      grad.addColorStop(1, 'rgba(0,168,255,0)');
      ctx.beginPath();
      ctx.arc(ex, CY - 5, 9, 0, Math.PI * 2);
      ctx.fillStyle = grad;
      ctx.fill();

      ctx.beginPath();
      ctx.arc(ex, CY - 5, 3, 0, Math.PI * 2);
      ctx.fillStyle = `rgba(255,255,255,${glow})`;
      ctx.fill();
    }

    // Mouth — only animates while speaking; otherwise settles to a flat
    // line so the face doesn't look like it's talking when it isn't.
    if (speaking) mouthOpen = Math.max(0.15, (Math.sin(t * 14) + 1) / 2);
    else mouthOpen = Math.max(0, mouthOpen - 0.08);

    ctx.beginPath();
    ctx.ellipse(CX, CY + 35, 16, 2 + mouthOpen * 8, 0, 0, Math.PI * 2);
    ctx.strokeStyle = `rgba(144,224,239,${0.6 + mouthOpen * 0.4})`;
    ctx.lineWidth = 1.5;
    ctx.stroke();

    // Small data readout — flavor text, not real telemetry.
    ctx.font = '8px monospace';
    ctx.fillStyle = 'rgba(72,202,228,0.5)';
    ctx.fillText(speaking ? 'VOICE: ACTIVE' : 'STANDBY', CX - 60, CY + 90);
    ctx.fillText(`T+${Math.floor(t)}`, CX + 30, CY + 90);

    t += 0.03;
    requestAnimationFrame(drawFace);
  }
  drawFace();
})();
