// The panel registry: the single list the rail, the router and the palette all read.
//
// Order is the rail order, and it is the operator's path: see the dog, drive it, then the things
// that need setting up. `id` must match the `data-panel` attribute in index.html; a panel with no
// section is a registry entry that silently never renders, so the two are checked by eye here and
// by `tests/test_webapp_coverage.py` for the routes each one calls.

import { overview } from "./overview.js";
import { drive } from "./drive.js";
import { tricks } from "./tricks.js";
import { routines } from "./routines.js";
import { places } from "./places.js";
import { people } from "./people.js";
import { camera } from "./camera.js";
import { decisions } from "./decisions.js";
import { history } from "./history.js";
import { map } from "./map.js";
import { modules } from "./modules.js";
import { logs } from "./logs.js";
import { config, calibration } from "./setup.js";

export const panels = [
  overview,
  drive,
  tricks,
  routines,
  places,
  people,
  camera,
  decisions,
  history,
  map,
  modules,
  config,
  calibration,
  logs,
];
