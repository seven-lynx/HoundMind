// Map: the home map the dog builds, drawn from the `document` M1 puts on `GET /map` (#307).
//
// **The frame comes from the document, and it is not the runtime's.** The document states
// `x = left-positive`, `y = forward-positive`, centimetres from the map origin (M plan section 5), so
// this panel draws nose-up with no conversion: screen x = centre - x * scale (left is left), screen
// y = centre - y * scale (forward is up). The runtime's own pose is (forward, left) - a different
// order under the same names - which is why the dog here comes from `document.dog` and never from
// `localization.pose`: plotting the live pose against this frame would mirror it (#347).
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

    let view = loadView();
    let document_ = null;
    let layers = new Set(LAYERS);

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


    function drawDog(ctx) {
      const dog = document_.dog;
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
      // Meaning underneath evidence: a room is context for the cells drawn on top of it.
      if (layers.has("surfaces")) drawSurfaces(ctx);
      if (layers.has("rooms")) drawRooms(ctx);
      if (layers.has("cells")) drawCells(ctx);
      if (layers.has("walls")) {
        drawWalls(ctx);
        drawOpenings(ctx);
      }
      drawDog(ctx);
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
        document_ = payload && payload.document ? payload.document : null;
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

    for (const name of LAYERS) {
      const box = root.querySelector(`#mp-layer-${name}`);
      box.checked = layers.has(name);
      box.addEventListener("change", () => {
        if (box.checked) layers.add(name);
        else layers.delete(name);
        render();
      });
    }

    // Drag to pan, wheel to zoom. Both write the view, so a reload comes back where you left it.
    let dragging = null;
    canvas.addEventListener("pointerdown", (event) => {
      canvas.setPointerCapture(event.pointerId);
      canvas.style.cursor = "grabbing";
      dragging = { x: event.clientX, y: event.clientY, view: { ...(view || {}) } };
    });
    canvas.addEventListener("pointermove", (event) => {
      if (!dragging || !view) return;
      const dx = event.clientX - dragging.x;
      const dy = event.clientY - dragging.y;
      view = {
        ...view,
        cx: (dragging.view.cx || 0) + dx / view.scale,
        cy: (dragging.view.cy || 0) + dy / view.scale,
      };
      render();
    });
    const stopDrag = () => {
      if (!dragging) return;
      dragging = null;
      canvas.style.cursor = "grab";
      if (view) saveView(view);
    };
    canvas.addEventListener("pointerup", stopDrag);
    canvas.addEventListener("pointercancel", stopDrag);
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
      if (!document.hidden && !root.closest(".panel").hidden) load();
    }, 4000);

    return {
      update() {
        /* the map changes at scan rate; the timer is enough */
      },
      destroy() {
        clearInterval(timer);
      },
    };
  },
};

