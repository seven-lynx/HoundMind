// Camera: the MJPEG stream and a still, both through a ticket rather than the token.
//
// An `<img>` cannot send an Authorization header, and the device token must never appear in a URL
// (#18) - so the panel asks for a short-lived ticket and puts *that* in the query string. The
// snapshot uses the same ticket, and the download goes through a blob so the URL is not in the
// browser's history with a credential in it.

import { api, errorText, esc } from "../lib.js";

export const camera = {
  id: "camera",
  label: "Camera",

  mount(root) {
    root.innerHTML = `
      <div class="card">
        <div class="row" style="justify-content:space-between">
          <h3 style="margin:0">Live</h3>
          <div class="row">
            <button id="cam-reload" class="tiny">Reload</button>
            <button id="cam-still" class="tiny">Save still</button>
            <button id="cam-full" class="tiny">Fullscreen</button>
          </div>
        </div>
        <img id="cam-img" alt="camera stream" style="width:100%;border-radius:8px;border:1px solid var(--line);margin-top:.7rem" hidden>
        <div id="cam-note" class="empty" style="margin-top:.7rem">asking for a stream ticket…</div>
      </div>
      <p class="error" id="cam-error" role="alert"></p>`;

    const img = root.querySelector("#cam-img");
    const note = root.querySelector("#cam-note");
    const error = root.querySelector("#cam-error");

    img.addEventListener("error", () => {
      img.hidden = true;
      note.hidden = false;
      note.textContent =
        "No frames. Enable a vision module on the device, or check the camera index in config.";
    });

    async function ticket() {
      const payload = await api("/camera/ticket", { method: "POST", body: JSON.stringify({}) });
      return payload.ticket;
    }

    async function stream() {
      error.textContent = "";
      note.hidden = false;
      note.textContent = "asking for a stream ticket…";
      try {
        const value = await ticket();
        img.src = `/api/v1/camera/stream?ticket=${encodeURIComponent(value)}`;
        img.hidden = false;
        note.hidden = true;
      } catch (err) {
        note.textContent = esc(errorText(err));
      }
    }

    async function still() {
      error.textContent = "";
      try {
        const value = await ticket();
        const response = await fetch(`/api/v1/camera/snapshot?ticket=${encodeURIComponent(value)}`);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const blob = await response.blob();
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = `houndmind-${new Date().toISOString().replace(/[:.]/g, "-")}.jpg`;
        link.click();
        setTimeout(() => URL.revokeObjectURL(url), 5000);
      } catch (err) {
        error.textContent = error && err.status ? errorText(err) : `No still: ${err.message}`;
      }
    }

    root.querySelector("#cam-reload").addEventListener("click", stream);
    root.querySelector("#cam-still").addEventListener("click", still);
    root.querySelector("#cam-full").addEventListener("click", () => {
      if (img.requestFullscreen) img.requestFullscreen().catch(() => {});
    });

    stream();

    return { update() { /* the stream is its own transport */ } };
  },
};
