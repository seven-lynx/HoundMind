// Map: the home map the dog builds, drawn from the `document` M1 puts on `GET /map` (#307).
//
// **Two frames, both correct, both called x/y — and the document's is not the runtime's.** A document
// point is `[x = left, y = forward]` (M plan section 5, `CONTROL_API.md`), which is what a person
// reading a plan expects, so this panel draws nose-up with no conversion: screen x = centre - x * scale
// (left is left), screen y = centre - y * scale (forward is up). The runtime speaks
// `(forward_cm, left_cm)` — the pose, the planner and the grid cells all do — so when this panel plots
// `localization.pose` it swaps once, through `runtime_point_to_document` on the server side (#347).
// That swap is why the dog here comes from `GET /map`'s `pose` (M5), not from `/state`: the panel
// keeps no second copy of the frame rule, and `document.dog` is only the fallback - the position last
// confirmed, not a pose.
//
// Four layers, each toggleable, because they answer different questions: cells are *evidence* (what
// the sonar hit), walls and openings are *claims* (drawn by a person or lifted from the scan), rooms
// and surfaces are *meaning*. Unknown ground is hatched and floor is solid: a single hit is a
// maybe, not a floor, and the two must not look the same.
//
// A truncated map says so, and a map with no cells says why it is empty - `grid_enabled: false` and
// "no sweep has filled a cell yet" are different problems.

import { api, errorText, fmt } from "../lib.js";

const VIEW_KEY = "houndmind.map.view";
const PAD = 18;
// A cell with this many hits or more is floor; fewer is "seen once", which is a maybe.
const FLOOR_HITS = 2;
const LAYERS = ["cells", "rooms", "walls", "surfaces"];
const SURFACE_HATCH = {
  hardwood: ["#c58b4a", "rgba(197, 139, 74, 0.18)"],
  carpet: ["#6f9bd1", "rgba(111, 155, 209, 0.20)"],
  tile: ["#8fb8a8", "rgba(143, 184, 168, 0.18)"],
  rug: ["#b98bc5", "rgba(185, 139, 197, 0.18)"],
  unknown: ["#8f8f8f", "rgba(143, 143, 143, 0.16)"],
};

// Rooms and surfaces (#308). The vocabulary is fixed because `step_scale` is what odometry reads: a
// paint the stepper does not know is a room that walks at the assumed length, silently.
const ROOM_COLOURS = [
  "rgba(120, 170, 220, 0.30)",
  "rgba(220, 180, 120, 0.30)",
  "rgba(150, 210, 160, 0.30)",
  "rgba(210, 150, 200, 0.30)",
  "rgba(180, 180, 230, 0.30)",
];
const MODES = ["view", "wall", "opening", "delete", "room", "surface", "pose", "go"];

function pointInPolygon(point, polygon) {
  // Ray casting: a click inside a lasso selects that room, and a boundary hit counts as inside.
  let inside = false;
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i, i += 1) {
    const [xi, yi] = polygon[i];
    const [xj, yj] = polygon[j];
    if (yi > point[1] !== yj > point[1] && point[0] < ((xj - xi) * (point[1] - yi)) / (yj - yi) + xi) {
      inside = !inside;
    }
  }
  return inside;
}

// Editing (#309): a wall is two centimetre points, an opening is a gap in one. Everything a person
// draws is snapped to 5 cm and magnets to an existing endpoint, because a wall that misses its
// neighbour by 2 cm is a hole the planner will happily route through.
const SNAP_CM = 5;
const MAGNET_CM = 15;
const MIN_WALL_CM = 20;
const HIT_PX = 12;

const snap = (value) => Math.round(value / SNAP_CM) * SNAP_CM;

function uid(prefix) {
  const random = Math.random().toString(36).slice(2, 8);
  return `${prefix}_${random}`;
}

function distanceToSegment(point, a, b) {
  const dx = b[0] - a[0];
  const dy = b[1] - a[1];
  const lengthSquared = dx * dx + dy * dy;
  if (lengthSquared === 0) return Math.hypot(point[0] - a[0], point[1] - a[1]);
  let t = ((point[0] - a[0]) * dx + (point[1] - a[1]) * dy) / lengthSquared;
  t = Math.max(0, Math.min(1, t));
  return Math.hypot(point[0] - (a[0] + t * dx), point[1] - (a[1] + t * dy));
}

function projectOnSegment(point, a, b) {
  const dx = b[0] - a[0];
  const dy = b[1] - a[1];
  const lengthSquared = dx * dx + dy * dy;
  if (lengthSquared === 0) return 0;
  return Math.max(0, Math.min(1, ((point[0] - a[0]) * dx + (point[1] - a[1]) * dy) / lengthSquared));
}

function pointAt(a, b, t) {
  return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];
}

function loadView() {
  try {
    const raw = localStorage.getItem(VIEW_KEY);
    const view = raw ? JSON.parse(raw) : null;
    if (view && Number.isFinite(view.scale) && view.scale > 0) return view;
  } catch (err) {
    /* a corrupt remembered view is not a reason to refuse to draw */
  }
  return null;
}

function saveView(view) {
  try {
    localStorage.setItem(VIEW_KEY, JSON.stringify(view));
  } catch (err) {
    /* private mode, a full quota: the map still draws, it just forgets where you were */
  }
}

function bounds(document) {
  let minX = Infinity;
  let maxX = -Infinity;
  let minY = Infinity;
  let maxY = -Infinity;
  const see = (x, y) => {
    if (!Number.isFinite(x) || !Number.isFinite(y)) return;
    if (x < minX) minX = x;
    if (x > maxX) maxX = x;
    if (y < minY) minY = y;
    if (y > maxY) maxY = y;
  };
  const cell = Number(document.cell_size_cm) || 10;
  for (const key of Object.keys(document.cells || {})) {
    const [ix, iy] = String(key).split(",").map(Number);
    // The document's frame: x is the map's left axis, y its forward axis (M plan section 5).
    see(ix * cell, iy * cell);
  }
  for (const list of [document.walls, document.rooms, document.surfaces]) {
    for (const item of list || []) {
      if (Array.isArray(item.a)) see(item.a[0], item.a[1]);
      if (Array.isArray(item.b)) see(item.b[0], item.b[1]);
      for (const point of item.polygon || []) {
        if (Array.isArray(point)) see(point[0], point[1]);
      }
    }
  }
  if (document.dog) see(document.dog.x_cm, document.dog.y_cm);
  if (!Number.isFinite(minX)) return { minX: -100, maxX: 100, minY: -100, maxY: 100 };
  return { minX, maxX, minY, maxY };
}

export const map = {
  id: "map",
  label: "Map",

  mount(root) {
    root.innerHTML = `
      <div class="card">
        <div class="row" style="justify-content:space-between">
          <h3 style="margin:0">Home map</h3>
          <div class="row">
            <span class="chip" id="mp-count">no map</span>
            <span class="chip" id="mp-rev">rev -</span>
            <span class="chip" id="mp-pose-tier">pose: -</span>
            <span class="chip" id="mp-route"></span>
            <span class="chip" id="mp-health">map: -</span>
          </div>
        </div>
        <div class="row" style="margin:.5rem 0;flex-wrap:wrap">
          <button id="mp-fit" class="tiny">Fit</button>
          <button id="mp-in" class="tiny">+</button>
          <button id="mp-out" class="tiny">-</button>
          ${LAYERS.map(
            (name) =>
              `<label class="tiny" style="margin:0"><input id="mp-layer-${name}" type="checkbox" checked style="width:auto;margin:0 .25rem 0 0">${name}</label>`
          ).join("")}
        </div>
        <canvas id="mp-canvas" width="720" height="460"
          style="width:100%;display:block;background:var(--ink-2);border-radius:8px;cursor:grab"></canvas>
        <div class="row" style="margin:.5rem 0;flex-wrap:wrap">
          <button id="mp-mode-view" class="tiny">View</button>
          <button id="mp-mode-wall" class="tiny">Wall</button>
          <button id="mp-mode-opening" class="tiny">Doorway</button>
          <button id="mp-mode-delete" class="tiny">Delete</button>
          <button id="mp-mode-room" class="tiny">Room</button>
          <button id="mp-mode-surface" class="tiny">Surface</button>
          <button id="mp-mode-pose" class="tiny">Pose</button>
          <button id="mp-mode-go" class="tiny">Go</button>
          <button id="mp-pose-confirm" class="tiny" disabled>Confirm position</button>
          <button id="mp-pose-cancel" class="tiny" disabled>Cancel</button>
          <button id="mp-send" class="tiny" disabled>Send route</button>
          <input id="mp-room-name" class="tiny" placeholder="room name" style="width:7.5rem">
          <select id="mp-surface" class="tiny">
            <option value="hardwood">hardwood</option>
            <option value="carpet">carpet</option>
            <option value="tile">tile</option>
            <option value="rug">rug</option>
            <option value="unknown">unknown</option>
          </select>
          <span class="chip" id="mp-surface-cm">not measured</span>
          <button id="mp-keepout" class="tiny">keep-out: -</button>
          <label class="tiny" style="margin:0">doorway width
            <input id="mp-opening-width" type="number" min="30" max="200" step="5" value="80"
              style="width:4.5rem;margin-left:.3rem">
          </label>
          <button id="mp-undo" class="tiny">Undo</button>
          <button id="mp-save" class="tiny">Save to device</button>
          <button id="mp-reload" class="tiny">Reload</button>
          <span class="chip" id="mp-dirty">saved</span>
        </div>
        <p class="hint" id="mp-note"></p>
        <p class="hint" id="mp-legend"></p>
        <p class="error" id="mp-error" role="alert"></p>
      </div>`;

    const canvas = root.querySelector("#mp-canvas");
    const count = root.querySelector("#mp-count");
    const rev = root.querySelector("#mp-rev");
    const note = root.querySelector("#mp-note");
    const legend = root.querySelector("#mp-legend");
    const error = root.querySelector("#mp-error");
    const poseChip = root.querySelector("#mp-pose-tier");
    const routeChip = root.querySelector("#mp-route");
    const confirmButton = root.querySelector("#mp-pose-confirm");
    const cancelButton = root.querySelector("#mp-pose-cancel");
    const sendButton = root.querySelector("#mp-send");
    const healthChip = root.querySelector("#mp-health");

    let view = loadView();
    let document_ = null;
    let layers = new Set(LAYERS);
    // Editing state (#309): `history` holds {walls, openings} snapshots, one per edit, so Undo is a
    // restore rather than an inverse operation nobody wrote down.
    let history = [];
    let mode = "view";
    let draft = null;
    let edited = false;
    // A lasso is the polygon being clicked out, `selected` is the room the keep-out button acts on.
    let lasso = null;
    let cursorPoint = null;
    let selected = null;
    let measured = {};
    // M5: the live pose exactly as `GET /map` publishes it - already in the document's frame - and the
    // ghost the user dragged. The ghost is separate on purpose: a finger on a canvas is not a
    // measurement, and a drop that was not confirmed must not move the origin the map is built on.
    let livePose = null;
    let ghost = null;
    // M6: the walk so far and what the map says about itself, both read from `GET /map`, plus the
    // route the user is looking at before it is sent. `preview` is the whole answer, refusal included:
    // a preview that is not `valid` is drawn as a reason, never as a route.
    let trail = [];
    let health = null;
    let preview = null;
    const dirty = root.querySelector("#mp-dirty");
    const widthInput = root.querySelector("#mp-opening-width");

    function markDirty(isDirty) {
      edited = Boolean(isDirty);
      dirty.textContent = edited ? "unsaved" : "saved";
    }

    function pushHistory() {
      if (!document_) return;
      // Every user section, not just the one this edit touched: Undo has to put back the document a
      // step ago, and a snapshot missing `rooms` would restore a wall and lose a room.
      history.push(
        JSON.stringify({
          walls: document_.walls || [],
          openings: document_.openings || [],
          rooms: document_.rooms || [],
          surfaces: document_.surfaces || [],
        })
      );
      if (history.length > 50) history.shift();
    }

    function undo() {
      if (!document_ || !history.length) return;
      const previous = JSON.parse(history.pop());
      document_.walls = previous.walls;
      document_.openings = previous.openings;
      document_.rooms = previous.rooms;
      document_.surfaces = previous.surfaces;
      // A snapshot restores the arrays, so an item the user had selected is gone: holding the old
      // object would leave the keep-out button acting on a room that is no longer in the document.
      selected = null;
      lasso = null;
      refreshKeepOut();
      markDirty(true);
      render();
    }

    function modeTo(next) {
      mode = next;
      draft = null;
      lasso = null;
      cursorPoint = null;
      // Leaving Pose drops an unconfirmed ghost: it is a proposal, and a proposal that survived a
      // mode change would be confirmed later by a click the user meant for something else.
      if (next !== "pose") ghost = null;
      // A preview belongs to `Go` for the same reason: it is a route nobody asked for yet.
      if (next !== "go") preview = null;
      for (const name of MODES) {
        const button = root.querySelector(`#mp-mode-${name}`);
        if (button) button.classList.toggle("active", name === next);
      }
      canvas.style.cursor = next === "view" ? "grab" : "crosshair";
      refreshPoseButtons();
      refreshSend();
      render();
    }

    const roomName = root.querySelector("#mp-room-name");
    const surfacePick = root.querySelector("#mp-surface");
    const surfaceCm = root.querySelector("#mp-surface-cm");
    const keepOutButton = root.querySelector("#mp-keepout");

    function refreshSurface() {
      const value = measured[surfacePick.value];
      surfaceCm.textContent = Number.isFinite(value) ? `${value} cm measured` : "not measured";
    }

    function refreshKeepOut() {
      const room = selected && selected.kind === "room" ? selected.item : null;
      keepOutButton.disabled = !room;
      keepOutButton.textContent = `keep-out: ${room ? (room.keep_out ? "on" : "off") : "-"}`;
    }

    function refreshPoseButtons() {
      // Confirm only means something with a ghost on the map, and only in Pose: anywhere else the
      // button would be a second way to do something the mode does not offer.
      confirmButton.disabled = !(mode === "pose" && ghost);
      cancelButton.disabled = !ghost;
    }

    function refreshSend() {
      // Send is enabled by a *valid* preview and nothing else: a refused route has no goal to send,
      // and one that was never previewed is a click the dog was never shown.
      sendButton.disabled = !(mode === "go" && preview && preview.valid === true);
    }

    function agoText(seconds) {
      const value = Number(seconds);
      if (!Number.isFinite(value) || value < 0) return "-";
      if (value < 90) return `${Math.round(value)}s`;
      if (value < 5400) return `${Math.round(value / 60)}m`;
      return `${Math.round(value / 3600)}h`;
    }

    function refreshHealth() {
      // The badge is the map's own account of itself: whether the file was read, how long ago, which
      // stride the walk is measured in, and anything the loader could not take at face value.
      if (!health) {
        healthChip.textContent = "map: -";
        healthChip.title = "";
        return;
      }
      const loaded = health.loaded ? "loaded" : "not loaded";
      const when = Number.isFinite(Number(health.loaded_at))
        ? ` ${agoText(Date.now() / 1000 - Number(health.loaded_at))} ago`
        : "";
      const stride = health.step_cm_source || "assumed";
      const conflicts = (health.conflicts || []).length;
      healthChip.textContent = `map: ${loaded}${when} · stride ${stride} · ${conflicts} conflict${
        conflicts === 1 ? "" : "s"
      }`;
      const details = []
        .concat(health.conflicts || [], health.notes || [])
        .filter(Boolean);
      healthChip.title = details.length ? details.join("; ") : String(health.reason || "");
    }

    function toggleKeepOut() {
      const room = selected && selected.kind === "room" ? selected.item : null;
      if (!room) return;
      pushHistory();
      room.keep_out = !room.keep_out;
      markDirty(true);
      refreshKeepOut();
      render();
    }

    function roomUnder(point) {
      for (const room of (document_ && document_.rooms) || []) {
        const polygon = room.polygon || [];
        if (polygon.length >= 3 && pointInPolygon(point, polygon)) return room;
      }
      return null;
    }

    function surfaceUnder(point) {
      for (const surface of (document_ && document_.surfaces) || []) {
        const polygon = surface.polygon || [];
        if (polygon.length >= 3 && pointInPolygon(point, polygon)) return surface;
      }
      return null;
    }

    function addLassoPoint(point) {
      const next = snapped(point, null, false);
      if (!lasso) lasso = [];
      if (lasso.length >= 3) {
        const [first] = lasso;
        // Clicking back on the first corner closes the polygon: there is no button to forget to press
        // and no half-drawn room left behind when the tab is closed.
        if (Math.hypot(next[0] - first[0], next[1] - first[1]) <= MAGNET_CM) {
          closeLasso();
          return;
        }
      }
      lasso = [...lasso, next];
      // Unsaved from the first corner: an open lasso is work, and the poll must not replace it.
      markDirty(true);
      render();
    }

    function closeLasso() {
      if (!lasso || lasso.length < 3) return;
      const polygon = lasso;
      lasso = null;
      cursorPoint = null;
      if (mode === "surface") {
        const key = surfacePick.value;
        pushHistory();
        document_.surfaces = [
          ...(document_.surfaces || []),
          { id: uid("surf"), name: key, step_scale: key, polygon },
        ];
        error.textContent = "";
        markDirty(true);
        render();
        return;
      }
      const count = (document_.rooms || []).length;
      const name = (roomName.value || "").trim() || `Room ${count + 1}`;
      const room = {
        id: uid("room"),
        name,
        polygon,
        colour: ROOM_COLOURS[count % ROOM_COLOURS.length],
        keep_out: false,
      };
      pushHistory();
      document_.rooms = [...(document_.rooms || []), room];
      selected = { kind: "room", item: room };
      roomName.value = "";
      error.textContent = "";
      markDirty(true);
      refreshKeepOut();
      render();
    }

    function docPoint(event) {
      const rect = canvas.getBoundingClientRect();
      const px = ((event.clientX - rect.left) * canvas.width) / Math.max(rect.width, 1);
      const py = ((event.clientY - rect.top) * canvas.height) / Math.max(rect.height, 1);
      return [
        (canvas.width / 2 - px) / view.scale + (view.cx || 0),
        (canvas.height / 2 - py) / view.scale + (view.cy || 0),
      ];
    }

    function magnet(point) {
      // Endpoint magnetism: a wall that ends 2 cm from its neighbour leaves a gap the planner will
      // happily walk through, so an existing endpoint within MAGNET_CM wins over the snap grid.
      let best = null;
      let bestDistance = MAGNET_CM;
      for (const wall of (document_ && document_.walls) || []) {
        for (const end of [wall.a, wall.b]) {
          if (!Array.isArray(end)) continue;
          const distance = Math.hypot(point[0] - end[0], point[1] - end[1]);
          if (distance < bestDistance) {
            best = [end[0], end[1]];
            bestDistance = distance;
          }
        }
      }
      return best;
    }

    function snapped(point, anchor, shiftKey) {
      let [x, y] = point;
      if (shiftKey && anchor) {
        // Shift constrains to the axis the drag is longer on: walls are usually straight.
        if (Math.abs(x - anchor[0]) >= Math.abs(y - anchor[1])) y = anchor[1];
        else x = anchor[0];
      }
      const magneted = magnet([x, y]);
      return magneted || [snap(x), snap(y)];
    }

    function nearestSegment(point, toleranceCm) {
      let best = null;
      let bestDistance = toleranceCm;
      for (const opening of (document_ && document_.openings) || []) {
        if (!Array.isArray(opening.a) || !Array.isArray(opening.b)) continue;
        const distance = distanceToSegment(point, opening.a, opening.b);
        if (distance < bestDistance) {
          best = { kind: "opening", item: opening };
          bestDistance = distance;
        }
      }
      for (const wall of (document_ && document_.walls) || []) {
        if (!Array.isArray(wall.a) || !Array.isArray(wall.b)) continue;
        const distance = distanceToSegment(point, wall.a, wall.b);
        if (distance < bestDistance) {
          best = { kind: "wall", item: wall };
          bestDistance = distance;
        }
      }
      return best;
    }

    function commitWall(a, b) {
      const length = Math.hypot(b[0] - a[0], b[1] - a[1]);
      if (length < MIN_WALL_CM) {
        error.textContent = `a wall shorter than ${MIN_WALL_CM} cm is a dot, not a wall`;
        return;
      }
      pushHistory();
      document_.walls = [
        ...(document_.walls || []),
        { id: uid("wall"), a: [a[0], a[1]], b: [b[0], b[1]], source: "user" },
      ];
      error.textContent = "";
      markDirty(true);
      render();
    }

    function cutOpening(point) {
      const width = Math.max(10, Number(widthInput.value) || 80);
      let target = null;
      let best = (HIT_PX + 4) / view.scale;
      for (const wall of (document_ && document_.walls) || []) {
        if (!Array.isArray(wall.a) || !Array.isArray(wall.b)) continue;
        const distance = distanceToSegment(point, wall.a, wall.b);
        if (distance < best) {
          best = distance;
          target = wall;
        }
      }
      if (!target) {
        error.textContent = "click a wall to cut a doorway through it";
        return;
      }
      const length = Math.hypot(target.b[0] - target.a[0], target.b[1] - target.a[1]);
      if (length < width + 10) {
        error.textContent = `that wall is ${length.toFixed(0)} cm; a ${width} cm doorway does not fit`;
        return;
      }
      const t = projectOnSegment(point, target.a, target.b);
      const half = width / 2 / length;
      // Keep the gap inside its own wall: a doorway that overhangs is a tear, not an opening.
      const from = Math.max(0, t - half);
      const to = Math.min(1, t + half);
      pushHistory();
      document_.openings = [
        ...(document_.openings || []),
        {
          id: uid("door"),
          a: pointAt(target.a, target.b, from),
          b: pointAt(target.a, target.b, to),
          width_cm: Math.round(width),
          kind: "door",
        },
      ];
      error.textContent = "";
      markDirty(true);
      render();
    }

    function deleteAt(point) {
      const room = roomUnder(point);
      if (room) {
        pushHistory();
        document_.rooms = (document_.rooms || []).filter((item) => item !== room);
        if (selected && selected.item === room) selected = null;
        refreshKeepOut();
        markDirty(true);
        render();
        return;
      }
      const surface = surfaceUnder(point);
      if (surface) {
        pushHistory();
        document_.surfaces = (document_.surfaces || []).filter((item) => item !== surface);
        markDirty(true);
        render();
        return;
      }
      const hit = nearestSegment(point, (HIT_PX + 4) / view.scale);
      if (!hit) return;
      pushHistory();
      if (hit.kind === "opening") {
        document_.openings = (document_.openings || []).filter((item) => item !== hit.item);
      } else {
        document_.walls = (document_.walls || []).filter((item) => item !== hit.item);
      }
      markDirty(true);
      render();
    }

    async function save() {
      if (!document_) return;
      error.textContent = "";
      try {
        const answer = await api("/map", {
          method: "PUT",
          body: JSON.stringify({
            document: {
              ...document_,
              walls: document_.walls || [],
              openings: document_.openings || [],
            },
          }),
        });
        // Publish what the device wrote: the rev it returns is the one the next save must send.
        if (answer && answer.document) {
          document_ = answer.document;
          describe(document_);
        }
        markDirty(false);
        history = [];
        render();
      } catch (err) {
        const payload = err.payload || {};
        if (payload.problems && payload.problems.length) {
          error.textContent = `${err.message}: ${payload.problems.join("; ")}`;
        } else if (err.status === 409) {
          error.textContent =
            "the map changed since this copy was read - press Reload and redo the edit";
        } else {
          error.textContent = errorText(err);
        }
      }
    }


    async function previewRoute(point) {
      error.textContent = "";
      note.textContent = "";
      try {
        const answer = await api("/map/preview", {
          method: "POST",
          body: JSON.stringify({ x_cm: point[0], y_cm: point[1] }),
        });
        preview = answer && typeof answer === "object" ? answer : null;
        if (preview && preview.valid === true) {
          const count = (preview.waypoints || []).length;
          note.textContent = `${fmt(preview.distance_cm, "cm")} to walk · ${count} waypoint${
            count === 1 ? "" : "s"
          } · Send route to start${preview.note ? ` · ${preview.note}` : ""}`;
        } else if (preview) {
          // The refusal is the whole answer here, and it is already named: `goal_in_keep_out` is the
          // room the user drew, not a failure of the click.
          error.textContent = `${preview.refusal || "refused"}: ${preview.detail || "no route"}`;
        }
      } catch (err) {
        preview = null;
        const payload = err.payload || {};
        error.textContent = payload.detail
          ? `${payload.error || "refused"}: ${payload.detail}`
          : errorText(err);
      }
      refreshSend();
      render();
    }

    async function goTo(point) {
      error.textContent = "";
      try {
        await api("/map/go", {
          method: "POST",
          body: JSON.stringify({ x_cm: point[0], y_cm: point[1] }),
        });
        note.textContent = "route requested: the dog plans it on the next tick";
        // The preview has been spent: keeping it would leave a route drawn that the follower has
        // already planned, and a `Send` that would ask for it twice.
        preview = null;
        refreshSend();
        render();
      } catch (err) {
        const payload = err.payload || {};
        // The 409 bodies carry the reason a client would otherwise have to infer from nothing
        // happening: `no_pose` means "correct the position first", not "try again".
        error.textContent = payload.detail
          ? `${payload.error || "refused"}: ${payload.detail}`
          : errorText(err);
      }
    }

    async function confirmPose() {
      if (!ghost || !document_) return;
      error.textContent = "";
      // Only a heading the dog actually reported is sent. With no pose there is no compass reading,
      // and writing 0 would claim the dog faces forward on the strength of a drag.
      const heading = livePose === null ? null : Number(livePose.heading_deg);
      const body = { x_cm: ghost.x, y_cm: ghost.y };
      if (heading !== null && Number.isFinite(heading)) body.heading_deg = heading;
      try {
        const answer = await api("/map/pose", { method: "PUT", body: JSON.stringify(body) });
        // Adopt `dog` and `rev` only. The rest of this tree may hold unsaved edits, and replacing it
        // with the server's copy is exactly the edit-losing refresh `load()` refuses to be.
        if (answer && answer.dog) {
          document_.dog = answer.dog;
          const stored = Number(answer.dog.heading_deg);
          livePose = {
            x_cm: answer.dog.x_cm,
            y_cm: answer.dog.y_cm,
            // Local marker only: the next `GET /map` replaces this with the device's own pose.
            heading_deg: Number.isFinite(stored) ? stored : 0,
            tier: "user",
          };
        }
        if (answer && answer.rev != null && document_.meta) document_.meta.rev = answer.rev;
        ghost = null;
        modeTo("view");
      } catch (err) {
        error.textContent = errorText(err);
      }
    }


    const toScreen = (x, y) => [canvas.width / 2 - x * view.scale, canvas.height / 2 - y * view.scale];

    function fit(document) {
      const box = bounds(document);
      const spanX = Math.max(box.maxX - box.minX, 40);
      const spanY = Math.max(box.maxY - box.minY, 40);
      const scale = Math.min(
        (canvas.width - PAD * 2) / spanX,
        (canvas.height - PAD * 2) / spanY
      );
      view = { scale, cx: (box.minX + box.maxX) / 2, cy: (box.minY + box.maxY) / 2 };
      saveView(view);
    }

    const screen = (x, y) => toScreen(x - (view.cx || 0), y - (view.cy || 0));


    // ---- the layers ---------------------------------------------------------

    function hatch(ctx, polygon, colour) {
      ctx.save();
      ctx.beginPath();
      polygon.forEach(([x, y], index) => {
        const [sx, sy] = screen(x, y);
        if (index === 0) ctx.moveTo(sx, sy);
        else ctx.lineTo(sx, sy);
      });
      ctx.closePath();
      ctx.fillStyle = colour;
      ctx.fill();
      ctx.clip();
      ctx.strokeStyle = colour;
      ctx.lineWidth = 1;
      ctx.globalAlpha = 0.6;
      for (let offset = -canvas.height; offset < canvas.width; offset += 9) {
        ctx.beginPath();
        ctx.moveTo(offset, 0);
        ctx.lineTo(offset + canvas.height, canvas.height);
        ctx.stroke();
      }
      ctx.restore();
    }

    function drawSurfaces(ctx) {
      for (const surface of document_.surfaces || []) {
        const polygon = surface.polygon || [];
        if (polygon.length < 3) continue;
        const [stroke, fill] = SURFACE_HATCH[surface.step_scale] || SURFACE_HATCH.unknown;
        hatch(ctx, polygon, fill);
        const centre = polygonCentre(polygon);
        const [sx, sy] = screen(centre[0], centre[1]);
        ctx.fillStyle = stroke;
        ctx.font = "11px ui-monospace, monospace";
        ctx.textAlign = "center";
        ctx.fillText(surface.name || "surface", sx, sy);
      }
    }

    function drawRooms(ctx) {
      for (const room of document_.rooms || []) {
        const polygon = room.polygon || [];
        if (polygon.length < 3) continue;
        ctx.beginPath();
        polygon.forEach(([x, y], index) => {
          const [sx, sy] = screen(x, y);
          if (index === 0) ctx.moveTo(sx, sy);
          else ctx.lineTo(sx, sy);
        });
        ctx.closePath();
        ctx.fillStyle = room.colour || "rgba(120, 170, 220, 0.18)";
        ctx.fill();
        ctx.strokeStyle = room.keep_out ? "#e46a6a" : "rgba(233, 238, 243, 0.35)";
        ctx.lineWidth = room.keep_out ? 2 : 1;
        ctx.setLineDash(room.keep_out ? [6, 4] : []);
        ctx.stroke();
        ctx.setLineDash([]);
        const centre = polygonCentre(polygon);
        const [sx, sy] = screen(centre[0], centre[1]);
        ctx.fillStyle = "#e9eef3";
        ctx.font = "600 12px ui-sans-serif, system-ui";
        ctx.textAlign = "center";
        ctx.fillText(room.name || "room", sx, sy);
        if (room.keep_out) {
          ctx.font = "10px ui-sans-serif, system-ui";
          ctx.fillText("keep out", sx, sy + 12);
        }
      }
    }

    function drawCells(ctx) {
      const cell = Number(document_.cell_size_cm) || 10;
      const entries = Object.entries(document_.cells || {});
      if (!entries.length) return;
      const side = Math.max(cell * view.scale, 1);
      for (const [key, hitsRaw] of entries) {
        const [ix, iy] = key.split(",").map(Number);
        if (!Number.isFinite(ix) || !Number.isFinite(iy)) continue;
        const hits = Number(hitsRaw) || 0;
        const [sx, sy] = screen(ix * cell, iy * cell);
        if (hits >= FLOOR_HITS) {
          ctx.fillStyle = `rgba(240, 165, 58, ${(0.3 + 0.5 * Math.min(1, hits / 6)).toFixed(2)})`;
          ctx.fillRect(sx - side / 2, sy - side / 2, side, side);
        } else {
          // Seen once: a maybe, not a floor. Drawn as an outline so it never reads as surface.
          ctx.strokeStyle = "rgba(240, 165, 58, 0.55)";
          ctx.lineWidth = 1;
          ctx.strokeRect(sx - side / 2, sy - side / 2, side, side);
        }
      }
    }

    function drawWalls(ctx) {
      ctx.strokeStyle = "#e9eef3";
      ctx.lineCap = "round";
      for (const wall of document_.walls || []) {
        if (!Array.isArray(wall.a) || !Array.isArray(wall.b)) continue;
        const [ax, ay] = screen(wall.a[0], wall.a[1]);
        const [bx, by] = screen(wall.b[0], wall.b[1]);
        ctx.lineWidth = 2.5;
        ctx.strokeStyle = wall.source === "scan" ? "rgba(233, 238, 243, 0.55)" : "#e9eef3";
        ctx.beginPath();
        ctx.moveTo(ax, ay);
        ctx.lineTo(bx, by);
        ctx.stroke();
      }
    }

    function drawOpenings(ctx) {
      // An opening is drawn as a break in its wall, which is what a person means by a doorway.
      for (const opening of document_.openings || []) {
        if (!Array.isArray(opening.a) || !Array.isArray(opening.b)) continue;
        const [ax, ay] = screen(opening.a[0], opening.a[1]);
        const [bx, by] = screen(opening.b[0], opening.b[1]);
        ctx.strokeStyle = "#0f1418";
        ctx.lineWidth = 5;
        ctx.beginPath();
        ctx.moveTo(ax, ay);
        ctx.lineTo(bx, by);
        ctx.stroke();
        ctx.fillStyle = "#8fb8a8";
        for (const [px, py] of [
          [ax, ay],
          [bx, by],
        ]) {
          ctx.beginPath();
          ctx.arc(px, py, 2.5, 0, Math.PI * 2);
          ctx.fill();
        }
      }
    }


    function drawTrail(ctx) {
      // Behind everything and faint: a breadcrumb is context for where the dog is, not a feature of its
      // own. Drawn from `GET /map`'s `trail`, which the device already swapped into this frame (#347).
      if (!trail.length) return;
      ctx.save();
      ctx.strokeStyle = "rgba(122, 214, 122, 0.4)";
      ctx.lineWidth = 1.5;
      ctx.setLineDash([3, 3]);
      ctx.beginPath();
      trail.forEach((point, index) => {
        const [sx, sy] = screen(Number(point[0]) || 0, Number(point[1]) || 0);
        if (index === 0) ctx.moveTo(sx, sy);
        else ctx.lineTo(sx, sy);
      });
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = "rgba(122, 214, 122, 0.45)";
      for (const point of trail.slice(-20)) {
        const [sx, sy] = screen(Number(point[0]) || 0, Number(point[1]) || 0);
        ctx.beginPath();
        ctx.arc(sx, sy, 1.6, 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.restore();
    }

    function drawPreview(ctx) {
      // A refusal is a cross where the walk was asked for, never a route: drawing a line the dog will
      // not follow is how a client says "yes" to the user and "no" to the dog.
      if (!preview) return;
      const goal = preview.goal_cm;
      const [gx, gy] = goal
        ? screen(Number(goal.x_cm) || 0, Number(goal.y_cm) || 0)
        : [0, 0];
      if (preview.valid !== true) {
        if (!goal) return;
        ctx.save();
        ctx.strokeStyle = "#e46a6a";
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.moveTo(gx - 6, gy - 6);
        ctx.lineTo(gx + 6, gy + 6);
        ctx.moveTo(gx + 6, gy - 6);
        ctx.lineTo(gx - 6, gy + 6);
        ctx.stroke();
        ctx.restore();
        return;
      }
      const waypoints = preview.waypoints || [];
      ctx.save();
      ctx.strokeStyle = "#8fb8a8";
      ctx.lineWidth = 2;
      ctx.setLineDash([6, 4]);
      ctx.beginPath();
      [goal, ...waypoints].filter(Boolean).forEach((point, index) => {
        const [sx, sy] = screen(Number(point.x_cm) || 0, Number(point.y_cm) || 0);
        if (index === 0) ctx.moveTo(sx, sy);
        else ctx.lineTo(sx, sy);
      });
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = "#8fb8a8";
      for (const point of waypoints) {
        const [sx, sy] = screen(Number(point.x_cm) || 0, Number(point.y_cm) || 0);
        ctx.beginPath();
        ctx.arc(sx, sy, 2.5, 0, Math.PI * 2);
        ctx.fill();
      }
      if (goal) {
        ctx.strokeStyle = "#8fb8a8";
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.arc(gx, gy, 6, 0, Math.PI * 2);
        ctx.stroke();
        ctx.fillStyle = "#e9eef3";
        ctx.font = "11px ui-monospace, monospace";
        ctx.textAlign = "center";
        ctx.fillText(fmt(preview.distance_cm, "cm"), gx, gy - 11);
      }
      ctx.restore();
    }

    function drawDog(ctx) {
      // The live pose first: it is the runtime's answer, already swapped into this frame by
      // `GET /map`. `document.dog` is the fallback and answers a different question - where the dog
      // was last *confirmed* - so it is drawn only when there is no pose to draw.
      const dog = livePose || document_.dog;
      if (!dog) return;
      const [sx, sy] = screen(Number(dog.x_cm) || 0, Number(dog.y_cm) || 0);
      // Screen y is up-negative, so a forward heading of 0 points up rather than down.
      const angle = -((Number(dog.heading_deg) || 0) * Math.PI) / 180;
      ctx.save();
      ctx.translate(sx, sy);
      ctx.rotate(angle);
      ctx.fillStyle = "#7ad67a";
      ctx.beginPath();
      ctx.moveTo(0, -9);
      ctx.lineTo(6, 7);
      ctx.lineTo(0, 4);
      ctx.lineTo(-6, 7);
      ctx.closePath();
      ctx.fill();
      ctx.restore();
    }

    function drawGhost(ctx) {
      // What the user is about to claim, drawn as a claim: an open ring, not a dog. Confirm turns it
      // into the dog; nothing else does.
      if (!ghost) return;
      const [sx, sy] = screen(ghost.x, ghost.y);
      ctx.save();
      ctx.strokeStyle = "#f0c060";
      ctx.setLineDash([4, 3]);
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.arc(sx, sy, 9, 0, Math.PI * 2);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.font = "10px ui-monospace, monospace";
      ctx.fillStyle = "#f0c060";
      ctx.textAlign = "center";
      ctx.fillText("confirm?", sx, sy - 13);
      ctx.restore();
    }

    function drawScale(ctx) {
      // A bar that is a round number of metres at the current zoom, and never wider than a third.
      const metres = [0.5, 1, 2, 5, 10, 20, 50].find(
        (value) => value * 100 * view.scale < canvas.width / 3
      ) || 0.5;
      const width = metres * 100 * view.scale;
      const y = canvas.height - 14;
      ctx.strokeStyle = "#8fa0b0";
      ctx.fillStyle = "#8fa0b0";
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.moveTo(12, y);
      ctx.lineTo(12 + width, y);
      ctx.moveTo(12, y - 4);
      ctx.lineTo(12, y + 4);
      ctx.moveTo(12 + width, y - 4);
      ctx.lineTo(12 + width, y + 4);
      ctx.stroke();
      ctx.font = "11px ui-monospace, monospace";
      ctx.textAlign = "left";
      ctx.fillText(metres < 1 ? `${metres * 100} cm` : `${metres} m`, 12, y - 8);
    }

    function drawDraft(ctx) {
      if (!draft || !draft.b) return;
      const [ax, ay] = screen(draft.a[0], draft.a[1]);
      const [bx, by] = screen(draft.b[0], draft.b[1]);
      ctx.save();
      ctx.setLineDash([6, 4]);
      ctx.strokeStyle = "#7ad67a";
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(ax, ay);
      ctx.lineTo(bx, by);
      ctx.stroke();
      ctx.restore();
    }

    function drawLasso(ctx) {
      if (!lasso || !lasso.length) return;
      ctx.save();
      ctx.strokeStyle = "#f0c060";
      ctx.fillStyle = "rgba(240, 192, 96, 0.12)";
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      lasso.forEach(([x, y], index) => {
        const [sx, sy] = screen(x, y);
        if (index === 0) ctx.moveTo(sx, sy);
        else ctx.lineTo(sx, sy);
      });
      if (cursorPoint) {
        const [sx, sy] = screen(cursorPoint[0], cursorPoint[1]);
        ctx.lineTo(sx, sy);
      }
      // Three corners or more is a polygon the next click can close, so it gets the fill early: the
      // shape reads as a room before the user commits to it.
      if (lasso.length >= 3) {
        ctx.closePath();
        ctx.fill();
      }
      ctx.stroke();
      ctx.restore();
    }

    function drawSelection(ctx) {
      const polygon = (selected && selected.item && selected.item.polygon) || [];
      if (polygon.length < 3) return;
      ctx.save();
      ctx.strokeStyle = "#f0c060";
      ctx.lineWidth = 2;
      ctx.setLineDash([]);
      ctx.beginPath();
      polygon.forEach(([x, y], index) => {
        const [sx, sy] = screen(x, y);
        if (index === 0) ctx.moveTo(sx, sy);
        else ctx.lineTo(sx, sy);
      });
      ctx.closePath();
      ctx.stroke();
      ctx.restore();
    }

    function polygonCentre(polygon) {
      let x = 0;
      let y = 0;
      for (const point of polygon) {
        x += point[0];
        y += point[1];
      }
      return [x / polygon.length, y / polygon.length];
    }

    function render() {
      const ctx = canvas.getContext("2d");
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      if (!document_ || !view) return;
      // The walk is context for everything else, so it is drawn first and faintest (M6).
      drawTrail(ctx);
      // Meaning underneath evidence: a room is context for the cells drawn on top of it.
      if (layers.has("surfaces")) drawSurfaces(ctx);
      if (layers.has("rooms")) drawRooms(ctx);
      if (layers.has("cells")) drawCells(ctx);
      if (layers.has("walls")) {
        drawWalls(ctx);
        drawOpenings(ctx);
      }
      drawDraft(ctx);
      drawLasso(ctx);
      drawSelection(ctx);
      drawPreview(ctx);
      drawDog(ctx);
      drawGhost(ctx);
      drawScale(ctx);
    }

    function describe(document) {
      const cells = Object.keys(document.cells || {}).length;
      rev.textContent = `rev ${document.meta && document.meta.rev ? document.meta.rev : "-"}`;
      if (!cells && !(document.walls || []).length && !(document.rooms || []).length) {
        count.textContent = "no map";
        note.textContent =
          document.meta && document.meta.source === "scan"
            ? "no sweep has filled a cell yet"
            : "this document carries no cells, walls or rooms yet";
        legend.textContent = "";
        return;
      }
      count.textContent = `${cells} cell${cells === 1 ? "" : "s"}`;
      const stepSource = (document.meta && document.meta.step_cm_source) || "assumed";
      note.textContent = `one square is ${fmt(
        document.cell_size_cm,
        "cm"
      )}, nose up; stride ${stepSource}. Solid squares are floor, outlines are seen once.`;
      legend.textContent = `walls ${(document.walls || []).length} · openings ${
        (document.openings || []).length
      } · rooms ${(document.rooms || []).length} · surfaces ${(document.surfaces || []).length}`;
    }

    async function load() {
      error.textContent = "";
      try {
        const payload = await api("/map");
        const incoming = payload && payload.document ? payload.document : null;
        // A copy, not the payload: every edit mutates this tree, and a poll must never merge a
        // half-finished edit into a fresh document.
        document_ = incoming ? JSON.parse(JSON.stringify(incoming)) : null;
        // The measured step per surface rides beside the document (M4): the panel cannot read the
        // config, and a vocabulary offered without its values behind it is a menu that lies.
        measured =
          payload && payload.surface_step_cm && typeof payload.surface_step_cm === "object"
            ? payload.surface_step_cm
            : {};
        // M5: the runtime's pose, swapped into this frame by the route, or null when the dog cannot
        // place itself - in which case the last confirmed `document.dog` is still worth drawing.
        livePose = payload && payload.pose ? payload.pose : null;
        // M6: the walk and the map's own account of itself. Neither is editable, so the poll may
        // replace them mid-edit - unlike the document, which it refuses to touch while dirty.
        trail = payload && Array.isArray(payload.trail) ? payload.trail : [];
        health =
          payload && payload.health && typeof payload.health === "object" ? payload.health : null;
        preview = null;
        history = [];
        draft = null;
        lasso = null;
        selected = null;
        refreshSurface();
        refreshKeepOut();
        refreshHealth();
        refreshSend();
        markDirty(false);
        if (!document_) {
          count.textContent = "no document";
          note.textContent = "the device answered without a map document";
          legend.textContent = "";
          return;
        }
        describe(document_);
        // A remembered view survives a reload; a first visit fits the map to the canvas.
        if (!view) fit(document_);
        render();
      } catch (err) {
        error.textContent = errorText(err);
        count.textContent = "no map";
        note.textContent = "";
        legend.textContent = "";
      }
    }


    // ---- interaction --------------------------------------------------------

    function zoom(factor) {
      if (!view) return;
      view = { ...view, scale: Math.min(20, Math.max(0.02, view.scale * factor)) };
      saveView(view);
      render();
    }

    root.querySelector("#mp-fit").addEventListener("click", () => {
      if (!document_) return;
      fit(document_);
      render();
    });
    root.querySelector("#mp-in").addEventListener("click", () => zoom(1.3));
    root.querySelector("#mp-out").addEventListener("click", () => zoom(1 / 1.3));

    for (const name of MODES) {
      root.querySelector(`#mp-mode-${name}`).addEventListener("click", () => modeTo(name));
    }
    root.querySelector("#mp-undo").addEventListener("click", undo);
    root.querySelector("#mp-save").addEventListener("click", save);
    root.querySelector("#mp-reload").addEventListener("click", () => load());
    root.querySelector("#mp-keepout").addEventListener("click", toggleKeepOut);
    confirmButton.addEventListener("click", confirmPose);
    cancelButton.addEventListener("click", () => {
      ghost = null;
      refreshPoseButtons();
      render();
    });
    sendButton.addEventListener("click", () => {
      // Only a valid preview has something to send; `refreshSend` is what keeps the button honest.
      if (!preview || preview.valid !== true || !preview.goal_cm) return;
      goTo([Number(preview.goal_cm.x_cm) || 0, Number(preview.goal_cm.y_cm) || 0]);
    });
    surfacePick.addEventListener("change", refreshSurface);

    for (const name of LAYERS) {
      const box = root.querySelector(`#mp-layer-${name}`);
      box.checked = layers.has(name);
      box.addEventListener("change", () => {
        if (box.checked) layers.add(name);
        else layers.delete(name);
        render();
      });
    }

    // Drag to pan in View; drag to draw in Wall; click to cut or delete. One handler, four modes,
    // because a canvas that switches behaviour by mode is easier to trust than three overlapping
    // listeners that all have to guess which one the user meant.
    let dragging = null;
    let dogDragging = false;
    canvas.addEventListener("pointerdown", (event) => {
      if (!document_) return;
      const point = docPoint(event);
      if (mode === "pose") {
        // Dragging *proposes* a position. Confirm is a separate act (`confirmPose`), because a finger
        // on a canvas is not a measurement and a mis-drop must not move the map's origin.
        ghost = { x: point[0], y: point[1] };
        dogDragging = true;
        canvas.setPointerCapture(event.pointerId);
        refreshPoseButtons();
        render();
        return;
      }
      if (mode === "go") {
        // Preview first, walk second: the user sees the route and its distance before the dog does.
        previewRoute(point);
        return;
      }
      if (mode === "wall") {
        const start = snapped(point, null, false);
        draft = { a: start, b: start };
        canvas.setPointerCapture(event.pointerId);
        return;
      }
      if (mode === "opening") {
        cutOpening(point);
        return;
      }
      if (mode === "delete") {
        deleteAt(point);
        return;
      }
      if (mode === "room" || mode === "surface") {
        addLassoPoint(point);
        return;
      }
      canvas.setPointerCapture(event.pointerId);
      canvas.style.cursor = "grabbing";
      dragging = { x: event.clientX, y: event.clientY, view: { ...(view || {}) }, moved: false };
    });

    canvas.addEventListener("pointermove", (event) => {
      if (!document_) return;
      if (mode === "pose" && dogDragging && ghost) {
        const point = docPoint(event);
        ghost = { x: point[0], y: point[1] };
        render();
        return;
      }
      if (mode === "wall" && draft) {
        draft = { a: draft.a, b: snapped(docPoint(event), draft.a, event.shiftKey) };
        render();
        return;
      }
      if ((mode === "room" || mode === "surface") && lasso) {
        cursorPoint = snapped(docPoint(event), null, false);
        render();
        return;
      }
      if (!dragging || !view) return;
      const dx = event.clientX - dragging.x;
      const dy = event.clientY - dragging.y;
      if (Math.abs(dx) + Math.abs(dy) > 3) dragging.moved = true;
      view = {
        ...view,
        cx: (dragging.view.cx || 0) + dx / view.scale,
        cy: (dragging.view.cy || 0) + dy / view.scale,
      };
      render();
    });

    const endDrag = (event) => {
      dogDragging = false;
      if (mode === "wall" && draft) {
        const start = draft.a;
        const end = draft.b || start;
        draft = null;
        commitWall(start, end);
        return;
      }
      if (!dragging) return;
      const wasClick = !dragging.moved;
      dragging = null;
      canvas.style.cursor = mode === "view" ? "grab" : "crosshair";
      if (view) saveView(view);
      // A click that did not pan is a selection: that is how the keep-out button learns which room
      // it is about, without a second list of rooms to keep in sync.
      if (wasClick && mode === "view") {
        const room = roomUnder(docPoint(event));
        selected = room ? { kind: "room", item: room } : null;
        refreshKeepOut();
        render();
      }
    };
    canvas.addEventListener("pointerup", endDrag);
    canvas.addEventListener("pointercancel", endDrag);
    canvas.addEventListener(
      "wheel",
      (event) => {
        event.preventDefault();
        zoom(event.deltaY < 0 ? 1.1 : 1 / 1.1);
      },
      { passive: false }
    );

    load();
    // The map moves at scan rate, not at the state rate: one small read every few seconds is the
    // honest cadence, and it is paused while the tab is hidden.
    const timer = setInterval(() => {
      // Never while an edit is unsaved: a poll that replaced the working copy would delete the
      // wall somebody is drawing, which is the one thing an editor must not do.
      if (!document.hidden && !root.closest(".panel").hidden && !edited) load();
    }, 4000);

    return {
      update(store) {
        // Text only. The dog marker needs a pose in *this* frame, and the swap is the server's job
        // (#347), so the geometry arrives on the 4 s `GET /map` and not on every state frame - the
        // alternative was a second copy of the frame rule living in JavaScript.
        const tier = store && store.localization ? String(store.localization.tier || "") : "";
        poseChip.textContent = `pose: ${tier || "-"}`;
        const route = store && store.route;
        if (route && route.state === "refused") {
          routeChip.textContent = `route refused: ${route.refusal || "no_path"}`;
          routeChip.title = String(route.detail || "");
        } else if (route && route.state === "walking") {
          routeChip.textContent = `walking ${route.index}/${route.total}`;
          routeChip.title = "";
        } else if (routeChip.textContent) {
          routeChip.textContent = "";
          routeChip.title = "";
        }
      },
      destroy() {
        clearInterval(timer);
      },
    };
  },
};

