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
// Five layers, each toggleable, because they answer different questions: cells are *evidence* (what
// the sonar hit), walls and openings are *claims* (drawn by a person or lifted from the scan), rooms
// and surfaces are *meaning*, and places are *pins* - a taught spot with the camera's picture of it
// (M7). Unknown ground is hatched and floor is solid: a single hit is a maybe, not a floor, and the
// two must not look the same.
//
// A truncated map says so, and a map with no cells says why it is empty - `grid_enabled: false` and
// "no sweep has filled a cell yet" are different problems.
//
// The map is user data, so it can leave the tab (M8): **Export JSON** is the document `GET /map`
// publishes, which is exactly what `PUT /map` takes back; **Export PNG** is this canvas; and
// **Import…** copies a document into the live generation and lets **Save to device** carry it, so
// there is one write path and one validator rather than a second pair for files.

import { api, download, errorText, fmt } from "../lib.js";

const VIEW_KEY = "houndmind.map.view";
const PAD = 18;
// A cell with this many hits or more is floor; fewer is "seen once", which is a maybe.
const FLOOR_HITS = 2;
const LAYERS = ["cells", "rooms", "walls", "surfaces", "places"];
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
const MODES = ["view", "wall", "opening", "delete", "room", "surface", "object", "pose", "go", "pin"];
// The furniture kinds `mapping/home_map.py::OBJECT_KINDS` accepts. Closed on purpose: the server
// refuses a spelling it does not know, so the menu is the only place a new kind may appear (H3).
const OBJECT_KINDS = ["cabinet", "counter", "sofa", "table", "shelf", "other"];

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
const MIN_OBJECT_CM = 20;
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
          <button id="mp-mode-object" class="tiny">Object</button>
          <button id="mp-mode-pose" class="tiny">Pose</button>
          <button id="mp-mode-go" class="tiny">Go</button>
          <button id="mp-mode-pin" class="tiny">Pin</button>
          <button id="mp-pin-here" class="tiny">Here</button>
          <button id="mp-pose-confirm" class="tiny" disabled>Confirm position</button>
          <button id="mp-pose-cancel" class="tiny" disabled>Cancel</button>
          <button id="mp-send" class="tiny" disabled>Send route</button>
          <input id="mp-room-name" class="tiny" placeholder="room name" style="width:7.5rem">
          <label class="tiny" style="margin:0">room size cm
            <input id="mp-room-width" type="number" min="0" step="5" placeholder="width"
              style="width:4.5rem;margin-left:.3rem">
            <input id="mp-room-depth" type="number" min="0" step="5" placeholder="depth"
              style="width:4.5rem;margin-left:.25rem">
          </label>
          <select id="mp-object-kind" class="tiny">
            ${OBJECT_KINDS.map((kind) => `<option value="${kind}">${kind}</option>`).join("")}
          </select>
          <label class="tiny" style="margin:0">object cm
            <input id="mp-object-width" type="number" min="20" step="5" value="80" placeholder="along"
              style="width:4.5rem;margin-left:.3rem">
            <input id="mp-object-depth" type="number" min="20" step="5" value="60" placeholder="out"
              style="width:4.5rem;margin-left:.25rem">
          </label>
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
          <button id="mp-export-json" class="tiny">Export JSON</button>
          <button id="mp-export-png" class="tiny">Export PNG</button>
          <button id="mp-import" class="tiny">Import…</button>
          <input id="mp-import-file" type="file" accept="application/json" hidden>
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
    // M7: the picture of each place, from `GET /places`, keyed by place id. A pin draws a thumbnail
    // when one exists and reads as a plain ring when it does not - never as a broken image.
    let thumbs = new Map();
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
          places: document_.places || [],
          objects: document_.objects || [],
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
      document_.places = previous.places || [];
      // An object is a user section too: a snapshot that skipped it would make Undo *add* the last
      // piece of furniture back rather than remove it (H3).
      document_.objects = previous.objects || [];
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
    const roomWidth = root.querySelector("#mp-room-width");
    const roomDepth = root.querySelector("#mp-room-depth");
    const objectKind = root.querySelector("#mp-object-kind");
    const objectWidth = root.querySelector("#mp-object-width");
    const objectDepth = root.querySelector("#mp-object-depth");
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

    // The object hit test is the drawn rectangle, not its wall: a click on the sofa is a click on the
    // shape the user sees, so it reuses the corners `drawObjects` paints rather than a second geometry
    // that could disagree with the picture (#365).
    function objectUnder(point) {
      for (const entry of (document_ && document_.objects) || []) {
        const corners = objectCorners(entry);
        if (!corners) continue;
        if (pointInPolygon(point, corners)) return entry;
      }
      return null;
    }

    function pinUnder(point) {
      // The same tolerance the wall picker uses, so a click near a pin means the pin whether the
      // user meant to delete it or not: a 6 cm ring is one pixel wide at a fitted zoom.
      const tolerance = (HIT_PX + 4) / (view ? view.scale : 1);
      for (const pin of (document_ && document_.places) || []) {
        const x = Number(pin.x_cm);
        const y = Number(pin.y_cm);
        if (!Number.isFinite(x) || !Number.isFinite(y)) continue;
        if (Math.hypot(x - point[0], y - point[1]) <= tolerance) return pin;
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

    // The room's real size, when the person who drew it typed one (H2). Both numbers or nothing:
    // half a rectangle is not a measurement, and the absent key is what makes the room unmeasured.
    function roomSize() {
      const width = Number(roomWidth.value);
      const depth = Number(roomDepth.value);
      if (!(width > 0) || !(depth > 0)) return null;
      return { width_cm: width, depth_cm: depth };
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
      const size = roomSize();
      const room = {
        id: uid("room"),
        name,
        polygon,
        colour: ROOM_COLOURS[count % ROOM_COLOURS.length],
        keep_out: false,
        // Omitted rather than zeroed: `size_cm` absent is the room nobody measured, and the server
        // reads that same absence into `meta.scale_source` (H2).
        ...(size ? { size_cm: size } : {}),
      };
      pushHistory();
      document_.rooms = [...(document_.rooms || []), room];
      selected = { kind: "room", item: room };
      roomName.value = "";
      roomWidth.value = "";
      roomDepth.value = "";
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

    // An object is a rectangle standing against a wall: `start_cm` from the wall's `a` end, `width_cm`
    // along the wall, `depth_cm` out from it, and a kind from a closed list (H3). Nothing on the
    // device reads one yet — this is the drawing the planner will be given, not a rule it obeys.
    function placeObject(point) {
      const width = Math.max(MIN_OBJECT_CM, Math.round(Number(objectWidth.value) || 0));
      const depth = Math.max(MIN_OBJECT_CM, Math.round(Number(objectDepth.value) || 0));
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
        error.textContent = "click a wall to stand an object against it";
        return;
      }
      const length = Math.hypot(target.b[0] - target.a[0], target.b[1] - target.a[1]);
      if (length < width + 10) {
        error.textContent = `that wall is ${length.toFixed(0)} cm; a ${width} cm object does not fit`;
        return;
      }
      // A rectangle that overhangs its wall is refused by the server, so the clamp here keeps
      // `start_cm + width_cm` inside the wall rather than sending an edit that comes back a `400`.
      const limit = Math.max(0, Math.floor((length - width) / SNAP_CM) * SNAP_CM);
      const t = projectOnSegment(point, target.a, target.b);
      const start = Math.min(snap(Math.max(0, t * length - width / 2)), limit);
      pushHistory();
      document_.objects = [
        ...(document_.objects || []),
        {
          id: uid("obj"),
          wall_id: target.id,
          start_cm: start,
          width_cm: width,
          depth_cm: depth,
          kind: objectKind.value,
          source: "user",
        },
      ];
      error.textContent = "";
      markDirty(true);
      render();
    }

    function deleteAt(point) {
      const pin = pinUnder(point);
      if (pin) {
        // The pin is the map's annotation, the place is the catalogue's entry: deleting this one
        // forgets where it is drawn, and the place stays until it is Forgotten in the Places panel.
        pushHistory();
        document_.places = (document_.places || []).filter((item) => item !== pin);
        markDirty(true);
        render();
        return;
      }
      // Furniture is drawn *inside* a room, so it is tested before the room: a click on the counter
      // would otherwise delete the kitchen it stands in. It goes through `pushHistory` like every other
      // delete, because the snapshot already carries `objects` and Undo has to take it back (#365).
      const object = objectUnder(point);
      if (object) {
        pushHistory();
        document_.objects = (document_.objects || []).filter((item) => item !== object);
        markDirty(true);
        render();
        return;
      }
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


    // ---- export and import (M8) --------------------------------------------

    function exportName(extension) {
      // The generation rides in the name: a map is exactly the file a person keeps several of, and
      // two copies in one folder are otherwise indistinguishable.
      const generation = document_ && document_.meta ? document_.meta.rev : null;
      const label = generation === null || generation === undefined ? "unversioned" : generation;
      return `houndmind-map-${label}.${extension}`;
    }

    function exportJson() {
      if (!document_) return;
      // The wire document, not a file shape invented here: it is what `PUT /map` accepts, so a backup
      // and a hand-over to another console are the same artefact.
      const blob = new Blob([JSON.stringify(document_, null, 2)], { type: "application/json" });
      download(blob, exportName("json"));
      note.textContent = `exported rev ${
        document_.meta && document_.meta.rev != null ? document_.meta.rev : "-"
      } as JSON`;
    }

    function exportPng() {
      // The canvas is the floor plan: no second renderer, and what is on screen - legend, scale bar
      // and all - is what ends up on the fridge. A browser that cannot encode it says so.
      canvas.toBlob((blob) => {
        if (blob) download(blob, exportName("png"));
        else error.textContent = "this browser could not encode the canvas as a PNG";
      }, "image/png");
    }

    function importDocument(file) {
      if (!document_) {
        // There is no live generation to import *into*, and a document adopted here would carry a
        // `rev` nobody measured on the one field a save must get right.
        error.textContent = "load the map from the device before importing one";
        return;
      }
      const reader = new FileReader();
      reader.onerror = () => {
        error.textContent = `${file.name} could not be read`;
      };
      reader.onload = () => {
        let parsed = null;
        try {
          // A file saved by a Windows editor may carry a byte-order mark, and `JSON.parse` refuses
          // one with a message that blames the JSON rather than the three bytes in front of it (#361).
          parsed = JSON.parse(String(reader.result).replace(/^\uFEFF/, ""));
        } catch (err) {
          error.textContent = `${file.name} is not JSON`;
          return;
        }
        // Two spellings, one document: the export is the bare document and a `PUT /map` body wraps
        // it, so a file this panel wrote and a request copied out of a log both import.
        const carried =
          parsed && typeof parsed === "object" && !Array.isArray(parsed)
            ? parsed.document || parsed
            : null;
        if (!carried || typeof carried !== "object" || Array.isArray(carried)) {
          error.textContent = `${file.name} does not carry a map document`;
          return;
        }
        const next = JSON.parse(JSON.stringify(carried));
        // The device's own file nests the cells under `grid`; the wire shape is flat and `PUT /map`
        // takes either, so lifting them is what lets a file copied off the Pi draw here.
        if (!next.cells && next.grid && next.grid.cells) next.cells = next.grid.cells;
        delete next.grid;
        // The position on this map is *this* dog's: `_pose_origin` falls back to `document.dog` when
        // there is no live pose, so a foreign one would become the origin a taught place is measured
        // from. The live dog stays.
        delete next.dog;
        if (document_.dog) next.dog = document_.dog;
        // One generation: the copy is imported into this device's map, not beside it. A foreign `rev`
        // would make the save a 409 that reads as "the map changed since this copy was read".
        const live = document_.meta ? document_.meta.rev : 0;
        next.meta = { ...(next.meta || {}), rev: live };
        document_ = next;
        // The imported tree replaced the one the cursor was working on, so a half-drawn wall, a lasso
        // and a snapshot of the old document all refer to something that is no longer there.
        history = [];
        draft = null;
        lasso = null;
        selected = null;
        ghost = null;
        preview = null;
        error.textContent = "";
        markDirty(true);
        describe(document_);
        fit(document_);
        render();
        note.textContent = `${file.name} imported: Save to device writes it`;
      };
      reader.readAsText(file);
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


    // ---- pins (M7) ----------------------------------------------------------

    const THUMB_W = 32;
    const THUMB_H = 24;
    // A thumbnail is 768 raw grey bytes, not an image file (`perception/place_views.py` stores the
    // pixels). It becomes a canvas once per distinct picture: grey in, grey out, drawn scaled with
    // smoothing off so 32x24 stays recognisable instead of turning to mush.
    const thumbCache = new Map();

    function thumbCanvas(b64) {
      if (typeof b64 !== "string" || !b64) return null;
      if (thumbCache.has(b64)) return thumbCache.get(b64);
      let raw;
      try {
        raw = atob(b64);
      } catch (err) {
        return null;
      }
      if (raw.length !== THUMB_W * THUMB_H) return null;
      const pixels = new ImageData(THUMB_W, THUMB_H);
      for (let index = 0; index < raw.length; index += 1) {
        const grey = raw.charCodeAt(index);
        pixels.data[index * 4] = grey;
        pixels.data[index * 4 + 1] = grey;
        pixels.data[index * 4 + 2] = grey;
        pixels.data[index * 4 + 3] = 255;
      }
      const off = document.createElement("canvas");
      off.width = THUMB_W;
      off.height = THUMB_H;
      off.getContext("2d").putImageData(pixels, 0, 0);
      thumbCache.set(b64, off);
      return off;
    }

    async function refreshThumbs() {
      const next = new Map();
      try {
        const catalogue = await api("/places");
        for (const place of (catalogue && catalogue.places) || []) {
          if (!place || !place.id) continue;
          const picture = thumbCanvas(place.thumb);
          if (picture) next.set(String(place.id), picture);
        }
      } catch (err) {
        // A 503 here is the normal state with `place_navigator` off and a 403 is a token that
        // cannot read places: pins still draw, they just have no picture. Nothing to report over a
        // map that is otherwise fine.
      }
      thumbs = next;
    }

    async function teachAt(point) {
      if (!document_) return;
      error.textContent = "";
      const name = window.prompt("Name this spot", "");
      if (name === null) return;
      const trimmed = name.trim();
      if (!trimmed) return;
      try {
        const answer = await api("/places/teach", {
          method: "POST",
          body: JSON.stringify({ name: trimmed, x_cm: point[0], y_cm: point[1] }),
        });
        const place = answer && answer.place ? answer.place : null;
        if (!place || !place.id) {
          error.textContent = "the device answered without a place";
          return;
        }
        // The pin is a `places[]` entry in this document - a user section `PUT /map` already
        // carries - not a second store. It stays unsaved until **Save to device**.
        pushHistory();
        const pin = {
          id: String(place.id),
          name: String(place.name || trimmed),
          x_cm: point[0],
          y_cm: point[1],
          heading_deg: Number(place.heading_deg) || 0,
          uncertainty_cm: null,
        };
        document_.places = (document_.places || [])
          .filter((item) => item.id !== pin.id)
          .concat(pin);
        const picture = thumbCanvas(place.thumb);
        if (picture) thumbs.set(pin.id, picture);
        markDirty(true);
        describe(document_);
        const assumed = !(document_.meta && document_.meta.step_cm_source === "measured");
        // The stride is what turns a distance into a walk, and it is a guess until it is measured
        // (#285): saying so beside the pin is the difference between a fact and a claim.
        note.textContent = `pin "${pin.name}" added · ${fmt(
          Number(place.distance_cm),
          "cm"
        )} and ${fmt(Number(place.heading_deg), "°")} from the dog · ${
          assumed ? "stride assumed, so the distance is a guess" : "stride measured"
        } · Save to device keeps it`;
        render();
      } catch (err) {
        const payload = err.payload || {};
        error.textContent = payload.detail
          ? `${payload.error || "refused"}: ${payload.detail}`
          : errorText(err);
      }
    }

    async function teachHere() {
      const pose = livePose || (document_ && document_.dog ? document_.dog : null);
      if (!pose) {
        error.textContent = "no position to teach from - correct the dog's position first";
        return;
      }
      await teachAt([Number(pose.x_cm) || 0, Number(pose.y_cm) || 0]);
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
        // H2: a room nobody measured says so on the drawing rather than leaving the save to imply a
        // scale the dog has not discovered. The per-room field is the truth here, not
        // `meta.scale_source`, which is only the document-wide claim.
        ctx.font = "10px ui-sans-serif, system-ui";
        const size = room.size_cm;
        const measured = Boolean(size) && Number(size.width_cm) > 0 && Number(size.depth_cm) > 0;
        ctx.fillText(
          measured
            ? `${size.width_cm} x ${size.depth_cm} cm`
            : "scale: not measured - run the room to measure it",
          sx,
          sy + 12
        );
        if (room.keep_out) {
          ctx.fillText("keep out", sx, sy + 24);
        }
      }
    }

    // The four corners of one object, in the document frame, from the wall it is anchored to. Kept
    // here rather than on the server because nothing on the device reads objects yet (H3).
    function objectCorners(entry) {
      const wall = ((document_ && document_.walls) || []).find((item) => item.id === entry.wall_id);
      if (!wall || !Array.isArray(wall.a) || !Array.isArray(wall.b)) return null;
      const length = Math.hypot(wall.b[0] - wall.a[0], wall.b[1] - wall.a[1]);
      if (!(length > 0)) return null;
      const width = Math.max(0, Number(entry.width_cm) || 0);
      const depth = Math.max(0, Number(entry.depth_cm) || 0);
      const start = Math.min(Math.max(0, Number(entry.start_cm) || 0), Math.max(0, length - width));
      const from = start / length;
      const to = Math.min(1, (start + width) / length);
      const dx = (wall.b[0] - wall.a[0]) / length;
      const dy = (wall.b[1] - wall.a[1]) / length;
      // The rectangle stands out from the wall on the side a room is drawn on. With no room to say
      // which, the wall's own right normal is the one an outline reads as inside.
      const mid = pointAt(wall.a, wall.b, (from + to) / 2);
      const rooms = (document_ && document_.rooms) || [];
      const insideLeft = rooms.some(
        (room) =>
          Array.isArray(room.polygon) &&
          room.polygon.length >= 3 &&
          pointInPolygon([mid[0] - dy * 5, mid[1] + dx * 5], room.polygon)
      );
      const nx = insideLeft ? -dy : dy;
      const ny = insideLeft ? dx : -dx;
      const a = pointAt(wall.a, wall.b, from);
      const b = pointAt(wall.a, wall.b, to);
      return [
        a,
        b,
        [b[0] + nx * depth, b[1] + ny * depth],
        [a[0] + nx * depth, a[1] + ny * depth],
      ];
    }

    function drawObjects(ctx) {
      for (const entry of document_.objects || []) {
        const corners = objectCorners(entry);
        if (!corners) continue;
        ctx.beginPath();
        corners.forEach(([x, y], index) => {
          const [sx, sy] = screen(x, y);
          if (index === 0) ctx.moveTo(sx, sy);
          else ctx.lineTo(sx, sy);
        });
        ctx.closePath();
        ctx.fillStyle = "rgba(233, 238, 243, 0.14)";
        ctx.fill();
        ctx.strokeStyle = "rgba(233, 238, 243, 0.55)";
        ctx.lineWidth = 1;
        ctx.stroke();
        const [cx, cy] = screen(
          (corners[0][0] + corners[2][0]) / 2,
          (corners[0][1] + corners[2][1]) / 2
        );
        ctx.fillStyle = "#c9d3de";
        ctx.font = "10px ui-sans-serif, system-ui";
        ctx.textAlign = "center";
        ctx.fillText(entry.kind || "object", cx, cy);
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

    function drawPins(ctx) {
      const places = document_ && Array.isArray(document_.places) ? document_.places : [];
      for (const pin of places) {
        const x = Number(pin.x_cm);
        const y = Number(pin.y_cm);
        if (!Number.isFinite(x) || !Number.isFinite(y)) continue;
        const [sx, sy] = screen(x, y);
        const name = String(pin.name || pin.id || "place");
        const picture = thumbs.get(String(pin.id));
        ctx.save();
        if (picture) {
          // The picture is the point of a pin: it is how a person recognises the room months later.
          ctx.imageSmoothingEnabled = false;
          ctx.drawImage(picture, sx - THUMB_W, sy - 40, THUMB_W * 2, THUMB_H * 2);
          ctx.strokeStyle = "#7fd4c1";
          ctx.lineWidth = 1;
          ctx.strokeRect(sx - THUMB_W, sy - 40, THUMB_W * 2, THUMB_H * 2);
        }
        // A ring, not a filled dot: the dog is the brightest thing on the canvas and a pin must not
        // compete with it for that reading.
        ctx.strokeStyle = "#7fd4c1";
        ctx.fillStyle = "rgba(12, 26, 24, .8)";
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.arc(sx, sy, 6, 0, Math.PI * 2);
        ctx.fill();
        ctx.stroke();
        ctx.fillStyle = "#d6efe9";
        ctx.font = "12px ui-monospace, monospace";
        ctx.textAlign = "left";
        ctx.fillText(name, sx + 10, sy + 4);
        ctx.restore();
      }
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
      if (layers.has("rooms")) {
        // Furniture is room context, so it rides the `rooms` layer: a sixth toggle would be a sixth
        // thing to forget, and a rectangle on top of the floor it stands on reads as part of it (H3).
        drawRooms(ctx);
        drawObjects(ctx);
      }
      if (layers.has("cells")) drawCells(ctx);
      if (layers.has("walls")) {
        drawWalls(ctx);
        drawOpenings(ctx);
      }
      if (layers.has("places")) drawPins(ctx);
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
      if (
        !cells &&
        !(document.walls || []).length &&
        !(document.rooms || []).length &&
        !(document.places || []).length
      ) {
        count.textContent = "no map";
        note.textContent =
          document.meta && document.meta.source === "scan"
            ? "no sweep has filled a cell yet"
            : "this document carries no cells, walls, rooms or pins yet";
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
      } · rooms ${(document.rooms || []).length} · surfaces ${
        (document.surfaces || []).length
      } · places ${(document.places || []).length}`;
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
        // M7: pins are places, and only `GET /places` carries their picture. Awaiting it here keeps
        // one refresh per poll; a device with the navigator off answers 503 and the pins draw plain.
        await refreshThumbs();
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
    root.querySelector("#mp-export-json").addEventListener("click", exportJson);
    root.querySelector("#mp-export-png").addEventListener("click", exportPng);
    const importFile = root.querySelector("#mp-import-file");
    root.querySelector("#mp-import").addEventListener("click", () => importFile.click());
    importFile.addEventListener("change", () => {
      const file = importFile.files && importFile.files[0];
      // Cleared first: importing the same file twice is a thing people do, and an unchanged value
      // fires no `change` event the second time.
      importFile.value = "";
      if (file) importDocument(file);
    });
    root.querySelector("#mp-keepout").addEventListener("click", toggleKeepOut);
    root.querySelector("#mp-pin-here").addEventListener("click", teachHere);
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
      if (mode === "pin") {
        // One click, one place: the name and the picture are the whole act (M7).
        teachAt(point);
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
      if (mode === "object") {
        placeObject(point);
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

