// ── HUD color state — FRIDAY's own palette (--bright/--glow from :root),
// not JARVIS's leftover rgba(0,168,255,...) blue. Shifts to her existing
// --danger red when locked down or HulkBuster is deployed, driven by
// setHudThreatState() from pollState() below — one source of truth for
// both the canvas-drawn elements and the edge-strip HTML labels (via the
// --hud-glow CSS variable).
const HUD_NORMAL = {r: 72,  g: 202, b: 228};  // --bright
const HUD_ALERT  = {r: 230, g: 57,  b: 70};   // --danger
let hudColor = HUD_NORMAL;
let hudThreatActive = false;

function setHudThreatState(active) {
  if (active === hudThreatActive) return;
  hudThreatActive = active;
  hudColor = active ? HUD_ALERT : HUD_NORMAL;
  document.documentElement.style.setProperty(
    '--hud-glow', `rgba(${hudColor.r},${hudColor.g},${hudColor.b},0.7)`);
  const btn = document.getElementById('reticle-toggle-btn');
  if (btn) btn.style.color = `rgb(${hudColor.r},${hudColor.g},${hudColor.b})`;
}

// ── Helmet view — first-person targeting reticle overlay ────────────────────
// Sized from the viewport, not a fixed 680x680 — that was fine on a
// desktop window but dwarfed any phone screen, so most of the ring/labels
// rendered off-screen. Every radius/offset below scales off `scale`
// (relative to the original 340px reference half-size) instead of being
// hardcoded, so resizing the canvas keeps the whole design proportional
// rather than just cropping a fixed-size drawing.
(function() {
  const c = document.getElementById('reticle-overlay');
  if (!c) return;
  const ctx = c.getContext('2d');
  let t = 0;

  function sizeCanvas() {
    const size = Math.max(240, Math.min(window.innerWidth, window.innerHeight, 680) * 0.85);
    c.width = size;
    c.height = size;
  }
  sizeCanvas();
  window.addEventListener('resize', sizeCanvas);
  window.addEventListener('orientationchange', sizeCanvas);

  function rgba(mult) {
    return `rgba(${hudColor.r},${hudColor.g},${hudColor.b},${mult})`;
  }

  function drawReticle() {
    const W = c.width, H = c.height;
    const CX = W / 2, CY = H / 2;
    const scale = CX / 340;
    ctx.clearRect(0, 0, W, H);
    const glow = 0.4 + Math.sin(t * 0.8) * 0.15;
    const pulse = hudThreatActive ? 0.5 + Math.sin(t * 4) * 0.5 : 0;

    const R = 220 * scale;
    ctx.strokeStyle = rgba(glow * 0.5 + pulse * 0.3);
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.arc(CX, CY, R, 0, Math.PI * 2);
    ctx.stroke();

    for (let i = 0; i < 72; i++) {
      const angle = (i / 72) * Math.PI * 2;
      const isLong = i % 6 === 0;
      const inner = R - (isLong ? 12 : 5) * scale;
      const x1 = CX + Math.cos(angle) * inner;
      const y1 = CY + Math.sin(angle) * inner;
      const x2 = CX + Math.cos(angle) * R;
      const y2 = CY + Math.sin(angle) * R;
      ctx.beginPath();
      ctx.moveTo(x1, y1);
      ctx.lineTo(x2, y2);
      ctx.strokeStyle = isLong ? rgba(glow * 0.7) : rgba(glow * 0.25);
      ctx.lineWidth = isLong ? 1.5 : 0.5;
      ctx.stroke();
    }

    // Twin interlocking arcs rather than one segmented hex ring — a softer,
    // more fluid motif than the mechanical original, rotating in opposite
    // directions to feel less like a static gunsight.
    ctx.save();
    ctx.translate(CX, CY);
    const R2 = 160 * scale;
    [1, -1].forEach((dir) => {
      ctx.save();
      ctx.rotate(t * 0.15 * dir);
      for (let i = 0; i < 6; i++) {
        const a1 = (i / 6) * Math.PI * 2;
        const a2 = a1 + Math.PI / 6 * 0.55;
        ctx.beginPath();
        ctx.arc(0, 0, dir === 1 ? R2 : R2 - 14 * scale, a1, a2);
        ctx.strokeStyle = rgba(glow * (dir === 1 ? 0.4 : 0.25));
        ctx.lineWidth = 1;
        ctx.stroke();
      }
      ctx.restore();
    });
    ctx.restore();

    // Center crosshair, breathing gently in sync with her chat orb pulse
    // (.ar-widget-orb elsewhere on the page) instead of a fixed size.
    const chSize = (14 + pulse * 4) * scale;
    ctx.strokeStyle = rgba(glow * 0.6 + pulse * 0.3);
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(CX - chSize, CY);
    ctx.lineTo(CX - chSize/2, CY);
    ctx.moveTo(CX + chSize/2, CY);
    ctx.lineTo(CX + chSize, CY);
    ctx.moveTo(CX, CY - chSize);
    ctx.lineTo(CX, CY - chSize/2);
    ctx.moveTo(CX, CY + chSize/2);
    ctx.lineTo(CX, CY + chSize);
    ctx.stroke();

    ctx.font = `${Math.max(8, 9 * scale)}px Courier New`;
    ctx.fillStyle = rgba(glow * 0.5);
    const labels = [
      {angle: -Math.PI/2, text: hudThreatActive ? 'ALERT' : 'SYS OK'},
      {angle: 0, text: window.hudRangeLabel || '---'},
      {angle: Math.PI/2, text: window.hudThreatsLabel || '0 THR'},
      {angle: Math.PI, text: window.hudLockLabel || 'CLEAR'},
    ];
    labels.forEach(l => {
      const lx = CX + Math.cos(l.angle) * (R + 16 * scale);
      const ly = CY + Math.sin(l.angle) * (R + 16 * scale);
      ctx.textAlign = 'center';
      ctx.fillText(l.text, lx, ly);
    });

    t += 0.01;
    requestAnimationFrame(drawReticle);
  }
  drawReticle();
})();

// ── Corner radar sweep ──────────────────────────────────────────────────────
(function() {
  const c = document.getElementById('corner-radar-friday');
  if (!c) return;
  const ctx = c.getContext('2d');
  let sweepAngle = 0;

  function drawRadar() {
    ctx.clearRect(0, 0, 80, 80);
    const CX = 40, CY = 40, R = 32;
    const base = `rgba(${hudColor.r},${hudColor.g},${hudColor.b},`;

    ctx.strokeStyle = base + '0.3)';
    ctx.lineWidth = 0.5;
    ctx.beginPath();
    ctx.arc(CX, CY, R, 0, Math.PI * 2);
    ctx.stroke();
    ctx.beginPath();
    ctx.arc(CX, CY, R * 0.6, 0, Math.PI * 2);
    ctx.stroke();

    ctx.beginPath();
    ctx.moveTo(CX - R, CY); ctx.lineTo(CX + R, CY);
    ctx.moveTo(CX, CY - R); ctx.lineTo(CX, CY + R);
    ctx.stroke();

    ctx.save();
    ctx.translate(CX, CY);
    ctx.rotate(sweepAngle);
    const grad = ctx.createLinearGradient(0, 0, R, 0);
    grad.addColorStop(0, base + '0.5)');
    grad.addColorStop(1, base + '0)');
    ctx.strokeStyle = grad;
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(0, 0);
    ctx.lineTo(R, 0);
    ctx.stroke();
    ctx.restore();

    // A dot at the threat-count position when there's anything to show —
    // makes the radar reflect something real instead of sweeping over
    // nothing, without needing actual spatial threat data FRIDAY doesn't have.
    if (hudThreatActive) {
      const dotAngle = sweepAngle - 0.3;
      ctx.beginPath();
      ctx.arc(CX + Math.cos(dotAngle) * R * 0.75, CY + Math.sin(dotAngle) * R * 0.75, 2.5, 0, Math.PI * 2);
      ctx.fillStyle = base + '0.9)';
      ctx.fill();
    }

    sweepAngle += 0.02;
    requestAnimationFrame(drawRadar);
  }
  drawRadar();
})();

// ── Toggle + localStorage persistence ───────────────────────────────────────
let reticleOn = true;
function toggleReticle() {
  reticleOn = !reticleOn;
  localStorage.setItem('helmetViewOn', reticleOn);
  const display = reticleOn ? 'block' : 'none';
  document.getElementById('reticle-overlay').style.display = display;
  document.getElementById('hud-edge-strip').style.display = display;
  document.getElementById('corner-radar-friday').style.display = display;
  const btn = document.getElementById('reticle-toggle-btn');
  btn.style.borderColor = reticleOn
    ? `rgba(${hudColor.r},${hudColor.g},${hudColor.b},0.6)`
    : `rgba(${hudColor.r},${hudColor.g},${hudColor.b},0.3)`;
  btn.style.color = `rgb(${hudColor.r},${hudColor.g},${hudColor.b})`;
}
(function() {
  const savedState = localStorage.getItem('helmetViewOn');
  if (savedState === 'false') {
    reticleOn = false;
    document.getElementById('reticle-overlay').style.display = 'none';
    document.getElementById('hud-edge-strip').style.display = 'none';
    document.getElementById('corner-radar-friday').style.display = 'none';
    document.getElementById('reticle-toggle-btn').style.borderColor = 'rgba(0,168,255,0.3)';
  }
})();
