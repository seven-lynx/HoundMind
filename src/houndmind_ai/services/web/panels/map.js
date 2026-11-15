// Map: the occupancy grid the mapper keeps, drawn from `GET /map` (#175).
//
// The cells arrive in **cells, not centimetres** (`[ix, iy, hits]` plus `cell_size_cm`), so this panel
// does no projection of its own: it scales integers. `ix` is left-positive and `iy` is
// forward-positive, the mapper's own convention (`mapping/mapper.py::_ingest_into_grid`), so the
// picture is drawn with the nose up and the dog's left on the screen's left.
//
// A truncated map says so: an empty corner is "not sent", not "not mapped", and only one of those is
// worth walking into. No map at all is stated as the reason it is missing - `grid_enabled: false`
// and "no sweep has filled a cell yet" are different problems.

import { api, errorText, fmt } from "../lib.js";

const SIZE = 320;

export const map = {
  id: "map",
  label: "Map",

  mount(root) {
    root.innerHTML = `
      <div class="card">
        <div class="row" style="justify-content:space-between">
          <h3 style="margin:0">Occupancy</h3>
          <div class="row">
            <span class="chip" id="mp-count">no map</span>
            <button id="mp-refresh" class="tiny">Refresh</button>
          </div>
        </div>
        <canvas id="mp-canvas" width="${SIZE}" height="${SIZE}"
          style="width:100%;max-width:${SIZE}px;display:block;margin:.6rem auto;background:var(--ink-2);border-radius:8px"></canvas>
        <p class="hint" id="mp-note"></p>
        <p class="error" id="mp-error" role="alert"></p>
      </div>`;

    const canvas = root.querySelector("#mp-canvas");
    const count = root.querySelector("#mp-count");
    const note = root.querySelector("#mp-note");
    const error = root.querySelector("#mp-error");

    function draw(payload) {
      const ctx = canvas.getContext("2d");
      ctx.clearRect(0, 0, SIZE, SIZE);
      const grid = payload && payload.map;
      if (!grid || !Array.isArray(grid.cells) || !grid.cells.length) {
        count.textContent = "no map";
        note.textContent =
          payload && payload.grid_enabled === false
            ? "mapping.grid_enabled is off, so nothing is being recorded"
            : "no sweep has filled a cell yet";
        return;
      }

      let minX = 0;
      let maxX = 0;
      let minY = 0;
      let maxY = 0;
      for (const [ix, iy] of grid.cells) {
        if (ix < minX) minX = ix;
        if (ix > maxX) maxX = ix;
        if (iy < minY) minY = iy;
        if (iy > maxY) maxY = iy;
      }
      // At least eight cells across, so one cell is not blown up to the whole canvas.
      const span = Math.max(maxX - minX, maxY - minY, 8);
      const scale = SIZE / (span + 2);
      const centreX = (minX + maxX) / 2;
      const centreY = (minY + maxY) / 2;
      const screenX = (ix) => SIZE / 2 + (centreX - ix) * scale;
      const screenY = (iy) => SIZE / 2 - (iy - centreY) * scale;
      const strongest = Math.max(...grid.cells.map(([, , hits]) => hits)) || 1;

      // The forward axis first, so the cells sit on top of it.
      ctx.strokeStyle = "rgba(143, 160, 176, 0.35)";
      ctx.beginPath();
      ctx.moveTo(SIZE / 2, SIZE / 2);
      ctx.lineTo(SIZE / 2, 0);
      ctx.stroke();

      for (const [ix, iy, hits] of grid.cells) {
        const alpha = 0.25 + 0.75 * (hits / strongest);
        ctx.fillStyle = `rgba(240, 165, 58, ${alpha.toFixed(2)})`;
        const side = Math.max(scale, 1);
        ctx.fillRect(screenX(ix) - scale / 2, screenY(iy) - scale / 2, side, side);
      }

      // The dog, at its own origin.
      ctx.fillStyle = "#e9eef3";
      ctx.beginPath();
      ctx.arc(SIZE / 2, SIZE / 2, 3, 0, Math.PI * 2);
      ctx.fill();

      const label = `${grid.count} cell${grid.count === 1 ? "" : "s"}`;
      count.textContent = grid.truncated ? `${label} (truncated)` : label;
      note.textContent = grid.truncated
        ? `showing the ${grid.cells.length} most-hit of ${grid.count} cells; one square is ${fmt(
            grid.cell_size_cm,
            "cm"
          )}, nose up`
        : `one square is ${fmt(grid.cell_size_cm, "cm")}, nose up`;
    }

    async function load() {
      error.textContent = "";
      try {
        draw(await api("/map"));
      } catch (err) {
        error.textContent = errorText(err);
        count.textContent = "no map";
        note.textContent = "";
      }
    }

    root.querySelector("#mp-refresh").addEventListener("click", load);
    load();
    // The grid moves at scan rate, not at the state rate: a poll every few seconds is the honest
    // cadence, and it costs one small read rather than a frame on every tick.
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
