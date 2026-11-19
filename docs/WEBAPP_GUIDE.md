# HoundMind Kennel Console — user guide

Status: **guide** — open the web app, connect to it, and use each panel. Every fact here is
checkable against the tree: `src/houndmind_ai/services/web/` is the app, `services/settings.py` holds
the defaults, and `docs/CONTROL_API.md` is the route contract.
Pairs with: [`CONTROL_API.md`](CONTROL_API.md) (the wire contract),
[`INSTALL.md` §*The service: what starts at boot*](INSTALL.md#the-service-what-starts-at-boot),
[`FEATURES_GUIDE.md` §26](FEATURES_GUIDE.md#26-control-plane--rest-websocket-camera-web-app) (the
reference entry, including the security posture)

The console is the **Kennel Console**: one page, fourteen panels, served by the runtime itself. It
is not a second program. `GET /` and `/static/*` come from the `api` module
(`ControlPlaneModule`, `src/houndmind_ai/services/module.py`) on the same port as the REST and
WebSocket API — `8420` unless `settings.api.port` says otherwise. Two consequences worth holding on
to:

- runtime up ⇒ console up, provided `modules.api.enabled` is `true` (it is, in the shipped config);
- runtime down, or the module disabled itself ⇒ nothing is listening, and no browser can connect.

Nothing in this guide moves the dog by itself. Drive and Tricks send commands, and whether the dog
acts on one is decided on the device — [§6](#6-what-the-console-cannot-do) is the part to read before
pressing anything.

## Contents

- [1. Before you open it](#1-before-you-open-it)
- [2. First connection](#2-first-connection)
- [3. The shell](#3-the-shell)
- [4. Keyboard and the palette](#4-keyboard-and-the-palette)
- [5. The panels](#5-the-panels)
- [6. What the console cannot do](#6-what-the-console-cannot-do)
- [7. Install it on a phone](#7-install-it-on-a-phone)
- [8. Desktop notifications](#8-desktop-notifications)
- [9. Several dogs](#9-several-dogs)
- [10. When it will not load](#10-when-it-will-not-load)
- [11. Security](#11-security)
- [12. Where the facts live](#12-where-the-facts-live)

## 1. Before you open it

Four things have to be true. The first three are the ones that fail in practice.

| Need | Check it on the device | Comes from |
|---|---|---|
| The runtime is running | `systemctl is-active houndmind` → `active` | [`INSTALL.md` §*The service*](INSTALL.md#the-service-what-starts-at-boot) |
| The control plane is enabled | `modules.api.enabled` is `true` | `config/settings.jsonc:143` |
| Something is listening | `ss -ltnp \| grep 8420` | `settings.api.host` / `port` |
| A token exists | `ls -l ~/.houndmind/api_token` | written `0600` on the first start |

```bash
# on the device
systemctl is-active houndmind
ss -ltnp | grep 8420                          # one LISTEN on 0.0.0.0:8420
curl -s http://127.0.0.1:8420/api/v1/health   # answers without a token
curl -s http://127.0.0.1:8420/api/v1/meta     # answers without a token
```

`/api/v1/health` and `/api/v1/meta` are the only routes that answer without a token; everything
else needs it. If the first command says `inactive`, nothing below in this guide applies until the
service is started — [§10](#10-when-it-will-not-load).

Then find the address to type into the browser:

```bash
hostname -I | awk '{print $1}'                 # e.g. 192.168.1.42
```

The plane also advertises itself over mDNS, so `http://<hostname>.local:8420/` normally works — the
name the plane publishes is `<whatever the Pi is called>.local`, so a stock card answers as
`raspberrypi.local` (`settings.api.discovery_name` renames the mDNS *instance*, not the host).
mDNS loses to networks that block multicast; the numeric address always works (#294).

## 2. First connection

Open `http://<pi-address>:8420/`. Until a token is accepted you get the **Connect** card and
nothing else — it is the only screen reachable without one.

### With the device token

The device token is the operator credential. The runtime generates it on its first start and writes
it to `~/.houndmind/api_token`, mode `0600`:

```bash
grep -m1 . ~/.houndmind/api_token           # prints the token; run this on the device
stat -c '%a %n' ~/.houndmind/api_token      # expect 600 and the path
```

Paste it into **Device token** and press **Use token**. The console keeps it in the tab's
`sessionStorage` (`houndmind.token`, `web/lib.js:9`): it survives a reload, disappears when the tab
closes, and is never written to `localStorage` or to disk. **Disconnect** clears it.

Do not paste that output into a URL, a chat, an issue or a screenshot.

### With a pairing code

A pairing code is for a phone or a second browser that should not hold the operator credential.
Open a window from a client that already has `admin` — the **History** panel's *Open a pairing
window* button, or:

```bash
curl -H "Authorization: Bearer $(cat ~/.houndmind/api_token)" \
     -X POST http://127.0.0.1:8420/api/v1/pair/open
```

The code is six digits, valid **five minutes**, **single use** (`services/auth.py:135`). Enter it in
**Pairing code**, give the client a name, and press **Pair this browser**.

### What a paired client may do

| Scope | Device token | Paired client | What it unlocks |
|---|---|---|---|
| `state:read` | yes | yes | every read: state, scan, map, modules, decisions, history, camera ticket |
| `move` | yes | yes | `POST /command`, `/stop`, `/mode` — Drive, Tricks, a routine, walking to a place — plus correcting the dog's position (`PUT /map/pose`) and sending it to a point (`POST /map/go`) |
| `config` | yes | yes | `PATCH /config`, place and routine writes, calibration probes |
| `admin` | yes | **no** | People, Logs, the support bundle, opening a pairing window |

`PAIRING_SCOPES` is exactly the first three (`services/auth.py:44`). A panel that needs a scope the
token lacks says so: `403` renders as "This token lacks the scope for that" rather than an empty box
(`web/lib.js:223`).

### HTTPS

With `settings.api.tls_enabled: false` (the default) the console is plain HTTP: the token, every
command and every camera frame cross the network in the clear. `true` serves HTTPS with a
self-signed certificate generated on first start, and each client trusts it once —
[`INSTALL.md` §*TLS*](INSTALL.md#tls-for-the-control-plane-optional). Two browser features need a
secure context, installing the app to a home
screen ([§7](#7-install-it-on-a-phone)) and desktop notifications ([§8](#8-desktop-notifications)), and
both are simply unavailable without one.

## 3. The shell

Once connected, the page is a header, a rail of panels, a stage, and an event ticker.

| Control | What it shows | Notes |
|---|---|---|
| Brand chip | `<device_id> · <profile>` | from `/api/v1/meta`; the profile is what the board reported |
| Device picker | this dog, plus any you added | choosing one navigates the tab — [§9](#9-several-dogs) |
| Mode badge | `mode idle` / `manual` / `patrol` / `rest` | the runtime's mode, not a local setting |
| Link badge | `connecting`, `live`, `no frames`, `offline`, `no stream` | hover it: it names the identity you are authenticated as and the scopes |
| Theme button | `dark` or `light` | dark-first, follows the OS until you choose; remembered in `localStorage` |
| Notify button | `notify off` / `notify on` / `notify blocked` | hidden entirely without a secure context — [§8](#8-desktop-notifications) |
| Disconnect | — | forgets the token in this tab and returns to the Connect card |

**The link badge is the one thing to trust over the panels.** A panel always shows its last known
state; the badge says whether that state is still arriving.

| Badge | Means | What to do |
|---|---|---|
| `connecting` | the socket is opening | wait a second |
| `live` | state frames are arriving | nothing |
| `no frames` | nothing for over 4 s (`web/app.js:355`) | check WiFi; the panels are frozen, not wrong |
| `offline` | the socket is closed | the client retries with backoff, up to every 15 s |
| `no stream` | HTTP answers, the WebSocket does not | a proxy or firewall is breaking the socket — [§10](#10-when-it-will-not-load) |

When the badge is not `live`, a banner says so in a sentence. On `offline` it says every panel shows
its last known state and nothing you press will reach the dog — that is literal: the REST call would
fail too.

**The ticker** (bottom) is the last twelve events from the device, newest first. Vetoes —
`command_vetoed`, `command_expired`, `safety_action` — are tinted, and each event row is a log
entry, not a control. It is the second place a refusal appears, after the panel that caused it.

## 4. Keyboard and the palette

| Key | Does |
|---|---|
| `Ctrl`/`Cmd` + `K` | open the command palette |
| `?` | open the palette |
| `Esc` | close the palette |
| `1` … `9` | jump to that panel, in rail order |
| `W` `A` `S` `D` or the arrow keys | drive while held — forward, left, back, right |
| `Space` | stop and park (`rest`) |

Three rules make the shortcuts safe rather than clever:

- **Typing wins.** A shortcut is ignored while the focus is in an `input`, `textarea`, `select`, or
  an editable element (`web/app.js:517`), so naming a place "wasd" does not walk the dog.
- **Drive keys are global.** They work on any panel, not only Drive — the same code path the
  on-screen pad uses, so a key press and a held button cannot drift apart (`web/app.js:506`).
- **A hidden tab stops the dog.** Switching tabs or minimising the window stops the motion the tab
  was commanding (`web/app.js:566`), without changing the mode.

The palette lists every panel by name and every command it can run — including the three that act on
the dog rather than the view: `Stop the dog (parks it in rest)`, `Park the dog (mode rest)` and
`Hand back control - autonomy on (mode idle)`. `1`–`9` map to the first nine
panels: Overview, Drive, Tricks, Routines, Places, People, Camera, Decisions, History.

## 5. The panels

Rail order is the operator's path: see the dog, drive it, then the things that need setting up. The
first nine are the ones `1`–`9` jump to.

### Overview

**Shows** — the dog in its current posture, four instruments, two sparklines, the sentence behind the
last decision, and a runtime block.

- The stance is a **reading, not a claim**: `moving`/`sitting`/`lying` only while the winning command
  is under 2.5 s old; otherwise `rest` reads as resting, `patrol` as patrolling, anything else as
  `standing by`. A posture the runtime has no word for stays "standing by" rather than a guess
  (`web/panels/overview.js:29`).
- Instruments honour validity: a sensor that did not answer draws a dash. Sonar warns at ≤30 cm and
  is critical at ≤12; battery at ≤7.0 V and ≤6.6 V; temperature at ≥65 °C and ≥78 °C; the loop gauge
  tints on tick overrun. Below them: a 12-second sonar trace and the tick cost.
- The **why** line is one of four sentences: the veto ("refused — the dog did not do it, see
  Decisions"), `intent (confidence%) from source`, `holding <action>`, or "nothing has asked the dog
  to move yet".
- The facts block carries mode, touch, sound (heard, and from where), pitch/roll, whether the heading
  is gyro-corrected, safety on/off, e-stop set/clear, and whether the supervisor is holding motion.

**Needs** — `state:read`.

**If it looks wrong** — dashes everywhere under a `live` badge mean the sensor modules are off, not
that the console is broken. Cross-check Modules.

### Drive

**Shows** — a hold-to-walk pad, the mode that decides what may drive, and a one-step control.

**You can**

- **Hold** ▲ / ◀ / ▶ / ▼ to walk, and release to stop. While held the client renews the command every
  150 ms; the server expires any command 300 ms after the last renewal (`web/lib.js:21`). Releasing
  also sends an explicit `stop` command, so the deadman is the backstop and not the mechanism.
- **STOP** in the middle, or the `Space` key — both **park** the dog. The client calls
  `POST /api/v1/stop`, which stops the motion in flight *and* sets the mode to `rest`, so it stays
  parked until a mode change rather than resuming on the next tick (#333).
- **Hiding the tab** stops the motion the tab was commanding and leaves the mode alone.
- **Change the mode**, labelled with what it means: `idle - autonomy on` (behaviour and the navigator
  may drive), `manual - you drive` (clients may, autonomy may not), `patrol - roams` (the navigator
  roams), `rest - parked` (only stop and the watchdog get through). This posts to `/api/v1/mode` and
  changes the whole dog.
- **One step**: speed 60–200 in steps of 10, one to five steps, forward or backward. That path sends
  `wait: true`, so the HAL finishes the step before the answer returns — it is the control to use
  when measuring distance, and there is no queue behind it.

**Handing control back.** The brake and the throttle are the same control: parking is `rest` and
handing the dog back to autonomy is `idle`. The command palette does both from the keyboard —
`Park the dog (mode rest)` and `Hand back control - autonomy on (mode idle)` — and the mode list on
this panel is the same two acts with their neighbours. There is no confirmation on `rest` -> `idle`:
one selection returns the dog to self-driving. From a shell, with the token read on the device:

```bash
TOKEN=$(cat ~/.houndmind/api_token)
curl -s -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
     -d '{"mode":"idle"}' http://127.0.0.1:8420/api/v1/mode      # {"mode": "idle"}
```

`GET /api/v1/mode` reads it back (`state:read`), and every change is published as `mode_changed`, so it
appears in the ticker. `rest` and `idle` are one selection apart in both directions — the route table
and what each mode admits are in [`CONTROL_API.md` §2](CONTROL_API.md#2-endpoints).

**Needs** — `move`.

**If it looks wrong** — an inline sentence, never silence: *Tilt latched: put the dog upright, then
clear it from the device*, or *Refused: `<veto>`* with the reason the interlock gave. A refusal is
the device working.

### Tricks

**Shows** — every action the repertoire reports (`GET /api/v1/repertoire`), grouped by the class the
**server** assigns from `config/actions.jsonc` — locomotion, posture, expression, non_motion.

**You can** run any action. Locomotion sits behind an **arm locomotion** switch, because that class
changes where the dog is and a stray click in a list of forty buttons is exactly how that happens.
Posture and expression run unarmed. Posing classes send `wait: true` so a second click cannot stack
behind a slow stand-up. Hovering a button shows its parameters.

**Needs** — `move`.

**If it looks wrong** — an empty list says why: no action is classified and the HAL reports none.
That is a config question, not a console one.

### Routines

**Shows** — the routines the runner actually loaded (not the files on disk), each with a step count,
plus a **refused files** table naming the file and the loader's own message.

**You can**

- **Run** a routine, or **Dry run** it. A dry run publishes nothing — it walks the step list one step
  a tick and reports what it *would* do (`behavior/routine_runner.py:257`). Nothing moves.
- **Stop the run**, which posts `/api/v1/stop` like every other stop.
- **Write a routine** in the JSON box. Save is judged by the loader's own validator, so a refused
  save names the step to fix. A saved routine is playable on the runner's next tick — `POST
  /routines` sets `routine_reload` (`services/api.py:1049`), so no restart is needed.
- Watch the **in progress** table: routine, state, step index, action, detail or veto, and whether it
  is a dry run.

**Needs** — `config` to write, `move` to run. With `modules.routine_runner.enabled: false` the routes
answer `503` and `/meta` stops advertising routines.

### Places

**Shows** — the taught catalogue: name, heading, distance, anchor, confidence; and any walk in
flight.

**You can** teach a place (name, heading in degrees, distance in cm, optional anchor and confidence),
**Go** to one, **Rename** it, or **Forget** it. *Go* sends `at_anchor` as a real boolean from the
checkbox: a walk across the room is refused unless you assert the dog is standing at the anchor,
because nothing on the device can verify that pose. A refused body lists every problem, not one.

A place taught from the **Map** panel — a pin — arrives here too, in the same table and the same
catalogue: its heading and distance were measured from where the dog stood to the point that was
clicked. This panel has no camera, so it cannot give a place a picture; teaching it from the map is
what does that.

**Needs** — `config` to teach or forget, `move` to go.

**If it looks wrong** — "nothing in flight" is the normal state, not an error. A `503` means
`place_navigator` is off; those routes then refuse rather than inventing a second writer.

### People

**Shows** — who the dog has been taught, and whether the identity module is running (with its
backend) or off (with the reason). "Identity off" and "nobody enrolled" are different sentences on
purpose.

**You can** enrol a name — one face in frame; the request is accepted (`202`) and the roster reports
the outcome — and **Forget** someone.

**Needs** — `admin`, **and** the identity module enabled. A paired phone gets a `403` here, and the
panel says which scope it lacks.

### Camera

**Shows** — the MJPEG stream, and a still on demand.

The panel never puts the device token in a URL. It asks for a short-lived **ticket**
(`POST /api/v1/camera/ticket`: one use, 60 s, `state:read` on a single frame) and puts that in the
query string, because an `<img>` cannot send an `Authorization` header. **Save still** downloads
through a blob, so the URL does not land in browser history with a credential in it.

**Needs** — `state:read`, and a vision module on the device that actually publishes frames.

**If it looks wrong** — "No frames. No vision module is publishing them - enable one on the device, or
read the reason it gave up in the Modules panel (vision_pi4 needs picamera2; vision needs Vilib)."
Nothing in the panel can fix that, and it is not a token problem: enable `vision_pi4` (Pi 4/5, and only
once `picamera2` is importable) or `vision`, and read the reason it is off from the Modules panel. There
is no camera-index config key to check (#332).

### Decisions

**Shows** — one record per tick, newest first: timestamp, the intent that won, who asked (`source`),
its confidence, and what refused it.

This is the panel that answers "why did it do that" without opening a log file. It polls every three
seconds while it is on screen, and the limit box takes 1–200 records.

**Needs** — `state:read`, and `modules.decision_log` running.

**If it looks wrong** — `503` here is a specific fact: "the decision feed is not running; enable
modules.decision_log" (`services/api.py:1590`). That is a different sentence from "no decisions
recorded yet", and the panel keeps them apart on purpose.

### History

**Shows** — the command audit (time, action, source, client, verdict) and the clients currently
attached (name, scopes, how long they have been quiet, last command).

**You can** — refresh on demand, raise the limit to 200, and, with `admin`, **Open a pairing window**
for a phone or a second browser. The code is six digits, valid five minutes, single use — hand it
over in person, and do not put it in a chat. A paired client cannot do this: opening a window needs
`admin`.

**Needs** — `state:read`; the pairing button needs `admin`.

### Map

**Shows** — the home map from the `document` on `GET /map`: rooms as labelled polygons, surfaces as
hatched fills, walls as lines, openings as breaks in them, and the cells the sonar filled as an
evidence layer. The map is drawn **nose up in the document's own frame** — `x` is the map's left
axis and `y` its forward axis, so nothing is transposed here — with the dog as a triangle at
`document.dog`. One square is `cell_size_cm`, and the note says whether the stride behind every
distance is `assumed` or `measured`.

Solid squares are floor (two or more hits in a cell); outlines are ground seen **once**, which is a
maybe rather than a floor, and the two are drawn differently on purpose. A truncated map says
`(truncated)`: an empty corner is "not sent", not "not mapped".

**You can** toggle the five layers (`cells`, `rooms`, `walls`, `surfaces`, `places`), `Fit` the map to the
canvas, zoom with `+`/`-` or the wheel, and **drag to pan**. Furniture drawn against a wall is part of the
`rooms` layer rather than a sixth toggle, because it is context for the floor it stands on (H3). The
view — scale and centre — is kept in `localStorage` under `houndmind.map.view`, so a reload comes back
where you left it; `Fit` throws it away. It polls every four seconds while visible, and **never while an
edit is unsaved**.

**Editing the walls (#309).** Four drawing modes for the walls, chosen from the row under the canvas:

| Mode | What a press does |
|---|---|
| `View` | pans — the default, and the only mode in which dragging moves the picture |
| `Wall` | drag from one end to the other; the draw snaps to 5 cm and **magnets to an existing endpoint** within 15 cm, so two walls meant to meet do meet. Hold `Shift` to constrain to the axis the drag is longer on. A wall shorter than 20 cm is refused |
| `Doorway` | click a wall to cut an opening through it, centred where you clicked, `doorway width` cm wide (80 by default). A doorway that would not fit inside its wall is refused, with the wall's length in the message |
| `Delete` | click a wall or a doorway to remove it |

`Undo` restores the previous walls-and-openings snapshot (up to 50 steps), and the chip beside the
buttons reads `unsaved` until **Save to device** writes the document with `PUT /map`. Saving is
optimistic: the document carries the `meta.rev` this copy was read at, a device that has moved on
answers `409` and the panel says to press **Reload** rather than overwriting somebody else's edit.
`Reload` re-reads the map and discards unsaved work, which is why the poll never runs while the chip
says `unsaved`.

**Rooms and surfaces (#308).** `Room` and `Surface` are lasso modes: click each corner (the points snap
like walls do) and click back on the **first corner** to close the polygon — no button to forget, and no
half-drawn room left behind when the tab closes. A closed room takes the name in the `room name` box, or
`Room N` when it is empty, and the next colour from a five-colour cycle; a closed surface takes the
`Surface` picker's value as both its name and its `step_scale`.

The two boxes beside `room name` take that room's real `width` and `depth` in centimetres. Both or
neither: half a rectangle is not a measurement, and a room drawn with neither is simply unmeasured —
the save is accepted, and the drawing labels it
`scale: not measured - run the room to measure it` under the name. That label reads the room's own
`size_cm`, never the document-wide `meta.scale_source`, because one measured room does not measure
the rest of the house.

`keep-out` acts on the room you have **selected** — in `View`, a click that does not pan selects the room
under the cursor (it gets an amber outline), and the button then reads `keep-out: on` or `off` and
toggles it. A keep-out room is drawn with a dashed red edge. `Delete` removes a room or a surface you
click, before it looks for a wall.

**Objects against a wall (H3).** `Object` stands a piece of furniture against a wall you have drawn. Pick
a `kind` from the list beside the boxes, type its size in the two `object cm` boxes — the first `along`
the wall, the second `out` from it — and click the wall where it should sit. The rectangle is centred on
the click, snapped to 5 cm and kept inside its wall; an object that would overhang the wall is refused
with the wall's length in the message, the way a doorway is. It is drawn on the side a room is drawn on
where one contains the wall, and it rides the `rooms` layer. `Undo` puts one back with everything else,
because the snapshot carries every user section. Nothing on the device reads an object yet: this is the
drawing the dog will be given, not a rule it obeys.

**Position and go (M5).** Two more modes, and the only two that involve the dog rather than the house:

| Mode | What a press does |
|---|---|
| `Pose` | drag the dog to where it really is. An amber ring marks the proposal and **nothing changes yet**; **Confirm position** sends it with `PUT /map/pose`, `Cancel` throws it away, and leaving `Pose` discards it too — a finger on a canvas is not a measurement |
| `Go` | click a point to **preview** the walk (`POST /map/preview`): the route is drawn dashed with its distance at the goal, and nothing moves. **Send route** then sends it (`POST /map/go`); a refused route draws a red cross at the point and prints the reason instead |

Confirming a position re-anchors odometry at that point and writes it into the map file, so it survives a
restart, and `localization` reports the `user` tier until the correction ages out (30 s) or the dog has
walked away from it. The chip in the header reads `pose: user` right after a correction and
`pose: dead_reckoning` when it has expired; the chip beside it shows the route — the refusal reason when
there is one, or `walking 2/5`. The dog itself is drawn from the `pose` on `GET /map`, which the device
has already converted into the map's frame: the panel never converts, so it cannot mirror the dog (#347).

**The map's own health, and the walk so far (M6).** The header carries a badge —
`map: loaded 4m ago · stride measured:hardwood · 0 conflicts`. It is the device's answer, not the panel's
guess: `loaded` and its age come from the module that read the file, `stride` from `odometry` (so a
calibration shows before the next save), and `conflicts` is what the loader could not take at face value —
the tooltip lists them, with the softer `notes` beside them. The faint dashed line behind everything is the
**breadcrumb**: the recent walk, one point per five centimetres and capped at 240 points. Confirming a new
position starts it again, because the points before a correction are in an origin that no longer exists.

A preview is what a keep-out room finally refuses: a goal inside one answers `goal_in_keep_out` and a walk
that crosses one `route_in_keep_out`, both naming the room. A dog already standing inside a keep-out room is
still allowed to plan its way out — the room keeps the dog out, it does not trap it.

**Pins: name the spot, and see its picture (M7).** `Pin` teaches a place. Click a point on the map, type a
name, and the device answers with the new place **and the camera's picture of it**: the panel draws a ring
with the name beside it and the 32x24 thumbnail above, and `GET /places` is where the picture comes from
(joined by the place's id). **Here** does the same at the dog's own position — "the dog is here, call it
the kitchen" — which is a place at zero distance, so asking the dog to go there arrives at once.

The pin itself is a `places[]` entry in this document, so it is **unsaved** until **Save to device**, like
every other edit here; `Undo` takes it back. `Delete` removes a pin from the map and leaves the place in
the catalogue, where `Places` is the panel that can Forget it. The `places` layer toggles the whole pin
layer, and the legend counts them.

The device needs three things for a pin to work, and each one fails with its own sentence: a vision module
publishing frames (`503 no camera frames are being published`), OpenCV on the device (`503 OpenCV is not
installed`), and something with texture in view — a blank wall answers `400` and says to point the camera
at something else. Teaching needs `config`, not `move`: it writes user data and moves nothing.


The chip beside the surface picker is the point of the whole exercise: `18.4 cm measured` when
`odometry.surface_step_cm` has a value for that paint, and `not measured` otherwise. The panel cannot
read the config, so `GET /map` publishes that table beside the document (see `docs/CONTROL_API.md`); a
surface painted `hardwood` is then walked at the length someone measured on hardwood instead of the
assumed one. Nothing is invented: no calibration, no number.

**Needs** — `state:read`.

**If it looks wrong** — "no map" with *no sweep has filled a cell yet* means the mapper has recorded
nothing; a device whose `mapping.grid_enabled` is off or whose map file is empty reads the same way,
and `python -m tools.map_inspect data/home_map.json` prints what the file actually holds. The dog
triangle comes from the document, **not** from the live `localization.pose`: the runtime's pose is
`(forward, left)` while the document's is `(left, forward)`, so plotting the live pose on this frame
would mirror it (#347). Walls and doorways are editable here, and so are rooms, surfaces and keep-out;
correcting the pose and clicking a goal are M5.

### Modules

**Shows** — every component, its state, its per-tick cost in `tick_ms`, and the reason it is not
running. The chip above the table counts loaded / disabled / failed.

**You can** refresh; it polls every four seconds while visible.

**Needs** — `state:read`.

**Reading it** — `disabled` is normal and expected: vision ships off, and a module with a missing
wheel or no camera disables itself with a reason. `failed` is a bug. The two are drawn in different
colours so the one that matters is not invisible. Rising `tick_ms` values are a performance question,
not a hardware fault — `docs/TROUBLESHOOTING.md` has the loop-overrun path.

### Config

**Shows** — the live keys the server says can be changed, and the whole document with secrets
redacted.

**You can** edit a live key and press **Apply changes**.

**Needs** — `config`.

**Three rules the panel itself enforces**

- Only **live** keys are offered. Anything else is read-only here, because the runtime reads it once
  at start.
- A redacted leaf (a password, a token path) is never turned into an input: sending `***` back would
  overwrite a real secret with three stars.
- The answer carries `persisted: false` and the panel says so: a change made here dies with the
  process. To keep it, edit `config/settings.jsonc` and restart (`docs/INSTALL.md`).

### Calibration

**Shows** — the stored servo trim (`servo_zero_offsets`) and whether it is applied automatically at
start.

**You can** run the read-only probes the route advertises. The probe list is not hardcoded in the
page: it is discovered from the route's own refusal, so the console can never hold a second copy that
drifts.

**Needs** — `config`.

**Nothing here writes an offset and nothing here moves the dog.** Applying and editing calibration is
a device procedure (`calibration/` and `src/tools/`); the console only reports.

### Logs

**Shows** — the runtime's own JSON log lines: time, level, logger, message, and the trace id when the
record has one.

**You can**

- Set the tail (10–500 lines), a level, and a substring to search for. The filter is a **server-side
  query** over the file, not a filter of what happened to be on screen, so a match older than the
  tail is still found.
- Watch it live: with no filter set, new lines arrive over the socket and the chip says `live`. Set a
  filter and the chip says `filtered`; the two are never mixed.
- **Download the support bundle** (logs, `config/settings.jsonc` and run metadata, zipped).

**Needs** — `admin`, which a paired client does not have; the panel says so rather than showing an
empty box.

**Before you share a bundle** — it contains `config/settings.jsonc` **verbatim**, WiFi credentials
included. Read it first.

## 6. What the console cannot do

The console is a **client**. It renders what the device publishes and submits what you ask; it never
decides whether the dog moves. Every press becomes a typed intent on the device's intent board, and
`act/gateway.py` resolves the competing intents in priority order before the interlock answers. The
console shows that answer and never bypasses it.

| The console cannot | Because |
|---|---|
| force an action past a veto | a veto is the interlock saying no; it is displayed, not overridden |
| clear a latched tilt | that is a physical condition; put the dog upright and clear it on the device |
| enable a safety module or silence a watchdog | those are config decisions, made in `config/settings.jsonc` |
| write a servo offset | calibration is a device procedure, not a web form |
| keep the dog moving when the link drops | see the three stop paths below |

**Three stop paths, and the deadman behind all of them**

1. Releasing the pad (or the key) issues a `stop` **command** (`POST /api/v1/command`): the motion in
   flight ends and the mode is untouched, which is what makes hold-and-release driving work.
2. Hiding the tab does the same (`web/app.js:566`).
3. If neither happens — a laptop lid closes, WiFi dies — the command simply expires: the client renews
   every 150 ms and the server drops a command 300 ms after the last renewal (`web/lib.js:21`). A
   client that stops pinging loses its command after `settings.api.link_loss_s` (6 s).

A routine is not an exception: it plays one step per tick through the same gateway, so the interlock,
the obstacle stop and the mode gate apply to it exactly as they do to a hand on the pad.

**STOP is the fourth path, and the only one that parks.** The STOP button, `Space` and the palette's
`Stop the dog` call `POST /api/v1/stop`, which stops the command *and* sets `rest` (#333). With
autonomy on — the `idle` mode — the behaviour and the navigator publish a fresh intent on the very
next tick, so a path that only cleared the motion in flight held for about a tenth of a second and the
dog walked on. `rest` is the mode the gateway refuses to drive in, so the press sticks until a mode
change; `manual` is the other way to keep autonomy out while leaving the pad working.

**A restart is not a resume — and not a park either.** After `systemctl restart houndmind` or a reboot,
a gait in flight is gone and a routine that was mid-run is lost rather than replayed. But the runtime
comes back in `mode idle`, where behaviour and the navigator may drive, so a dog with
`modules.behavior` enabled can start moving again on its own. Parking is a mode, not a restart: set
`rest` (or `manual`) once it is up.

## 7. Install it on a phone

The console is a small web app: it can be added to a home screen and opens without browser chrome.
That needs a **secure context** — HTTPS with a certificate the phone trusts, or `localhost`. On plain
HTTP the manifest is ignored and the service worker never registers; the console still works, it
just cannot be installed (`web/lib.js:80`).

| Platform | Steps |
|---|---|
| Android (Chrome) | menu ⋮ → *Install app* (or *Add to Home screen*) |
| iOS (Safari) | Share → *Add to Home Screen* |
| Desktop (Chrome/Edge) | the install icon in the address bar |

The installed shell is cached so the icon opens instantly and survives a device restart; **API
responses are never cached** (`/api/*` is excluded), so nothing it shows is stale data pretending to
be live. The token still lives in the tab's `sessionStorage`, so expect a fresh launch to ask for it
again — for a phone, open a pairing window and use the code ([§2](#2-first-connection)) rather than
pasting the device
token.

## 8. Desktop notifications

The **notify** button appears only in a secure context, because the browser's `Notification` API
requires one. Nothing is requested on page load: the permission prompt happens on your click, once,
and a refusal turns the button into `notify blocked`.

When granted, three events raise a desktop notification — the same three the ticker tints:

| Event | Means |
|---|---|
| `command_vetoed` | the interlock refused a command |
| `command_expired` | a command ran out of TTL before the dog acted |
| `safety_action` | a safety module acted |

A notification is a **second signal, never the only one**: the ticker records every event whether or
not the browser allows notifications, and the dog's own stop path is on the device. If notifications
stop arriving, check the badge first — an `offline` console raises nothing.

## 9. Several dogs

The header picker lists the dog this page was served by, plus any you have added. *add a device…*
asks for the other console's URL once.

Choosing one **navigates the tab** — it is a full page load at that dog's origin, not a cross-origin
fetch. That is deliberate: each device serves its own console and bundle, each keeps its own token in
its own origin's `sessionStorage`, and nothing needs CORS. It also means mixed deployments (one dog
on HTTPS, one on HTTP) do not break.

The list of URLs lives in `localStorage` (`houndmind.devices`); tokens never do. Switching to a dog
asks for that dog's token again in the new tab, and *that* is the same per-tab rule as
[§2](#2-first-connection) rather than
a new one.

## 10. When it will not load

Find the symptom, take the row. The first two commands answer most of them.

```bash
# on the device
systemctl is-active houndmind
journalctl -u houndmind -n 50
ss -ltnp | grep 8420
```

| Symptom | Cause | Do |
|---|---|---|
| Browser cannot reach the site | nothing is listening: the runtime is stopped, or `api` disabled itself | the three commands above; the journal carries the module's own reason |
| Connect card appears again | this tab has no token — a new tab, or **Disconnect** was pressed | paste the token, or pair |
| "Token rejected - paste the device token again" | wrong token, or it was rotated | re-read `~/.houndmind/api_token` on the device |
| One panel says the token lacks a scope | a paired client hitting an `admin` route | use the device token for People, Logs and the bundle |
| "Not running on the device: …" | the module that serves that panel is off | the detail names it: routines → `routine_runner`, decisions → `decision_log`, places → `place_navigator` |
| Badge says `no stream`, the rest works | the WebSocket is blocked while plain HTTP passes | usually a proxy without `Upgrade` support — connect directly |
| Badge says `no frames` | WiFi | the panels keep their last values; they are frozen, not wrong |
| Every instrument is a dash | the sensor modules are off | Modules panel |
| Camera: "No frames" | no vision module is publishing frames | enable `modules.vision_pi4` (needs `picamera2` importable) or `modules.vision`; Modules carries the reason it is off |
| Map: "`mapping.grid_enabled` is off" | mapping is off | `config/settings.jsonc` |
| Nothing at all after a reboot | the unit is installed but not enabled | `sudo systemctl enable --now houndmind` |

Confirm the boot contract. This is the whole difference between "it works today" and "it works after
the next power cut":

```bash
systemctl is-enabled houndmind                       # expect: enabled
systemctl cat houndmind | grep -A2 '\[Install\]'    # expect: WantedBy=multi-user.target
systemctl show houndmind -p ExecStart               # the runtime command
```

`is-enabled` is the check that matters; `systemctl show -p WantedBy` prints an **empty** value while
the unit is disabled, because it reports the links that exist rather than what the file asks for. The
`[Install]` line is what `enable` creates, and `ExecStart=… -m houndmind_ai.main` is the runtime.

One timing note that reads like a fault and is not: for the first few seconds after a start there is
no listener on 8420, because `api` is the last module registered. Give it ten seconds before
believing `ss`.

If the unit is missing entirely,
[`INSTALL.md` §*The service: what starts at boot*](INSTALL.md#the-service-what-starts-at-boot) has the
manual install, and `packaging/systemd/houndmind.service` is the template it renders.

**One honest limitation.** The control plane runs *inside* the runtime process. systemd restarts the
process if it exits (`Restart=on-failure`), and the watchdog restarts other modules. A plane whose
thread *exits* is now noticed by the module itself and restarted through the runtime (#330), so
"the console stopped answering" after a crash is a recovery rather than a mystery. What is still
uncovered is a plane that hangs with its thread alive: the process looks healthy, the thread is up, and
the watchdog is configured not to touch `api` (`settings.watchdog.ignore_modules`). When that happens
`sudo systemctl restart houndmind` is the fix, and the gap is **#338**.

## 11. Security

The console is the only network surface the device has, and on plain HTTP it is a plaintext one. Read
this before putting the dog on a network you do not control.

| Fact | Consequence |
|---|---|
| `tls_enabled: false` by default | the token, every command and every camera frame cross the LAN in the clear |
| The device token is the whole boundary | whoever holds it is the operator, with `admin` |
| `/api/v1/health` and `/api/v1/meta` need no token | they expose liveness, version and identity only |
| `/api/v1/pair` (submitting a code) and `/api/v1/events` (auth in its first frame) are open | a code is single-use and dies in five minutes |
| Camera URLs carry a one-use ticket, not the token | the token never enters browser history or a proxy log |

Three ways to close the door, cheapest first:

1. **Trust the network.** A LAN nobody else is on. Not a café, not a shared flat, not a hotel.
2. **Bind to loopback** — `"host": "127.0.0.1"` under `settings.api` — and reach it through an SSH
   tunnel: `ssh -L 8420:127.0.0.1:8420 pi@<pi-address>`, then open `http://127.0.0.1:8420/`.
3. **Turn TLS on** — `"tls_enabled": true`, and trust the generated certificate once per client
   ([`INSTALL.md` §*TLS*](INSTALL.md#tls-for-the-control-plane-optional) documents the browser, phone
   and `curl` steps).

Never port-forward 8420 to the internet, never paste the token into a URL or a screenshot, and read a
support bundle before sharing it: it contains `config/settings.jsonc` verbatim, WiFi credentials
included. `docs/SECURITY.md` covers what the device exposes and how to report a problem.

## 12. Where the facts live

| Question | Read |
|---|---|
| What does this route accept and return? | [`CONTROL_API.md`](CONTROL_API.md) — the contract |
| What does the control plane do, and what are its defaults? | [`FEATURES_GUIDE.md` §26](FEATURES_GUIDE.md#26-control-plane--rest-websocket-camera-web-app) |
| How do I install it, enable the service, or turn TLS on? | [`INSTALL.md`](INSTALL.md) |
| Something is broken and I do not know which file owns it | [`TROUBLESHOOTING.md`](TROUBLESHOOTING.md) |
| What do the log fields mean? | [`LOGGING.md`](LOGGING.md) |
| Every config key, with a comment | `config/settings.jsonc` |
| Which actions exist and what they cost | [`REPERTOIRE.md`](REPERTOIRE.md) |
| The routine file format | [`ROUTINES.md`](ROUTINES.md) |






