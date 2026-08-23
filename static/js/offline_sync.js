// static/js/offline_sync.js — keeps a read-only local snapshot of tasks,
// notes, and upcoming calendar events so there's something to look up
// with zero internet. Sync-only, deliberately: nothing here ever writes
// back to the server, so there's no offline-edit queue or conflict-
// resolution problem to solve (see the offline-mode scoping conversation
// for why that boundary is intentional, not a gap).

const SNAPSHOT_KEY = 'friday_offline_snapshot';
const SYNC_INTERVAL_MS = 5 * 60 * 1000;

async function syncOfflineSnapshot() {
  if (!navigator.onLine) return null;
  try {
    const r = await fetch('/friday/offline/snapshot');
    if (!r.ok) return null;
    const data = await r.json();
    data.synced_at = Date.now();
    localStorage.setItem(SNAPSHOT_KEY, JSON.stringify(data));
    return data;
  } catch (e) {
    return null;
  }
}

function getCachedSnapshot() {
  try {
    const raw = localStorage.getItem(SNAPSHOT_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch (e) {
    return null;
  }
}

function _age(synced_at) {
  const mins = Math.round((Date.now() - synced_at) / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins} min ago`;
  return `${Math.round(mins / 60)}h ago`;
}

function formatSnapshotForChat(snapshot) {
  if (!snapshot) {
    return "No cached data yet, boss — I haven't synced since you last had a connection.";
  }
  const lines = [`Last synced ${_age(snapshot.synced_at)}. This may be stale.`];

  const tasks = (snapshot.tasks || []).filter((t) => !t.done);
  lines.push(tasks.length
    ? `Tasks (${tasks.length}): ` + tasks.slice(0, 8).map((t) => t.task).join('; ')
    : 'Tasks: none pending.');

  const events = snapshot.events || [];
  lines.push(events.length
    ? `Upcoming (${events.length}): ` + events.slice(0, 5).map((e) => e.title).join('; ')
    : 'Upcoming: nothing on the calendar.');

  const notes = snapshot.notes || [];
  lines.push(`Notes: ${notes.length} saved` + (notes.length
    ? ' — most recent: "' + notes[notes.length - 1].content + '"'
    : '.'));

  return lines.join('\n');
}

function showOfflineData() {
  const text = formatSnapshotForChat(getCachedSnapshot());
  if (typeof addMsg === 'function') {
    addMsg('fri', 'FRIDAY', text, { model: 'cached', ms: 0 });
  }
}

window.addEventListener('online', syncOfflineSnapshot);
window.addEventListener('load', syncOfflineSnapshot);
setInterval(syncOfflineSnapshot, SYNC_INTERVAL_MS);

window.FridayOfflineSync = { syncOfflineSnapshot, getCachedSnapshot, showOfflineData };
