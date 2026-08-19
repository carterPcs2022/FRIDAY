"""routes/hud_page.py — Budget status and the HUD frontend page routes, split out of the former
monolithic server.py. Registered onto the main Flask app in server.py
via app.register_blueprint(hud_page_bp); nothing here changes behavior,
only where the code lives.
"""
from flask import Blueprint, jsonify

hud_page_bp = Blueprint("hud_page", __name__)


@hud_page_bp.route("/budget")
def budget_status():
    try:
        import budget_2 as budget
        return jsonify(budget.status())
    except Exception as e:
        return jsonify({"error": str(e)})


@hud_page_bp.route("/hud")
def hud():
    return FRIDAY_HUD_HTML


FRIDAY_HUD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>F.R.I.D.A.Y</title>
<style>

/* ==================================
   FRIDAY HOLOGRAPHIC DESIGN
   Deep space blue. Floating glass.
==================================== */

:root {
  --space:    #000814;
  --deep:     #001233;
  --mid:      #023e8a;
  --accent:   #0096c7;
  --bright:   #48cae4;
  --ice:      #90e0ef;
  --glow:     #00b4d8;
  --text:     #caf0f8;
  --muted:    #1a6b8a;
  --glass:    rgba(0,150,199,0.06);
  --glass2:   rgba(0,150,199,0.12);
  --border:   rgba(72,202,228,0.2);
  --border2:  rgba(72,202,228,0.08);
  --warn:     #f77f00;
  --danger:   #e63946;
  --green:    #2dc653;
}

* { box-sizing:border-box; margin:0; padding:0; }

body {
  background: var(--space);
  background-image:
    radial-gradient(ellipse at 20% 50%, rgba(2,62,138,0.15) 0%, transparent 60%),
    radial-gradient(ellipse at 80% 20%, rgba(0,150,199,0.1) 0%, transparent 50%);
  color: var(--text);
  font-family: -apple-system, 'SF Pro Display', 'Helvetica Neue', sans-serif;
  /* 100vh on iOS Safari is the viewport with the address bar hidden, not
     the visible one — content gets cut off behind the toolbar/home
     indicator, or leaves a scrollable gap, depending on scroll state.
     100dvh (dynamic viewport height) tracks the actual visible area;
     100vh stays as a fallback for browsers that don't support dvh. */
  height: 100vh;
  height: 100dvh;
  overflow: hidden;
  position: relative;
}

.particles { position: fixed; inset: 0; pointer-events: none; z-index: 0; overflow: hidden; }
.particle {
  position: absolute; width: 2px; height: 2px; border-radius: 50%;
  background: var(--bright); opacity: 0; animation: float-particle linear infinite;
}
@keyframes float-particle {
  0%   { opacity: 0; transform: translateY(100vh) scale(0); }
  10%  { opacity: 0.6; }
  90%  { opacity: 0.3; }
  100% { opacity: 0; transform: translateY(-10vh) scale(1); }
}

.chat-screen { position: fixed; inset: 0; display: flex; flex-direction: column; z-index: 1; }

.top-bar {
  position: relative; display: flex; align-items: center; padding: 12px 20px; gap: 16px;
  background: linear-gradient(180deg, rgba(0,8,20,0.95) 0%, rgba(0,8,20,0) 100%);
  z-index: 10;
}

.friday-logo { display: flex; align-items: center; gap: 10px; }
.logo-orb {
  width: 32px; height: 32px; border-radius: 50%;
  background: radial-gradient(circle, var(--bright) 0%, var(--accent) 40%, transparent 70%);
  box-shadow: 0 0 20px rgba(72,202,228,0.5), 0 0 40px rgba(0,150,199,0.2);
  animation: orb-breathe 4s ease-in-out infinite; flex-shrink: 0;
}
@keyframes orb-breathe {
  0%,100% { transform: scale(1); box-shadow: 0 0 20px rgba(72,202,228,0.5), 0 0 40px rgba(0,150,199,0.2); }
  50%     { transform: scale(1.15); box-shadow: 0 0 30px rgba(72,202,228,0.7), 0 0 60px rgba(0,150,199,0.4); }
}
.logo-text-wrap { display: flex; flex-direction: column; }
.logo-name { font-size: 16px; font-weight: 700; letter-spacing: 6px; color: var(--bright); text-shadow: 0 0 20px rgba(72,202,228,0.5); }
.logo-version { font-size: 9px; letter-spacing: 2px; color: var(--muted); margin-top: 1px; }

.top-pills { display: flex; gap: 8px; align-items: center; }
.pill {
  padding: 4px 12px; border-radius: 20px; font-size: 10px; letter-spacing: 1px;
  backdrop-filter: blur(10px); border: 1px solid var(--border2); background: var(--glass);
  color: var(--text); white-space: nowrap;
}
.pill.online { border-color: rgba(45,198,83,0.4); background: rgba(45,198,83,0.08); color: var(--green); }
.pill.warn   { border-color: rgba(247,127,0,0.4); background: rgba(247,127,0,0.08); color: var(--warn); }

.top-right { margin-left: auto; display: flex; align-items: center; gap: 10px; }
.clock-display { font-size: 18px; font-weight: 300; letter-spacing: 3px; color: var(--text); font-variant-numeric: tabular-nums; }
.panel-toggle {
  width: 34px; height: 34px; border-radius: 50%; border: 1px solid var(--border);
  background: var(--glass); backdrop-filter: blur(10px); cursor: pointer;
  display: flex; align-items: center; justify-content: center; font-size: 14px;
  color: var(--bright); transition: all 0.2s;
}
.panel-toggle:hover { background: var(--glass2); box-shadow: 0 0 12px rgba(72,202,228,0.2); }
.voice-mode-btn {
  width: auto; border-radius: 16px; padding: 0 12px; font-size: 10px; font-weight: 600;
  letter-spacing: 0.6px; white-space: nowrap;
}
.voice-mode-btn.on {
  border-color: rgba(72,202,228,0.5); color: var(--bright); background: var(--glass2);
  box-shadow: 0 0 12px rgba(72,202,228,0.25); animation: mic-pulse 1.6s ease-in-out infinite;
}

.messages-area {
  flex: 1; overflow-y: auto; padding: 20px; display: flex; flex-direction: column;
  gap: 12px; min-height: 0; scroll-behavior: smooth;
}
.messages-area::-webkit-scrollbar { width: 3px; }
.messages-area::-webkit-scrollbar-track { background: transparent; }
.messages-area::-webkit-scrollbar-thumb { background: var(--muted); border-radius: 2px; }

.msg-wrap { display: flex; flex-direction: column; animation: msg-appear 0.3s ease; max-width: 80%; }
@keyframes msg-appear { from { opacity:0; transform: translateY(8px); } to { opacity:1; transform: translateY(0); } }
.msg-wrap.user { align-self: flex-end; align-items: flex-end; }
.msg-wrap.fri  { align-self: flex-start; align-items: flex-start; }
.msg-wrap.sys  { align-self: center; align-items: center; max-width: 60%; }

.msg-who { font-size: 10px; letter-spacing: 2px; margin-bottom: 4px; font-weight: 600; }
.msg-wrap.user .msg-who { color: rgba(144,224,239,0.6); }
.msg-wrap.fri  .msg-who { color: rgba(72,202,228,0.6); }
.msg-wrap.sys  .msg-who { color: var(--muted); }

.msg-bubble { padding: 12px 18px; border-radius: 20px; font-size: 14px; line-height: 1.6; position: relative; max-width: 100%; }
.msg-wrap.user .msg-bubble {
  background: linear-gradient(135deg, rgba(0,150,199,0.2) 0%, rgba(0,180,216,0.15) 100%);
  border: 1px solid rgba(72,202,228,0.25); border-bottom-right-radius: 4px;
  backdrop-filter: blur(10px); color: var(--ice);
}
.msg-wrap.fri .msg-bubble {
  background: linear-gradient(135deg, rgba(2,62,138,0.3) 0%, rgba(0,70,150,0.2) 100%);
  border: 1px solid rgba(72,202,228,0.15); border-bottom-left-radius: 4px;
  backdrop-filter: blur(10px); color: var(--text);
  box-shadow: 0 4px 20px rgba(0,0,0,0.3), 0 0 0 1px rgba(72,202,228,0.05);
}
.msg-wrap.sys .msg-bubble {
  background: rgba(0,150,199,0.05); border: 1px solid var(--border2); border-radius: 10px;
  font-size: 11px; color: var(--muted); font-style: italic; backdrop-filter: blur(4px);
}

.msg-meta { display: flex; gap: 8px; margin-top: 4px; align-items: center; }
.msg-model-badge {
  font-size: 9px; padding: 2px 8px; border-radius: 10px; border: 1px solid var(--border2);
  background: var(--glass); color: var(--muted); letter-spacing: 1px;
}
.msg-ms { font-size: 9px; color: var(--muted); }
.msg-emotion {
  font-size: 9px; padding: 2px 8px; border-radius: 10px;
  border: 1px solid rgba(72,202,228,0.15); background: rgba(72,202,228,0.06); color: var(--bright);
}

.thinking-bubble {
  align-self: flex-start; display: flex; align-items: center; gap: 10px;
  padding: 12px 18px; border-radius: 20px; border-bottom-left-radius: 4px;
  background: linear-gradient(135deg, rgba(2,62,138,0.3) 0%, rgba(0,70,150,0.2) 100%);
  border: 1px solid rgba(72,202,228,0.15); backdrop-filter: blur(10px); animation: msg-appear 0.2s ease;
}
.think-dots-wrap { display: flex; gap: 5px; }
.tdot { width: 6px; height: 6px; border-radius: 50%; background: var(--bright); animation: tdot-bounce 1.2s ease-in-out infinite; }
.tdot:nth-child(2) { animation-delay: 0.2s; }
.tdot:nth-child(3) { animation-delay: 0.4s; }
@keyframes tdot-bounce { 0%,80%,100% { transform:scale(0.6); opacity:0.3; } 40% { transform:scale(1); opacity:1; } }
.thinking-text { font-size: 12px; color: var(--muted); letter-spacing: 2px; }

.input-zone { padding: 16px 20px 20px; background: linear-gradient(0deg, rgba(0,8,20,0.98) 0%, rgba(0,8,20,0) 100%); position: relative; }
.quick-actions { display: flex; gap: 8px; margin-bottom: 12px; overflow-x: auto; scrollbar-width: none; padding-bottom: 2px; }
.quick-actions::-webkit-scrollbar { display:none; }
.qa-btn {
  padding: 5px 14px; border-radius: 16px; border: 1px solid var(--border2); background: var(--glass);
  color: var(--muted); font-size: 11px; cursor: pointer; white-space: nowrap;
  backdrop-filter: blur(10px); transition: all 0.2s; flex-shrink: 0;
}
.qa-btn:hover { border-color: var(--border); color: var(--bright); background: var(--glass2); }

.input-row {
  display: flex; align-items: center; gap: 10px; background: var(--glass2);
  border: 1px solid var(--border); border-radius: 28px; padding: 8px 8px 8px 20px;
  backdrop-filter: blur(20px);
  box-shadow: 0 4px 30px rgba(0,0,0,0.4), 0 0 0 1px rgba(72,202,228,0.05), inset 0 1px 0 rgba(72,202,228,0.05);
  transition: border-color 0.2s, box-shadow 0.2s;
}
.input-row:focus-within {
  border-color: rgba(72,202,228,0.4);
  box-shadow: 0 4px 30px rgba(0,0,0,0.4), 0 0 20px rgba(72,202,228,0.1), inset 0 1px 0 rgba(72,202,228,0.1);
}
.chat-inp { flex: 1; background: transparent; border: none; outline: none; color: var(--text); font-size: 15px; font-family: inherit; letter-spacing: 0.3px; }
.chat-inp::placeholder { color: var(--muted); }
.voice-hint { font-size: 11px; color: var(--muted); letter-spacing: 0.3px; margin-top: 6px; padding-left: 4px; }

.mic-btn {
  width: 36px; height: 36px; border-radius: 50%; border: 1px solid var(--border2); background: var(--glass);
  color: var(--muted); cursor: pointer; display: flex; align-items:center; justify-content:center;
  font-size: 16px; transition: all 0.2s; flex-shrink: 0;
}
.mic-btn:hover, .mic-btn.on { border-color: rgba(72,202,228,0.4); color: var(--bright); background: var(--glass2); box-shadow: 0 0 12px rgba(72,202,228,0.2); }
.mic-btn.on { animation: mic-pulse 0.8s ease-in-out infinite; }
@keyframes mic-pulse { 0%,100% { box-shadow: 0 0 0 0 rgba(72,202,228,0.3); } 50% { box-shadow: 0 0 0 6px rgba(72,202,228,0); } }

.send-btn {
  width: 40px; height: 40px; border-radius: 50%; border: none;
  background: linear-gradient(135deg, var(--accent) 0%, var(--bright) 100%);
  color: var(--space); cursor: pointer; display: flex; align-items:center; justify-content:center;
  font-size: 16px; transition: all 0.2s; flex-shrink: 0; box-shadow: 0 4px 15px rgba(0,150,199,0.4);
}
.send-btn:hover { transform: scale(1.05); box-shadow: 0 6px 20px rgba(0,150,199,0.6); }

.slide-panel {
  position: fixed; top: 0; bottom: 0; width: 320px;
  background: linear-gradient(135deg, rgba(0,18,51,0.85) 0%, rgba(0,8,20,0.9) 100%);
  backdrop-filter: blur(30px); border: 1px solid var(--border); z-index: 100;
  transition: transform 0.35s cubic-bezier(0.4, 0, 0.2, 1);
  display: flex; flex-direction: column; overflow: hidden;
}
.slide-panel::before {
  content: ''; position: absolute; top: 0; left: 0; right: 0; height: 1px;
  background: linear-gradient(90deg, transparent, var(--bright), transparent); opacity: 0.5;
}
.slide-panel::after {
  content: ''; position: absolute; inset: 0;
  background: linear-gradient(135deg, rgba(72,202,228,0.03) 0%, transparent 60%); pointer-events: none;
}
.panel-left { left: 0; border-right: 1px solid var(--border); border-left: none; transform: translateX(-100%); box-shadow: 4px 0 40px rgba(0,0,0,0.5); }
.panel-left.open { transform: translateX(0); }
.panel-right { right: 0; border-left: 1px solid var(--border); border-right: none; transform: translateX(100%); box-shadow: -4px 0 40px rgba(0,0,0,0.5); }
.panel-right.open { transform: translateX(0); }

.panel-header { padding: 16px 18px; border-bottom: 1px solid var(--border2); display: flex; align-items: center; justify-content: space-between; flex-shrink: 0; }
.panel-title { font-size: 11px; letter-spacing: 4px; color: var(--bright); font-weight: 600; }
.panel-close {
  width: 28px; height: 28px; border-radius: 50%; border: 1px solid var(--border2); background: transparent;
  color: var(--muted); cursor: pointer; display: flex; align-items:center; justify-content:center; font-size: 14px; transition: all 0.2s;
}
.panel-close:hover { border-color: var(--border); color: var(--bright); }

.panel-content { flex: 1; overflow-y: auto; padding: 16px; scrollbar-width: thin; scrollbar-color: var(--muted) transparent; }
.p-section { margin-bottom: 20px; }
.p-section-title { font-size: 9px; letter-spacing: 3px; color: var(--muted); margin-bottom: 10px; text-transform: uppercase; }

.stat-card { background: var(--glass); border: 1px solid var(--border2); border-radius: 12px; padding: 12px 14px; margin-bottom: 8px; transition: border-color 0.2s; }
.stat-card:hover { border-color: var(--border); }
.stat-card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.stat-card-label { font-size: 10px; letter-spacing: 1px; color: var(--muted); }
.stat-card-value { font-size: 16px; font-weight: 700; color: var(--text); letter-spacing: 1px; }
.stat-card-value.green  { color: var(--green); }
.stat-card-value.warn   { color: var(--warn); }
.stat-card-value.danger { color: var(--danger); }
.stat-card-value.bright { color: var(--bright); }

.stat-bar { height: 3px; background: rgba(72,202,228,0.1); border-radius: 2px; overflow: hidden; }
.stat-bar-fill { height: 100%; border-radius: 2px; background: linear-gradient(90deg, var(--accent), var(--bright)); box-shadow: 0 0 6px rgba(72,202,228,0.4); transition: width 1s ease; }
.stat-bar-fill.warn { background: linear-gradient(90deg, #cc4400, var(--warn)); box-shadow: 0 0 6px rgba(247,127,0,0.4); }

.info-row { display: flex; justify-content: space-between; align-items: center; padding: 7px 0; border-bottom: 1px solid var(--border2); font-size: 11px; }
.info-row:last-child { border-bottom: none; }
.info-label { color: var(--muted); }
.info-val   { color: var(--text); }
.info-val.green  { color: var(--green); }
.info-val.bright { color: var(--bright); }
.info-val.warn   { color: var(--warn); }
.info-val.danger { color: var(--danger); }

.veronica-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.ver-card { background: var(--glass); border: 1px solid var(--border2); border-radius: 10px; padding: 10px 12px; text-align: center; }
.ver-card-val { font-size: 20px; font-weight: 700; color: var(--bright); }
.ver-card-label { font-size: 9px; letter-spacing: 2px; color: var(--muted); margin-top: 2px; }

.emotion-grid { display: flex; flex-wrap: wrap; gap: 6px; }
.emotion-badge { padding: 4px 10px; border-radius: 10px; background: var(--glass); border: 1px solid var(--border2); font-size: 10px; color: var(--bright); }

.protocol-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; }
.proto-btn {
  padding: 8px 10px; border-radius: 8px; border: 1px solid var(--border2); background: var(--glass);
  color: var(--muted); font-size: 9px; letter-spacing: 1px; cursor: pointer; text-align: center;
  transition: all 0.2s; font-family: inherit;
}
.proto-btn:hover { border-color: var(--border); color: var(--bright); background: var(--glass2); }

.mode-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 6px; }
.mode-btn {
  padding: 8px 4px; border-radius: 8px; border: 1px solid var(--border2); background: var(--glass);
  color: var(--muted); font-size: 9px; letter-spacing: 1px; cursor: pointer; text-align: center;
  transition: all 0.2s; font-family: inherit;
}
.mode-btn:hover, .mode-btn.active { border-color: rgba(72,202,228,0.4); color: var(--bright); background: rgba(72,202,228,0.08); }

.backdrop { position: fixed; inset: 0; background: rgba(0,0,0,0.4); backdrop-filter: blur(2px); z-index: 99; opacity: 0; pointer-events: none; transition: opacity 0.3s; }
.backdrop.on { opacity: 1; pointer-events: all; }

.status-orb {
  position: fixed; bottom: 100px; right: 20px; width: 48px; height: 48px; border-radius: 50%;
  background: var(--glass2); border: 1px solid var(--border); backdrop-filter: blur(20px);
  display: flex; align-items:center; justify-content:center; cursor: pointer; z-index: 20;
  transition: all 0.2s; box-shadow: 0 4px 20px rgba(0,0,0,0.4);
}
.status-orb:hover { box-shadow: 0 0 20px rgba(72,202,228,0.2); border-color: var(--border); }
.status-orb-dot { width: 12px; height: 12px; border-radius: 50%; background: var(--green); box-shadow: 0 0 8px var(--green); animation: orb-breathe 2s ease-in-out infinite; }

.cov-banner {
  position: fixed; top: 70px; left: 50%; transform: translateX(-50%); padding: 8px 20px; border-radius: 20px;
  background: rgba(247,127,0,0.1); border: 1px solid rgba(247,127,0,0.3); backdrop-filter: blur(10px);
  font-size: 11px; letter-spacing: 2px; color: var(--warn); z-index: 50; display: none;
}
.cov-banner.on { display: block; }

.mute-float {
  position: fixed; bottom: 160px; right: 20px; width: 40px; height: 40px; border-radius: 50%;
  background: var(--glass); border: 1px solid var(--border2); backdrop-filter: blur(20px);
  display: flex; align-items:center; justify-content:center; cursor: pointer; z-index: 20;
  font-size: 16px; color: var(--muted); transition: all 0.2s;
}
.mute-float.on { border-color: rgba(247,127,0,0.4); color: var(--warn); }

/* Holographic face — sits behind the message bubbles (transparent
   background, see .messages-area above) but above the particle field,
   so it reads as a projection glimpsed through the chat rather than a
   separate screen. Own z-index tier (0, tied with .particles) — later
   in the DOM so it paints over particles, but .chat-screen's z-index:1
   still wins over it for every real UI element. */
#friday-face {
  position: fixed; top: 50%; left: 50%; transform: translate(-50%, -50%);
  z-index: 0; opacity: 0; pointer-events: none;
  transition: opacity 0.6s ease;
  filter: drop-shadow(0 0 20px rgba(72,202,228,0.35));
}
#friday-face.on { opacity: 0.85; }

/* ── AR widget stage — spawnWidget() pops these up top-right, below the
   status pills, above everything else. Delivered via short-poll (no
   WebSocket in this Flask process — see services/friday_hud.py). ── */
.widget-stage {
  position: fixed; top: 76px; right: 20px; z-index: 40;
  display: flex; flex-direction: column; gap: 12px;
  width: 300px; pointer-events: none;
  perspective: 1200px;
}
.ar-widget {
  pointer-events: auto;
  background: linear-gradient(160deg, var(--glass2), var(--glass));
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 14px 16px;
  backdrop-filter: blur(14px);
  box-shadow: 0 0 24px rgba(0,180,216,0.15), inset 0 0 30px rgba(72,202,228,0.03);
  transform-style: preserve-3d;
  transform: rotateX(10deg) rotateY(-6deg) scale(0.85) translateZ(-50px);
  opacity: 0;
  animation: widget-in 0.5s cubic-bezier(.2,.9,.25,1.1) forwards;
}
.ar-widget.exiting { animation: widget-out 0.35s ease-in forwards; }
@keyframes widget-in {
  0%   { opacity: 0; transform: rotateX(16deg) rotateY(-12deg) scale(0.78) translateZ(-90px); }
  60%  { opacity: 1; transform: rotateX(-2deg) rotateY(2deg) scale(1.04) translateZ(10px); }
  100% { opacity: 1; transform: rotateX(0) rotateY(0) scale(1) translateZ(0); }
}
@keyframes widget-out {
  0%   { opacity: 1; transform: rotateX(0) scale(1) translateZ(0); }
  100% { opacity: 0; transform: rotateX(8deg) scale(0.85) translateZ(-60px); }
}
.ar-widget-title {
  font-size: 10px; letter-spacing: 3px; color: var(--bright); text-transform: uppercase;
  margin-bottom: 8px; display: flex; align-items: center; gap: 7px;
}
.ar-widget-title::before {
  content: ''; width: 6px; height: 6px; border-radius: 50%; background: var(--glow);
  box-shadow: 0 0 6px var(--glow); animation: orb-breathe 1.4s ease-in-out infinite;
}
.ar-widget-body { font-size: 12.5px; line-height: 1.55; color: var(--text); }
.ar-widget-rows { display: flex; flex-direction: column; gap: 5px; }
.ar-widget-row {
  display: flex; justify-content: space-between; font-size: 11px;
  padding: 3px 0; border-bottom: 1px solid var(--border2);
}
.ar-widget-row-name { color: var(--muted); letter-spacing: 0.5px; }
.ar-widget-row-val { color: var(--ice); }
.ar-widget-audio-bar { margin-top: 8px; height: 2px; background: var(--border2); border-radius: 1px; overflow: hidden; }
.ar-widget-audio-fill { height: 100%; width: 0%; background: linear-gradient(90deg, var(--accent), var(--bright)); transition: width 0.1s linear; }

@media (max-width: 700px) {
  /* .top-bar packs a logo, 3 status pills, a clock, and 6 buttons into
     one row — fine on a desktop-width viewport, but nothing stops it
     overflowing/clipping on a phone. Wrapping (not shrinking text) keeps
     every control reachable rather than guessing at which ones to hide —
     but wrapping also makes it roughly twice as tall, so the fixed-
     position HUD layers below it (widget-stage, hud-edge-strip) need
     more clearance than their desktop top offsets give them, or they'd
     sit under the wrapped second row instead of below it. These are
     estimates for a typical 2-row wrap, not measured against a real
     device — may want a pixel nudge once seen on an actual phone. */
  .top-bar { flex-wrap: wrap; padding: 10px 12px; gap: 8px 10px; }
  .top-pills { flex-wrap: wrap; }
  .top-right { flex-wrap: wrap; justify-content: flex-end; gap: 6px 8px; margin-left: 0; width: 100%; }
  .clock-display { font-size: 15px; }

  .widget-stage { left: 12px; right: 12px; width: auto; top: 112px; }
  #hud-edge-strip { top: 120px !important; }

  .slide-panel { width: min(320px, 88vw); }
}

</style>
</head>
<body>

<div class="particles" id="particles"></div>
<canvas id="friday-face" width="220" height="220"></canvas>

<!-- HELMET VIEW — first-person HUD overlay. Every readout below reflects
     something FRIDAY actually tracks (security/lockdown/protocol state) —
     no decorative flight-HUD placeholders that never update. -->
<canvas id="reticle-overlay" width="680" height="680"
  style="position:fixed;top:50%;left:50%;
  transform:translate(-50%,-50%);
  opacity:0.35;pointer-events:none;z-index:1;
  mix-blend-mode:screen">
</canvas>

<div id="hud-edge-strip" style="position:fixed;top:80px;left:20px;right:20px;
  display:flex;justify-content:space-between;
  pointer-events:none;z-index:2;opacity:0.7">
  <div style="font-size:9px;color:var(--hud-glow, rgba(72,202,228,0.7));
    letter-spacing:1px;font-family:'Courier New'">
    <div>RANGE: <span id="hud-range">---</span></div>
    <div>THREATS: <span id="hud-threats">0</span></div>
  </div>
  <div style="font-size:9px;color:var(--hud-glow, rgba(72,202,228,0.7));
    letter-spacing:1px;text-align:right;
    font-family:'Courier New'">
    <div>LOCK: <span id="hud-lock">CLEAR</span></div>
    <div>PWR: <span id="hud-pwr">---</span></div>
  </div>
</div>

<canvas id="corner-radar-friday" width="80" height="80"
  style="position:fixed;bottom:100px;left:20px;
  opacity:0.5;pointer-events:none;z-index:2">
</canvas>
<div class="widget-stage" id="widget-stage"></div>
<div class="cov-banner" id="cov-banner">COVERAGE MODE - JARVIS OFFLINE</div>
<div class="backdrop" id="backdrop" onclick="closeAll()"></div>

<!-- LEFT PANEL - Systems -->
<div class="slide-panel panel-left" id="panel-left">
  <div class="panel-header">
    <div class="panel-title">SYSTEMS</div>
    <button class="panel-close" onclick="toggleLeft()">&times;</button>
  </div>
  <div class="panel-content">

    <div class="p-section">
      <div class="p-section-title">DIAGNOSTICS</div>
      <div class="stat-card">
        <div class="stat-card-header"><span class="stat-card-label">CPU</span><span class="stat-card-value bright" id="p-cpu">-%</span></div>
        <div class="stat-bar"><div class="stat-bar-fill" id="p-cpu-bar" style="width:0%"></div></div>
      </div>
      <div class="stat-card">
        <div class="stat-card-header"><span class="stat-card-label">MEMORY</span><span class="stat-card-value" id="p-ram">-%</span></div>
        <div class="stat-bar"><div class="stat-bar-fill" id="p-ram-bar" style="width:0%"></div></div>
      </div>
    </div>

    <div class="p-section">
      <div class="p-section-title">STATUS</div>
      <div class="info-row"><span class="info-label">UPTIME</span><span class="info-val bright" id="p-uptime">-</span></div>
      <div class="info-row"><span class="info-label">JARVIS</span><span class="info-val" id="p-jarvis">-</span></div>
      <div class="info-row"><span class="info-label">COVERAGE</span><span class="info-val" id="p-coverage">STANDBY</span></div>
      <div class="info-row"><span class="info-label">MODE</span><span class="info-val bright" id="p-mode">NORMAL</span></div>
      <div class="info-row"><span class="info-label">API CALLS</span><span class="info-val" id="p-calls">-</span></div>
    </div>

    <div class="p-section">
      <div class="p-section-title">SECURITY</div>
      <div class="info-row"><span class="info-label">THREATS</span><span class="info-val danger" id="p-threats">0</span></div>
      <div class="info-row"><span class="info-label">BLOCKED IPS</span><span class="info-val warn" id="p-blocked">0</span></div>
    </div>

    <div class="p-section">
      <div class="p-section-title">VERONICA</div>
      <div class="veronica-grid">
        <div class="ver-card"><div class="ver-card-val" id="v-backed">-</div><div class="ver-card-label">BACKED UP</div></div>
        <div class="ver-card"><div class="ver-card-val" id="v-repairs">0</div><div class="ver-card-label">REPAIRS</div></div>
      </div>
    </div>

    <div class="p-section">
      <div class="p-section-title">VOICE MODE</div>
      <div class="mode-grid">
        <button class="mode-btn active" onclick="setMode('normal')">NORMAL</button>
        <button class="mode-btn" onclick="setMode('focused')">FOCUSED</button>
        <button class="mode-btn" onclick="setMode('support')">SUPPORT</button>
        <button class="mode-btn" onclick="setMode('coverage')">COVERAGE</button>
      </div>
    </div>

    <div class="p-section">
      <div class="p-section-title">TRAINING WHEELS</div>
      <div class="stat-card">
        <div class="stat-card-header"><span class="stat-card-label">TRUST TIER</span><span class="stat-card-value bright" id="trust-tier">-</span></div>
        <div class="stat-bar"><div class="stat-bar-fill" id="trust-bar" style="width:0%"></div></div>
      </div>
    </div>

  </div>
</div>

<!-- RIGHT PANEL - Intelligence -->
<div class="slide-panel panel-right" id="panel-right">
  <div class="panel-header">
    <div class="panel-title">INTELLIGENCE</div>
    <button class="panel-close" onclick="toggleRight()">&times;</button>
  </div>
  <div class="panel-content">

    <div class="p-section">
      <div class="p-section-title">EMOTIONAL TREND</div>
      <div class="emotion-grid" id="p-emotions"><div class="emotion-badge">NEUTRAL</div></div>
    </div>

    <div class="p-section">
      <div class="p-section-title">TRAINING</div>
      <div class="info-row"><span class="info-label">FACTS LEARNED</span><span class="info-val bright" id="p-training">-</span></div>
    </div>

    <div class="p-section">
      <div class="p-section-title">PROTOCOLS</div>
      <div class="protocol-grid">
        <button class="proto-btn" onclick="runProto(1)">P1 COVERAGE</button>
        <button class="proto-btn" onclick="runProto(3)">P3 DARK MODE</button>
        <button class="proto-btn" onclick="runProto(16)">P16 CHECK-IN</button>
        <button class="proto-btn" onclick="runProto(20)">P20 MORNING</button>
      </div>
    </div>

    <div class="p-section">
      <div class="p-section-title">QUICK LINKS</div>
      <div class="info-row"><a href="/friday/veronica/selftest" target="_blank" style="color:var(--bright);text-decoration:none;font-size:11px">Veronica Self-Test -&gt;</a></div>
      <div class="info-row"><a href="/friday/protocols" target="_blank" style="color:var(--bright);text-decoration:none;font-size:11px">All Protocols -&gt;</a></div>
    </div>

  </div>
</div>

<!-- MAIN CHAT SCREEN -->
<div class="chat-screen">

  <div class="top-bar">
    <div class="friday-logo">
      <canvas id="friday-arc" width="32" height="32" style="border-radius:50%;display:block"></canvas>
      <div class="logo-text-wrap">
        <div class="logo-name">F.R.I.D.A.Y</div>
        <div class="logo-version">HOLOGRAPHIC INTERFACE</div>
      </div>
    </div>

    <div class="top-pills">
      <div class="pill online" id="status-pill">ONLINE</div>
      <div class="pill" id="jarvis-pill">JARVIS -</div>
      <div class="pill" id="model-pill">NORMAL</div>
    </div>

    <div class="top-right">
      <div class="clock-display" id="clock">--:--:--</div>
      <button class="panel-toggle voice-mode-btn" id="voice-mode-btn" onclick="toggleVoiceMode()" title="Hands-free wake-word listening">VOICE OFF</button>
      <button class="panel-toggle voice-mode-btn" id="enroll-voice-btn" onclick="enrollVoice()" title="Enroll your voice for speaker verification">&#127908; ENROLL MY VOICE</button>
      <button class="panel-toggle" id="reset-voice-btn" onclick="resetVoiceEnrollment()" title="Wipe the stored voice profile and start over" style="font-size:9px">Reset &amp; Re-enroll</button>
      <button class="panel-toggle" onclick="toggleLeft()" title="Systems">&#9881;</button>
      <button class="panel-toggle" onclick="toggleRight()" title="Intelligence">&#9670;</button>
      <button id="reticle-toggle-btn" onclick="toggleReticle()"
        style="padding:4px 12px;border-radius:2px;
        border:1px solid rgba(72,202,228,0.6);
        background:transparent;color:#48cae4;
        font-size:9px;letter-spacing:2px;cursor:pointer">
        &#9678; HELMET VIEW
      </button>
    </div>
  </div>

  <div class="messages-area" id="messages">
    <div class="msg-wrap sys">
      <div class="msg-who">SYSTEM</div>
      <div class="msg-bubble">F.R.I.D.A.Y online. Ready when you are, boss.</div>
    </div>
  </div>

  <div class="input-zone">
    <div class="quick-actions">
      <button class="qa-btn" onclick="quickSend('FRIDAY run a morning brief')">Morning Brief</button>
      <button class="qa-btn" onclick="quickSend('FRIDAY threat assessment')">Threat Scan</button>
      <button class="qa-btn" onclick="quickSend('What is your status')">Status</button>
    </div>

    <div class="input-row">
      <input class="chat-inp" id="chat-inp" placeholder="Say 'FRIDAY' or type here, boss..."
             onkeydown="if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();send()}">
      <input type="file" id="vision-file" accept="image/*" style="display:none" onchange="uploadVisionImage(event)">
      <button class="mic-btn" id="vision-btn" onclick="document.getElementById('vision-file').click()" title="Show FRIDAY something (chat description)">&#128206;</button>
      <input type="file" id="identify-file" accept="image/*" style="display:none" onchange="uploadIdentifyImage(event)">
      <button class="mic-btn" id="identify-btn" onclick="document.getElementById('identify-file').click()" title="Quick identify (spawns an AR widget)">&#128065;</button>
      <button class="mic-btn" id="mic-btn" onclick="toggleMic()">&#127908;</button>
      <button class="send-btn" onclick="send()">&#9654;</button>
    </div>
    <div class="voice-hint" id="voice-hint" style="display:none;">Listening for "FRIDAY" — say the wake word, then your command.</div>
  </div>

</div>

<button class="status-orb" onclick="toggleLeft()" title="System status">
  <div class="status-orb-dot" id="status-orb-dot"></div>
</button>

<button class="mute-float" id="mute-float" onclick="toggleMute()" title="Mute voice">&#128266;</button>

<script>
const BASE = '';
let muted = false, recording = false;
let currentAudio = null;
let leftOpen = false, rightOpen = false;

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
    const r = await fetch(`${BASE}/command`, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({prompt: text}),
    });
    const d = await r.json();
    hideThinking();
    addMsg('fri', 'FRIDAY', d.response || '...', {model: d.model || '', ms: d.ms || 0, emotion: d.emotion});
    showFace();
    if (!muted && d.has_audio && d.audio_file) playAudio(d.audio_file);
  } catch(e) {
    hideThinking();
    addMsg('sys', 'SYSTEM', 'Connection issue, boss.');
  }
}

function quickSend(text) {
  document.getElementById('chat-inp').value = text;
  send();
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
    .replace(/\\[Confidence:\\s*\\d+%\\]/gi, '')
    .replace(/_FYI:.*?_/gi, '')
    .replace(/\\*\\*(.*?)\\*\\*/g, '<strong>$1</strong>')
    .replace(/\\*(.*?)\\*/g, '<em>$1</em>');
  let metaHtml = '';
  if (meta.model || meta.ms) {
    metaHtml = `<div class="msg-meta">
      ${meta.model ? `<span class="msg-model-badge">${meta.model.toUpperCase().slice(0,20)}</span>` : ''}
      ${meta.ms ? `<span class="msg-ms">${meta.ms}ms</span>` : ''}
      ${meta.emotion && meta.emotion !== 'neutral' ? `<span class="msg-emotion">${meta.emotion}</span>` : ''}
    </div>`;
  }
  wrap.innerHTML = `<div class="msg-who">${label}</div><div class="msg-bubble">${clean}</div>${metaHtml}`;
  area.appendChild(wrap);
  area.scrollTop = area.scrollHeight;
}

let thinkEl = null;
function showThinking() {
  const area = document.getElementById('messages');
  thinkEl = document.createElement('div');
  thinkEl.className = 'thinking-bubble';
  thinkEl.innerHTML = `<div class="think-dots-wrap"><div class="tdot"></div><div class="tdot"></div><div class="tdot"></div></div><span class="thinking-text">FRIDAY IS THINKING</span>`;
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
  });
  currentAudio.addEventListener('ended', () => {
    if (window.onFridayDone) window.onFridayDone();
    if (window.onFridayDoneFace) window.onFridayDoneFace();
    openConversationWindow();
  });
  currentAudio.addEventListener('pause', () => {
    if (window.onFridayDone) window.onFridayDone();
    if (window.onFridayDoneFace) window.onFridayDoneFace();
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
  if (voiceModeOn) startWakeListening();
  else stopWakeListening();
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
    stream = await navigator.mediaDevices.getUserMedia({ audio: true });
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
    showListeningIndicator(false);
    const blob = new Blob(commandChunks, { type: 'audio/webm' });
    await sendCommandAudio(blob);
    awaitingCommand = false;
    if (voiceModeOn) { try { wakeRecognition.start(); } catch (e) {} }
  };

  commandRecorder.start();
  resetSilenceTimer(timeoutMs);
}

function resetSilenceTimer(timeoutMs) {
  clearTimeout(silenceTimer);
  // 2.5s of silence after the wake word = "the command is done" by default
  // (no reliable cross-browser voice-activity signal to key off of); the
  // follow-up conversation window below passes a longer timeout instead.
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
</script>

<script>
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
</script>
</body>
</html>
"""
