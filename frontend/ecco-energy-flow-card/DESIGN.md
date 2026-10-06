# ECCO Energy Flow Card - design notes

Status: **live-tested and visually approved.** This document records the
decisions behind the design so they remain reviewable alongside it - it
predates the card's approval and is kept as design history, not a
polished spec.

## Update 2026-09-26 (Dump-to-Grid V1.1 investigation) - Home-power data fix, no visual change

A live Dump-to-Grid proof exposed Home reading exactly 0W while the energy
balance made that implausible (PV 763W, battery 632W discharging, inverter
AC out 1.24kW, grid 1.81kW importing). Two contributing facts: register 178
(`ecco_load_power`) is documented as unreliable/zero in some inverter
states (see `docs/DUMP_TO_GRID_V1.md`), and this card's own `homeW`
computation collapsed a genuinely unavailable reading and a genuinely zero
reading into the same displayed 0W with no fallback, unlike Grid and
Inverter.

Fix, in `src/config.ts`'s new `resolveHomeW()` (not the render path
itself - a pure, independently testable function, see
`test/homePower.test.ts`): prefer the native reading whenever credible;
fall back to `inverter_ac_output + grid_power` (this card's internal sign
convention) only when native is unavailable, or is exactly 0W while the
derived balance clearly implies real load (a 150W margin past ordinary
jitter, so a genuinely quiet site is never overridden). Clamped to >= 0.
Data-layer only - the frozen visual design below is untouched, and the
node/route geometry, colours and animation are unaffected.

## Update 2026-09-26 (final checkpoint) - true-port geometry, asymmetric composition, Grid 5-state + pylon pulse

The maintainer has approved the redesign at ~99.5%; the visual design is now
frozen. This entry summarizes the rounds after round 15 (below) that
never got their own diary entry written at the time, kept brief rather
than a further blow-by-blow, since the point of this checkpoint is to
record the final state, not replay every iteration.

- **TRUE PORT GEOMETRY**: round 15's calibrated per-connection insets
  (`INVERTER_PORT_VERTICAL`/`BATTERY_GRID_PORT`/etc.) were replaced
  entirely. Every connection point now renders a real, tiny `[data-port]`
  DOM element at its own actual edge; after every layout-affecting render
  the card measures each one's real `getBoundingClientRect()` centre (a
  `ResizeObserver` re-measures on any size change) and builds every route
  directly from those live coordinates. No guessed/calibrated inset
  remains anywhere except `PORT_UNDERLAP` (0.4 logical units, purely an
  anti-aliasing seam pull-in). Verified repeatedly via live port-to-
  path-endpoint distance measurement in a local preview harness -
  consistently ~0.35-0.50px, well under a 1.5px error budget.
- **Asymmetric composition**: `_layout()` deliberately moved away from
  the round-12/round-14 literal cross/plus shape - the inverter sits
  right of centre, and Battery/Grid/Home each occupy their own distinct
  height/distance from it instead of mirroring each other. The two Solar
  arrays remain the one deliberately mirrored pair. This is a
  position-only concern; TRUE PORT GEOMETRY means the routing layer never
  needs to be kept in sync with layout changes by hand.
- **Energy-ball secondary animation layer**: an earlier attempt at native
  SVG `<animateMotion path="..."> `/`<mpath href="#id">` (the mechanism
  round 14's chevrons and round 15's particles both used) was abandoned
  after live testing showed it does not reliably resolve a fragment
  `href` across this card's shadow DOM boundary in practice - the target
  path existed and the SMIL clock advanced, but the riding element's own
  `transform` never actually updated. Replaced with a small
  `requestAnimationFrame` loop that reads each ball's target `<path>` by
  id every frame and positions it via `getPointAtLength()` directly - no
  fragment reference of any kind, consistent with this file's
  long-standing avoidance of `url(#id)` SVG references. Ball count (1 at
  low power, up to 4 at 6kW+) and duration both scale with magnitude, on
  their own dedicated range distinct from the dash texture's.
- **Magnitude curve, heavily compressed at the low end**: live feedback
  was that the existing log-normalized curve still made a 20W trickle and
  a several-hundred-watt flow both look fairly active. The curve's
  normalized output is now additionally raised to a fixed exponent (>1)
  before use - mathematically a fixed point at the curve's own ceiling
  (any `x^n` = 1 when `x` = 1), so high-power behaviour is unchanged,
  while the everyday low/mid band is pushed disproportionately further
  down. Applies uniformly to dash speed/density, ball speed/count, and
  the pylon pulse (below).
- **Grid's 5-state model + pylon pulse**: Grid gained two states beyond
  the existing importing/exporting/idle - "disconnected" and
  "unavailable" - sourced from the SAME `inverter_details.grid_connected`
  entity the quick-metrics strip and details panel already read (no new
  entity invented). 0W flow is never itself treated as a fault; "idle"
  was narrowed to specifically mean "connected and confirmed ~0W" (a
  muted steel-blue, not the flat grey it used to be), and that grey moved
  to "unavailable" (the connectivity signal or the power reading itself
  can't be read). "disconnected" only fires on a real off/false signal
  from `grid_connected`, never inferred from the power reading alone. The
  Grid node's own pylon graphic (not the whole node box) gets a smooth
  `filter: brightness()`/`drop-shadow()` breathing pulse - never a hard
  blink - reinforcing the same state: magnitude-scaled speed while
  importing/exporting, a slow fixed heartbeat while connected-idle, a
  distinct, slightly quicker fixed cadence while disconnected, and no
  pulse at all while unavailable. All of it disabled under
  `prefers-reduced-motion`, alongside the existing dash/ball rules.

### Live-deployed and approved, this checkpoint commits it

Built and typechecked clean, deployed the same backup/stage/SHA256-
verify/`ha core check` sequence as every prior round, live-reviewed by
The maintainer at ~99.5% approval. This is the first round in this file to actually
land as a git commit - every round from 4 through this one was developed
and live-reviewed directly on this branch's working tree without an
intermediate commit, per the maintainer's own iteration process.

## Update 2026-09-25 (round 15) - UniFi-style particles, node identity, solar-box fix

An integrated polish pass on round 14's baseline (NOT a redesign) combining
The maintainer's own live feedback with a ChatGPT critique of the same screenshot.
The composition/layout from round 12 and the routed-bus system from round
13-14 both stand; this round changes the motion language, softens the
Solar/Home offset, gives nodes more distinct silhouettes, and fixes a
real, confirmed text-overflow bug in the solar box.

### Chevron markers replaced with UniFi-style glowing particles

The maintainer explicitly referenced his Ubiquiti/UniFi topology flow view: "the
line itself should communicate movement" via small luminous packets, not
a travelling arrowhead - round 14's chevron `<polygon>` markers still read
as small arrowheads, which was the wrong shape family entirely, not a
sizing problem. Replaced with plain `<circle>` particles - a symmetric
shape has no "pointing" direction of its own, so direction comes purely
from the motion itself, exactly the UniFi principle. Count (1-3), radius,
and opacity all scale gently with the same `t` (magnitude fraction) that
already drove line thickness/speed - sparser/dimmer/smaller near idle,
denser/brighter/larger at high power, kept to small ranges so it never
reads as a conveyor belt. Each still rides its own
`<animateMotion path="..." rotate="auto">` bound directly to the line's
own `d` (unchanged mechanism from round 14 - the path-following and
no-`url(#id)`-reference reasoning both still apply, `rotate="auto"` is
just inert on a circle now). A soft `drop-shadow(currentColor)` glow was
added - deliberately small (2.5px) per the maintainer's own "avoid excessive glow
spam" caution. CSS class renamed `.flow-motion-marker` -> `.flow-particle`
throughout, with no old-name references left behind.

### Solar/Home offset softened

`SOLAR_HOME_OFFSET_X` 26 -> 18 per live feedback that the bend read a
little too crooked. Still a genuine, deliberate, complementary two-axis
offset (Solar left, Home right of the inverter's centreline) - just less
pronounced.

### A real, confirmed solar-box layout bug, fixed

The array box's `.array-row` (label, panel strip, value all sharing one
flex row) had a genuine overflow bug at its current 236px width - measured
live, `.array-row-value` extended ~28px past the box's own right edge,
because the panel strip and the value text were competing for the same
~36px of leftover horizontal room. This was a real bug, not a preference.
Restructured to two lines per row: `.array-row-header` (label + value, now
given the row's FULL width with nothing to compete against) sits above
`.panel-grid` (also full row width) instead of beside it. This isn't just
a width fix - it reads more like an actual array readout (a heading over
its own panel diagram) than a cramped single-line stat, and let the panel
cells themselves grow (8x14 -> 15x14px) for better legibility.

Going to two lines per row costs real vertical space the old single-line
version didn't need, and the box grew from 75px to 132px tall as a direct
result - confirmed live, this created a brand-new Solar/Inverter box
overlap at 380px/420px that didn't exist before. Every row/box padding
and gap value was then tightened as far as it reasonably could be (saving
~18px back, down to 114px), and the remaining height increase was
absorbed by growing `ARRAY_TO_INVERTER_GAP` (92 -> 108) and recalibrating
`SOLAR_PORT` (17 -> 27, the box's own new half-height) - re-verified
live afterward: zero overlaps at 420/760/840px, and the only overlap
remaining at 380px is the same long-standing Battery/Grid-vs-Inverter
tightness every round since 12 has already noted and accepted below this
card's realistic minimum width.

### Node identity - Grid gets a distinct, more rectilinear shape

Adding a literal "terminal nub" DOM element to Battery for a stronger
battery-cell cue was considered and deliberately dropped: `.battery-box`
already uses both `::before` (the charge/discharge shimmer sweep) and
`::after` (the SOC background fill) pseudo-elements, so a third visual
element would need real DOM/markup changes, and the box's existing
`overflow: hidden` (required to contain the shimmer) would clip anything
positioned to protrude past the box like a real terminal bump does -
solvable, but a bigger structural change than "subtle cue" warranted for
this pass, with real risk of a subtly broken shimmer if rushed. Battery
already carries enough of a "cell" identity via its existing SOC bar,
flatter-top/rounder-base radius (round 8), and charge/discharge shimmer -
left unchanged, not regressed.

Grid, which had no shape treatment of its own (inheriting the generic
12px node radius), got one: `border-radius: 6px` - tighter and more
rectilinear than Battery's rounded-cell shape or Home's own asymmetric
roofline radius (round 12), a small, safe, "infrastructure/utility
cabinet" cue rather than a soft consumer-device shape. Three now-distinct
silhouette languages (cell / utility / roofline) without any of them
becoming literal clip-art icons.

### Verified via a parallel Workflow, not just spot-checked

Given the size of the explicit test matrix (particle motion + reversal
for Battery/Grid, Solar/Home direction + the box-overflow fix + offset,
node identity + live-value non-regression, responsive/collision at three
widths, reduced-motion CSS + idle behaviour), this round again used the
Workflow tool to run five independent verification agents in parallel
against the same running local preview harness.

Four of five passed outright. The fifth (responsive/collision) caught a
real, serious bug the other checks and my own eyes both missed: the
solar-array box's own height increase (see the fix above) pushed its top
edge to a NEGATIVE y-position relative to the `.flow` container at 380px
(-35.9px) and 420px (-33.7px) - and because that box sits later in DOM
order than the card's own `<h1 class="card-title">` with a solid-ish
background, it was visibly painting over the bottom ~22px of "ECCO Energy
Flow" at both widths, not just abstractly overlapping a bounding box.
This is categorically worse than the long-accepted Battery/Grid-vs-
Inverter tightness at 380px (an internal collision between flow nodes) -
it obscures the card's own title, and it happened at 420px, a width this
whole project has otherwise treated as fully realistic.

Root cause: `ARRAY_Y = INVERTER_Y - ARRAY_TO_INVERTER_GAP` had drifted
close enough to `y=0` (the coordinate space's own top edge, with nothing
reserved above it) that the box's now-larger half-height no longer fit
above its own centre point. There is no way to fix this without growing
the total canvas - reserving headroom above Solar and shifting the whole
cross down by that same amount are the same change, not two options -
so `INVERTER_Y` grew 128 -> 180 this round specifically to create that
headroom (this constant now needs to satisfy THREE constraints
simultaneously: real clearance below Solar down to the inverter, real
clearance above Solar up to `y=0`, and everything below the inverter
keeping its own already-tuned spacing - solved for the narrowest
constraint, then re-verified empirically, not re-derived by further hand
calculation, given how fragile that hand math had already proven this
session). Diagram height grows from 252 to 304 logical units as a direct,
necessary consequence - re-verified live afterward: solar's top edge now
sits 19-111px clear of the flow container's own top across all four
tested widths (was -35.9px at the worst case), zero title overlap
anywhere, and the same port-precision re-check from earlier in this round
(sub-2px at every connection) still holds since insets are relative
distances, unaffected by the shared Y-offset.

## Update 2026-09-25 (round 14) - moving direction markers, real ports, Solar/Home bus routing

The maintainer's live verdict on round 13: broadly the right direction, but (1) arrowheads
were in the wrong places, (2) Solar/Home still read as plain straight lines
while Battery/Grid got the real bus-routing treatment, (3) route
terminations needed to be cleaner (not masked deep under a box), and (4)
he wants the direction indicator to visibly MOVE through the route, not
sit static. This round is a routing-polish pass on round 13's system, not
another redesign - the three-case `_line()` architecture (STRAIGHT / LANE
JOG / ELBOW) is unchanged; what changed is which case Solar/Home hit, how
precisely every route terminates, and how direction is shown.

### Solar and Home now use real bus routing too

`_layout()` offsets `solarArrayNode` `SOLAR_HOME_OFFSET_X` (26 units) LEFT
of the inverter's centreline and `home` the same amount RIGHT - a
deliberate, complementary (opposite-direction) offset, not a random
nudge, so the two together read as one diagonal current through the
inverter (source upper-left, load lower-right) while Battery/Grid stay
the clean horizontal axis. Once Solar/Home are no longer perfectly
X-aligned with the inverter, `_line()`'s existing ELBOW case (a single
`roundedCorner()` bend, previously only reachable via a fanned-out 3+
solar array or the optional Generator arm) applies to them automatically
- no new geometry code needed, just a different starting position feeding
the same, already-correct machinery. The single-source solar fallback
gets the identical offset for consistency; a genuine 3+ array fan-out
needed no change (it already produces real elbows from its own fan-out
geometry).

### One shared corner radius

`JOG_RADIUS`/`ELBOW_RADIUS` (10/22) collapsed into one `ROUTE_RADIUS = 20`
- The maintainer's explicit "consistent bend radius" ask. `roundedCorner()` already
clamps a requested radius down to at most half of the shorter adjoining
leg, so the lane jog's short 16-unit middle segment still naturally
renders tighter than a full elbow's much longer legs - one constant, two
organically different results from the same geometric rule, not two
independently-tuned numbers that happened to differ.

### Ports calculated from actual node dimensions, not guessed

Every route previously used the same flat 20-unit pullback from each
node's centre regardless of that node's real size, which is exactly what
The maintainer flagged - lines disappeared 15-18px under the inverter box instead
of meeting its edge. Measured every node's ACTUAL rendered half-width/
half-height via `getBoundingClientRect()` against the real built card in
a local preview harness (not estimated from source), and gave each of the
four primary connections its own calibrated inset pair:
`INVERTER_PORT_VERTICAL` (26, for Solar/Home's arrival/departure on the
inverter's top/bottom edge), `INVERTER_PORT_HORIZONTAL` (38, Battery/
Grid's left/right edge), `BATTERY_GRID_PORT` (31, each node's own
inverter-facing edge), `HOME_PORT` (13), `SOLAR_PORT` (17). Re-measured
after the change: Battery/Grid/Home now land within ~1px of the actual
box edge (was ~15-18px under it); Solar within ~3px. Node sizes are fixed
CSS pixels while these insets are logical units mapped onto a
variable-width container, so no single value is exactly right at every
card width - these are tuned against the card's typical rendered size, a
real, measured improvement over the previous one-size-fits-all inset, not
a claim of pixel-perfect precision at every possible width.

### Moving direction markers replace the static arrowhead as the primary indicator

Each active (non-idle) line now carries two small chevron markers, each
riding its own `<animateMotion path="..." rotate="auto">` bound directly
to that line's own `d` string. The browser's own path-following
implementation handles every straight run and every rounded bend
uniformly - no manual per-segment angle math, and no risk of the marker
"jumping" at a corner, satisfying the maintainer's own suggestion to use the actual
SVG path as the motion path with automatic orientation rather than
guessing angles. Deliberately `path="..."` (an inline path string) and
not `<mpath href="#id">` - an inline path needs no referenced element, so
it carries none of the fragile browser/shadow-DOM `url(#id)` risk a
`<marker>` or `<mpath>` reference would (this file has avoided that whole
risk category since its very first live-rendering bug, long before this
round - see the earlier "why lines weren't rendering" history above).

Both markers share the same magnitude-scaled `duration` the dash texture
already used (deliberately - the moving chevrons and the dash pattern now
read as one coherent flow rather than two independently-timed effects),
staggered by half a cycle so there's a continuous rhythm rather than one
lone chevron. Idle lines get zero markers - nothing is flowing, nothing
should move.

The old static arrowhead is now hidden by default (`.flow-arrow { opacity:
0 }`) - showing both would duplicate the same information the moving
markers already carry - and reappears in exactly two cases: an idle line
(nothing moving to show direction with) and under `prefers-reduced-motion:
reduce` (no travel animation to rely on there either; `.flow-motion-marker`
is `display: none` in that same media block). Verified this round (see
below) both live in the harness AND by reading the actual emitted CSS
rule text, since this session's browser tooling has no way to force the
OS-level reduced-motion preference for a true end-to-end check.

### Verified via a parallel Workflow, not just spot-checked

Given the size of the explicit test matrix the maintainer asked for (Battery
discharging/charging/idle, Grid importing/exporting/idle, Solar/Home
direction, three card widths, reduced-motion), this round used the
Workflow tool to run five independent verification agents in parallel
against the same running local preview harness, each in its own browser
tab: battery-state reversal (proving the charging path's point sequence
is exactly the discharging path's reversed, corner-for-corner, not just
asserting it), grid-state reversal (same rigor), Solar/Home direction +
offset (confirming both are genuine two-axis elbow routes now, offset to
opposite sides of the inverter, direction never reversing), responsive/
collision at 380/420/840px, and the reduced-motion CSS text check.

Two real, concrete findings came out of it, both fixed and re-verified
before deployment:

- **Solar/Inverter genuinely overlapped at 380px** (a ~4.3px box-on-box
  overlap, not just a tight inset) - `ARRAY_TO_INVERTER_GAP` 84 -> 92 and
  `HOME_GAP` 78 -> 84 (Home was a 0.25px near-miss at the same width)
  restore real clearance there without changing anything at 420px/840px,
  where there was already no overlap. Diagram height grows by 6 units
  (246 -> 252) as a direct result.
- **The grid-idle check failed - because of this session's own local test
  harness, not the card.** The harness's "Idle / Night" mock scenario set
  `sensor.grid_power` to 310 (still importing to cover the load), so
  clicking that button never actually exercised the card's grid-idle
  styling/routing at all - a gap in test-harness data, not a card defect.
  The verification agent independently confirmed the card's own idle
  logic was already correct by overriding the value directly. Fixed the
  harness itself (grid_power and house_power both dropped under the 5W
  idle threshold in that scenario) and re-confirmed live: Grid now
  correctly renders `colour-grid-idle` with zero motion markers when that
  button is clicked, same as Battery already did.

The other three dimensions (battery-state reversal, Solar/Home direction,
reduced-motion CSS) passed on the first pass with no issues found.

### Not touched

`_layout()`'s core cross topology and the round-12 sizing work, entity
mapping, sign-convention normalisation, the colour/state system,
power-scaled thickness, idle behaviour beyond adding "no motion markers"
to it, click/more-info behaviour, and the quick-metrics/details-panel work
from round 12. The dashboard YAML's `show_details_panel: false` (added
round 13) is unchanged and was not redeployed this round unless this
round's own report says otherwise.

### Live-deployed for review, not yet committed

Built and typechecked clean. Deployed the same way as every round since
11 (direct to `/config/www/ecco-energy-flow-card.js`, the proven backup/
stage/SHA256-verify/`ha core check` sequence). Not committed - the maintainer
reviews live again before anything lands.

## Update 2026-09-25 (round 13) - wiring-style routing, from scratch

Round 12's compositional fix landed well, but the maintainer's live verdict on the
route SHAPE itself was blunter: the organic Bezier curves (rounded arcs/
S-curves, introduced round 11, retuned round 12) still read as "the old
schematic with curves added" rather than "a polished inverter-app's
routed wiring". This round replaces the curve system entirely with
rounded-orthogonal routing - structured horizontal/vertical runs with
rounded elbows, the real visual language of PCB/schematic bus routing -
per an explicit, detailed brief. Composition/layout/sizing from round 12
is untouched; only the route SHAPE and two config files changed.

### Three route shapes, not one curve family

`_line()` was rewritten around a single shared primitive,
`roundedCorner()` (a module-level pure function - "centralise the
radius/port/lane logic" per this round's own brief) - given a sharp
corner and the two points either side of it, it returns where a
radius-clamped quadratic curve should begin and end on each adjoining
leg, clamped to at most half of whichever leg is shorter so it can never
overshoot into a degenerate curve on a short segment.

- **STRAIGHT** (Solar, Home): each already leaves/arrives via its own
  edge dead-on - Solar's lower edge straight down into the inverter's top
  port, Home's top edge straight up into the inverter's bottom port -
  nothing to bend, and forcing an unmotivated jog would itself be the
  "decorative offset" this round's brief explicitly warns against.
- **LANE JOG** (Battery, Grid): a genuine two-corner "parallel-lane
  shift" - leave the node on its own inverter-facing edge, run straight
  for `JOG_FRACTION` (55%) of the distance, one short rounded step
  sideways onto a dedicated lane (`LANE_OFFSET_BATTERY_GRID`, -16 units,
  toward the solar side/away from Home), then straight again into the
  inverter's own port on that lane. This is the actual, real
  wiring-diagram technique for "these two lines would otherwise aim at
  the same point - give each its own channel" - not an arbitrary curve.
  Both ends still leave/arrive on their correct (horizontal)
  edge-direction; only the short middle segment is perpendicular.
- **ELBOW** (a fanned-out 3+-source solar array, the optional Generator
  arm): one real rounded corner via the same `roundedCorner()` helper -
  leave the start node moving vertically until reaching the end node's Y,
  then horizontally into it. This is a direct return to the pre-round-11
  rounded-corner technique, just centralised through the shared helper
  and given a visibly bigger radius (12 -> `ELBOW_RADIUS` 22) so the bend
  itself reads as a deliberate design feature.

### Reversal stability, proven not just asserted

Every route is built from `from`/`to` in their FIXED, never-swapped
order first (`fromPoint`, `toPoint`, every corner) - only the drawn `M`
direction depends on `reversed`. Verified this round by literally diffing
the rendered `d` attribute between Battery's discharging and charging
states in a live preview harness: the charging path's point sequence is
exactly the discharging path's sequence reversed, corner-for-corner,
control-point-for-control-point - the physical lane jog occupies the
identical pixels either way; only the arrow and dash direction flip.

### Verified live in a local harness, not guessed

Used the same Lit + real built `dist/ecco-energy-flow-card.js` preview
harness from round 12 (mocked `hass`/config matching
`examples/ecco-example.yaml`) to actually inspect the rendered `d`
strings and arrow `transform`s via `getComputedStyle`/DOM inspection, not
just screenshots - confirmed Battery/Grid arrows land exactly at
`inverterY + LANE_OFFSET_BATTERY_GRID` with the correct 0°/180° rotation
(arriving horizontally, as designed), and separately exercised the ELBOW
case by temporarily configuring a Generator node in the harness - its
line and Home's (which stops being axis-aligned with the inverter once
Generator is configured, see `_layout()`) both produced clean, correctly-
rounded single-corner bends.

### Not touched

Node layout/sizing/composition (round 12's fixes stand), entity mapping,
sign-convention normalisation, the colour/state system, power-scaled
thickness/animation-speed scaling, idle behaviour,
`prefers-reduced-motion` handling, click/more-info behaviour, and the
quick-metrics/details-panel work from round 12.

### Real ECCO dashboard config updated, not just the example

Round 12 only added `show_details_panel: false` to
`examples/ecco-example.yaml` - the maintainer's actual live card config lives in
`home-assistant/dashboards/ecco_pro.yaml` (a separate file this repo
tracks, deployed to `/config/ecco/dashboards/ecco_pro.yaml` via
`tools/deploy-dashboard.ps1`), which never got the same field, so the
redundant "Inverter details" panel kept showing live even after round
12's deploy. Fixed this round: the real dashboard config's `features:`
block now also sets `show_details_panel: false`, and the dashboard YAML
was deployed alongside the card JS.

### Live-deployed for review, not yet committed

Built and typechecked clean. Deployed the same way as rounds 11-12 (direct
to `/config/www/ecco-energy-flow-card.js`, plus this round the dashboard
YAML via `deploy-dashboard.ps1`). Not committed - the maintainer reviews live
again before anything lands.

## Update 2026-09-25 (round 12) - compositional redesign, quick-metrics cleanup

Round 11's curves were a real improvement over straight lines but the maintainer's
live verdict was "bit crap but better" - the diagram still read as "the
old schematic with Bezier curves added" rather than one designed object.
This round was given explicit freedom to move node positions/sizes/spacing
(not just curve amplitude) and used the Frontend Design skill to critique
the composition before touching code.

### The critique

Working from the maintainer's own live screenshot (not just the source), the real
problems were structural, not curve-shape:

- Every arm's reach from the inverter had drifted independently across
  earlier rounds (Solar's gap in particular, ~96 units, far exceeded
  Home/Battery/Grid's ~75-130) - Solar read as "a wide box floating above
  a separate network" rather than part of one system.
- The inverter (156px) was narrower than Home (172px) - the hub was
  visually SMALLER than one of its own spokes, so it never won the "most
  important node" comparison the layout's own doc comments claimed it did.
- Grid (104px) and Battery (132px) were meant to "feel approximately the
  same visual weight" per an earlier round's own comment, but were never
  actually the same width - a real, simple inconsistency.
- The solar array box had grown to 336px (a previous round's fix for
  "reads as a tiny status box") - overcorrected into dominating the card
  width instead, the opposite problem.
- `.flow`'s width cap (640 -> 840px, an earlier round's fix for "renders
  too small") combined with fixed-CSS-px node sizes meant gaps (percentage
  of container) grew on a wide card while boxes did not - this is the
  actual mechanism behind "too much dead space", not a coincidence.

### The fix

`_layout()`: every arm's distance from the inverter centre was
re-derived as one family instead of four independently-tuned numbers -
`ARRAY_TO_INVERTER_GAP` 96 -> 84, `HOME_GAP` 75 -> 78, `SIDE_GAP` stays 130
(this one turned out to already be close to the safe limit for the
inverter's own width - see the sizing note below). Diagram height drops
246 (was 265 at round 10's numbers) - a real reduction, not just a
different aspect ratio.

Sizing was rebalanced so the inverter actually wins the size comparison:
Home 172px -> 132px (was wider than the inverter - now sits in the same
family as Battery/Grid, distinguished by colour/glow, not sheer size),
Grid 104px -> 132px (now genuinely matches Battery, not just in a
comment), solar array 336px -> 236px (panel cells/gaps/label shrunk to
match). The inverter itself only grew a little in WIDTH (156 -> 160px) -
initial attempts at a much bigger inverter (188px) directly caused real
node-overlap at typical card widths, because every neighbour's safe
distance has to grow with it (see the git history of this round's own
back-and-forth, live-measured via a local preview harness - getBoundingClientRect()
against the actual built card, not guessed from source). The actual size/
prominence increase comes from taller padding (10px -> 14px, costs only
vertical room, which had far more slack than horizontal) plus a
strengthened glow/gradient/border - the inverter reads as the hero through
presence, not primarily through eating into Battery/Grid's own clearance.

Curve `BOW_*` constants were re-tuned down for the new, shorter spans
(14/7/10 -> 13/7/8) so they stay the same restrained ~15% of their own
span rather than becoming proportionally MORE curved as the spans shrunk.

### Verified, not assumed

This round used a local preview harness (Lit + the real built
`dist/ecco-energy-flow-card.js`, mocked `hass`/`nodes` matching
`examples/ecco-example.yaml` exactly) to actually screenshot the result
and measure real `getBoundingClientRect()` box positions at three card
widths (380/420/840px) before and after each change - the overlap/
overflow problems above were found and fixed this way, not by eyeballing
coordinates. At 420px and 840px (the realistic range - the maintainer's own live
screenshot renders wide) there is zero node overlap and zero quick-metrics
overflow. At an unrealistically narrow 380px there remains a small
(~9px) Inverter/Battery and Inverter/Grid overlap - re-deriving round 10's
own numbers shows this exact fragility already existed before this round
(battery already computed to a negative, off-canvas left edge at 380px
under the OLD SIDE_GAP/box-size combination) - not a new regression, and
consistent with this file's own repeated "narrow-width still needs
The maintainer's live check" caveat from earlier rounds.

Bidirectional reversal (Battery charge/discharge, Grid import/export) was
re-verified in the harness across all three mock scenarios - the physical
curve stays in the same place; only colour, label and arrow/dash direction
change, exactly as required.

### Quick metrics: five tiles, portable details-panel opt-out

`_renderQuickMetrics()` grew from three tiles (Grid Voltage/AC Temp/DC
Temp) to five (adds Grid Connected/Frequency) - these two previously only
appeared inside the collapsible "Inverter details" panel, which was
otherwise pure repetition of the other three once all five were
configured. Grid Connected gets its own presentation (a check/alert icon
plus the card's existing `--ecco-ok`/`--ecco-fault` severity colours - no
new colour introduced) rather than reusing the plain neutral tile style.

Portability: the schema keeps `inverter_details` exactly as it was (no
fields removed, nothing ECCO-specific hard-coded) - the quick-metrics
strip's five-tile behaviour is unconditional (any installation configuring
all five fields gets all five tiles, same "independently optional" pattern
as before). Only the collapsible PANEL's visibility became configurable:
`features.show_details_panel` (default `true`, so every existing
install/config renders exactly as before) - ECCO's own
`examples/ecco-example.yaml` sets it `false`, since it configures every
field the panel could otherwise add nothing beyond.

`.quick-metrics` changed from `display:flex` (three equal-width tiles) to
`display:grid; grid-template-columns: repeat(auto-fit, minmax(92px,1fr))`
- five tiles sit in one row at typical/wide widths and wrap to 2-3 per row
on a narrow card with no separate breakpoint needed and no tile ever
crushed below 92px.

### Not touched

Entity mapping, sign-convention normalisation, the colour/state system
itself (reused, not replaced), power-scaled thickness/animation-speed
scaling, idle behaviour, `prefers-reduced-motion` handling, the Today
section's own data model, click/more-info behaviour, and the
solar/battery/grid/home functional relationships - only the presentation
of that same information changed.

### Live-deployed for review, not yet committed

Built and typechecked clean. Deployed the same way as round 11 (direct to
`/config/www/ecco-energy-flow-card.js`, the bare path the live dashboard's
resource actually serves, via the manually-replicated backup/stage/
SHA256-verify/`ha core check` sequence - `tools/deploy-ha.ps1`'s own
allowlist still excludes that path, unchanged from round 11's note). Not
committed - the maintainer reviews live again before anything lands.

## Update 2026-09-25 (round 11) - organic curved routes, live-review pass

The maintainer confirmed the cross-shape topology and its functionality (round 10
and earlier) but felt the largely-straight connectors read as a rigid
electrical schematic rather than a premium energy dashboard. This round
touches ONLY the shape of the four flow-line paths built in `_line()` - no
topology, entity mapping, sign convention, colour system, or animation
timing changed.

### From rounded-corner orthogonal routing to cubic-Bezier organic routes

Every line is now a single cubic Bezier (`M ... C ...`), replacing both
the old plain straight run (aligned connections: Solar/Home/Battery/Grid)
and the old straight-with-one-small-rounded-corner path (the bent case: a
fanned-out 3+ solar array, the optional Generator arm).

- **Aligned connections** (start/end already share an X or Y - every arm
  of the inverter's cross) get a deliberate perpendicular "bow" off the
  straight line, a fixed distance tuned per connection
  (`BOW_BATTERY_GRID`/`BOW_HOME`/`BOW_SOLAR`): Battery and Grid bow as
  matched, balanced single arcs, away from Home; Solar bows once, reading
  as energy feeding down into the inverter; Home - the one connection
  The maintainer's brief specifically asked to read as visually distinct - gets a
  genuine S-curve (`shape: "s"`, bowing once each way) instead of a single
  arc. The bow's sign is resolved from each control point's own position
  relative to the span's midpoint, not from which node currently happens
  to be "start" - this is what keeps a bidirectional line's physical route
  (Battery/Grid) identical in both directions, charging or discharging,
  importing or exporting; only the arrow and animated dash direction flip,
  exactly as before this round.
- **Bent connections** (genuinely offset on both axes) now extend each
  control point from its own node along that node's own exit/entry axis
  by a fraction of that leg's length, instead of the old fixed 12-unit
  corner-rounding radius - a direct smoothing of the previous shape into
  one continuous flowing curve, same vertical-then-horizontal axis order
  as before.

### Arrowhead placement moved from midpoint to the receiving edge

Round 8 deliberately moved the arrowhead to each line's midpoint, reading
as "flowing along the open line" rather than crowding the arrival node.
This round's brief explicitly asks for the opposite - arrows should
terminate at the visible box edge - so the arrow is now positioned at the
curve's own already-inset receiving-end point, with its rotation computed
from the curve's TRUE final tangent (`P3 - P2` of the cubic) rather than a
fixed horizontal/vertical angle. This is a deliberate, requested reversal
of round 8's choice, not an oversight - flagged here so a future round
doesn't "fix" it back without knowing this was intentional.

### Not touched

Topology (`_layout()`), entity mapping, sign-convention normalisation, the
colour/state system, power-scaled thickness, animation-speed scaling, idle
behaviour, `prefers-reduced-motion` handling (the dash layer still turns
off via the same CSS rule; the curved static line remains visible - route
geometry is orthogonal to how the dash layer is styled), responsive
behaviour, and every other rendering helper. `stroke-linecap: round` in
`static styles` already existed and needed no change - it's what keeps the
new curves' joins smooth.

### Live-deployed for review, not yet committed

Built and typechecked clean (`npm run typecheck`, `npm run build`).
Deployed the rebuilt `dist/ecco-energy-flow-card.js` directly to
`/config/www/ecco-energy-flow-card.js` - the file the live dashboard's
already-registered `/local/ecco-energy-flow-card.js?v=...` resource
actually serves - via a manually-replicated version of
`tools/deploy-ha.ps1`'s own safety sequence (timestamped backup, staged
upload, SHA256 verification before AND after the move, `ha core check`,
no restart), not the script itself: its destination allowlist deliberately
excludes the bare `/config/www/` root (`docs/HA_SSH_DEPLOYMENT.md`), and
this card's resource has been deliberately left on that pre-existing bare
path rather than migrated to the newer `/config/www/ecco/` convention
(`deployment/ha-manifest.yaml`). See this round's report for the exact
verified hashes. Not committed - this is a live-review checkpoint; the maintainer
inspects the dashboard, then the next round either lands this as-is or
adjusts based on feedback.

## Update 2026-09-19 (round 10) - dedicated background variable, dashboard structural fix

Live integration into ECCO's Overview (feature/dashboard-energy-flow-
integration) surfaced two things a dashboard-side card_mod workaround
could not actually fix:

- The card's background was still charcoal/grey against the dashboard's
  navy cards even after overriding `--ecco-bg` via card_mod's `:host`
  block from outside. Root cause: `--ecco-bg` defaulted to
  `var(--card-background-color, #10151f)` - the maintainer's HA theme already
  sets `--card-background-color` globally (to a neutral charcoal), so
  the card's OWN navy fallback was never actually reached, and an
  external `:host { --ecco-bg: ... }` override arriving this early in
  the custom-property cascade did not reliably win against the theme's
  own value inherited through the light DOM. Fixed at the source instead
  of fighting it from outside: `--ecco-bg` now defaults to
  `var(--ecco-card-background, #141c2d)` - a card-specific variable name
  the host theme has no reason to already be setting, with a real navy
  default baked in. The card now looks complete (navy) out of the box
  with zero external configuration, and remains just as re-themeable as
  before for anyone who deliberately sets `--ecco-card-background` -
  the indirection didn't go away, it just points at a name that isn't
  already claimed by something else. All existing `--ecco-surface`/
  `--ecco-border`/etc. color-mix() derivations off `--ecco-bg` are
  unchanged and continue working automatically.
- `grid_options.rows` fixed numbers (11, then auto-but-unstructured, now
  properly auto) are covered on the dashboard side - see
  home-assistant/dashboards/ecco_pro.yaml's own history on
  feature/dashboard-energy-flow-integration for the full story (Grid
  Status + Current Plan wrapped in a single `vertical-stack` sibling
  next to the Energy Flow card, rather than relying on three independent
  Sections-view items happening to pack into alignment via matching row
  counts - the fragile setup that broke when Energy Flow's height
  became genuinely dynamic via `rows: auto` and the Inverter Details
  toggle).

No flow/state colours, topology, routing, or animation touched - this
round only changed the single `:host { --ecco-bg: ... }` line and its
explanatory comment.

## Update 2026-09-19 (round 8) - final premium-polish pass: route separation, micro-interactions, finish

The maintainer confirmed round 7's colours/animation/weight all live-tested well and
asked for one last finish-quality pass, no new features. The one real
functional change is the routing fix below; everything else is CSS.

### Battery/Home/Grid route separation (the main fix)

Every bottom-row line previously bent to arrive at the exact same y - the
inverter's own centre (`endNode.y` in `_line()`'s bend branch, where
`endNode` was always the raw inverter `FlowNode`). Home's line is a plain
straight vertical run (already exactly x-aligned with the inverter, so it
uses `_line()`'s "aligned" branch, no bend). Battery/grid's bent paths,
though, both swept in horizontally right along that same centre y before
diving into the inverter from the side - at typical card widths that
horizontal approach landed close enough to home's central column that the
charge/discharge or import/export colour visibly crossed/overlaid part of
home's blue line, reading as if home's own colour were changing.

Fix, entirely inside `_buildLines()` (no change to `_line()`'s own
algorithm at all): battery and grid now target a synthetic "port"
`FlowNode` - a plain object spreading the inverter's own fields with `x`
offset by `PORT_OFFSET_X = 22` (left for battery, right for grid) and `y`
offset by `PORT_OFFSET_Y = 18` (down from centre) - instead of the
inverter's raw centre point. `_line()` itself needed zero changes; it just
received a different endpoint. This gives each of the three bottom routes
a genuinely separate arrival point on the inverter's own footprint -
battery lower-left, home bottom-centre (unchanged), grid lower-right, per
The maintainer's own "connection ports" framing - while both offsets stay
comfortably inside the inverter box's rendered footprint at typical card
widths, so the arrival point/arrowhead stay masked under the opaque card
exactly as before, just from a different edge of it.

### Smooth state transitions

`.node-box`'s existing `transition: width 0.2s ease;` grew to also cover
`border-color`/`background`/`box-shadow` at 280ms, plus a new `color`
transition on `.node-box ha-icon` and `stroke`/`fill` transitions on the
flow-line/arrow elements (their colour class swaps on the same persisted
SVG element across a re-render, so this actually animates). Clickable
nodes get their OWN faster 180ms transition (including a new `transform`)
for hover/press feedback specifically, layered on top of the base one.
None of this touches how quickly a new value from `hass` is reflected -
only how the resulting colour change is painted.

### Typography stability

`font-variant-numeric: tabular-nums` added to every live numeric display
in the card (`.node-value`, `.inverter-value`, `.today-value`,
`.quick-metric-value`, `.details-value`, and the two `strong` badges/Solar
Share) - each digit glyph takes equal width, so a value cycling through
its digits, or crossing a W/kW unit boundary, doesn't visibly jitter
inside its already-fixed-width node box.

### Clickable micro-interaction

`.node-box.clickable`/`.inverter-box.clickable` gained a 1px hover lift
(`translateY(-1px)`) plus the existing border-glow, and a tiny press
response (`translateY(0) scale(0.98)`) on `:active` - both pure CSS
pseudo-classes, no JS touch handling added, so this doesn't interfere with
HA's own touch behaviour. A dedicated `prefers-reduced-motion` rule turns
the transform off for these two states specifically while leaving the
border/glow feedback (not motion) in place.

### Alignment/spacing audit findings

One real inconsistency found: `.battery-box .node-text` had its own
`gap: 1px` for its three stacked lines, but the newly-added `.grid-box`
(also three lines) had no equivalent and inherited the base `.node-text`'s
implicit 0 gap. Fixed by moving `gap: 1px` onto the base `.node-text` rule
(now shared by every node, 2-line or 3-line) and removing the
now-redundant battery-specific override. Border-radius/icon-tint/
surface-transparency/heading-contrast/separator-opacity were all audited
and found already consistent - they were already flowing through the same
small set of shared `--ecco-*` custom properties from earlier rounds, so
nothing needed correcting there.

### Battery/grid/inverter/solar-total: verified, minor tuning only

- Battery: peak glow-pulse intensity reduced (16px/-3px/65% -> 14px/-4px/
  55% blur/spread/opacity) and shimmer opacity reduced (26% -> 20%) so
  neither ever reads as more prominent than the inverter's own glow (now
  also given a second, quiet drop-shadow layer for a touch more depth -
  see `.inverter-box`). SOC background fill, text contrast, and
  charge/discharge/idle transitions were reviewed and left as-is - already
  restrained. Confirmed `.battery-box`'s existing `overflow: hidden`
  already fully contains the shimmer sweep (no spill past the card).
- Grid: sizing/weight/colours already matched Battery from round 7 -
  verified, no change.
- Solar Total: already at its intended size/spacing/prominence from round
  7 - verified, not enlarged further, its glow pulse and idle sleep-back
  behaviour both reviewed and left unchanged.
- Inverter: no recolouring; only the two-layer shadow above, purely
  static (no new animation on the card itself).

### Responsive width check - honestly scoped

No live browser/HA runtime was available in this pass to literally render
the card at multiple widths, so no "confirmed working at N widths" claim
is made. A code-level review found nothing that changed this round would
newly break at narrow widths (all new CSS is either fluid, e.g.
`tabular-nums`/transitions, or additive glow/shadow on already-existing
fixed-size node boxes) - the fixed-CSS-px node-box sizing and the
`dense`-mode crowding threshold are both pre-existing, unchanged
characteristics from earlier rounds. Literal narrow-width visual
confirmation still needs the maintainer's live check.

## Update 2026-09-19 (round 7) - state-aware colour, power-scaled flow, battery animation, clickable nodes

The largest visual-polish pass yet, still explicitly NOT a topology/schema
change - the maintainer's brief plus a mid-turn add-on, both folded into one round
since everything requested composes cleanly on top of round 4-6's existing
structure. No `nodes:`/`today:`/`inverter_details:`/`features:` schema
field was added or changed - every new behaviour here is either derived
from entities the user already configured, or pure CSS.

### Colour system

`FlowColourKind` grew from one static value per node kind to a real state
machine for battery (`battery-charge`/`battery-discharge`/`battery-idle`)
and grid (`grid-import`/`grid-export`/`grid-idle`), computed identically in
`_buildLines()` (drives the line) and `_renderBottomNode()` (drives the
node card) from the exact same sign-convention-normalised value - one
source of truth for "what state is this in right now", never two
independent guesses that could disagree. Solar stays a single `solar`
kind (it has no direction to speak of) but gained real border/background-
tint/glow styling via `.node-box.colour-solar` plus a generic `.idle`
modifier class (near-zero total dims it back to neutral) reused by both
the array nodes and the Solar Total combiner.

CSS variables: `--ecco-line-grid` split into `--ecco-line-grid-import`/
`-export`/`-idle`; `--ecco-line-battery-charge`/`-discharge` KEPT their
names but their actual colours swapped meaning (charge was blue `#5aa8ff`,
now green `#43d17a`; discharge was green `#57e59a`, now orange `#ff8a3d`)
to match the maintainer's explicit charge=green/discharge=orange request, plus a
new `--ecco-line-battery-idle`. `--ecco-line-solar`/`--ecco-line-home`/
`--ecco-line-generator` are unchanged. All border/background-tint/glow
values are derived from these via `color-mix()` at low percentages
(10-16% for tints, kept off the SVG stroke/fill critical paint path per
the existing no-color-mix-there constraint) rather than being separate
hard-coded hex values - one variable per state stays the single source of
truth for that state's colour everywhere it appears.

### Battery "alive" treatment

`.battery-box` now has real motion while charging/discharging: a slow
(3.4s) `box-shadow` glow pulse, a diagonal shimmer sweep (`::before`,
3.6s, direction differs charge vs. discharge - suggesting energy flowing
in vs. out), and a matching sheen on the SOC bar (`.soc-fill::after`).
Fully static (no `animation` property at all, not just a paused one) while
idle. A separate `::after` pseudo-element renders a very subtle SOC-
proportional background fill (`--ecco-soc`, set inline per render) behind
everything else - an ambient second representation of charge level next
to, not instead of, the existing precise `.soc-track` bar. Stacking is a
local context (`.battery-box { position: relative; z-index: 0; }`) with
the SOC fill at `z-index: -2` and the shimmer at `-1`, so the card's own
icon/text (plain in-flow content, no explicit z-index needed) always
paints above both without extra markup. Grid gets the same border/tint/
glow treatment but deliberately NO animation - the maintainer only asked for
battery to "feel alive", grid just needed comparable visual weight
(`.grid-box`, sized to match `.battery-box`'s 104px/font sizes).

### Power-scaled flow and idle behaviour

Animation speed was already magnitude-scaled from round 3 (verified, no
change needed). Added: line THICKNESS now scales the same way
(`MIN_LINE_WIDTH_PX`/`MAX_LINE_WIDTH_PX`, set per-path via an inline
`--ecco-line-w` custom property so the shared CSS rule stays the single
place the property itself lives) - thin near idle, modestly thicker at
high power, deliberately a small range. Idle/near-zero behaviour was
already mostly in place (the `.idle` class on lines drops them to 0.12
opacity and pauses the dash animation); this round extends the same
"sleep back" concept to node cards themselves - solar via the new
`.idle` modifier, battery/grid via their own `-idle` colour state
(neutral border/background, no glow, no animation).

### Clickable nodes

Every node with a determinable entity (`EntityIdMap`, built once in
`render()` from whatever `nodes:` the user already configured - power
preferred, falling back to state/SOC for inverter/battery, nothing
hard-coded) is now a `tabindex`-focusable, `role="button"` element that
dispatches HA's standard `hass-more-info` bubbling/composed custom event
on click/Enter/Space - the same event HA's own frontend listens for, so
no HA frontend import/dependency was needed. A node with nothing
configured for this simply never gets the `clickable` class/attributes,
so it stays a plain, non-interactive card. The SVG line layer already had
`pointer-events: none` from round 2/3, and node cards already sit above it
via `z-index: 1`, so this required no changes to the pointer-event
layering - clicks already only ever reached the HTML node layer.

### Reduced motion

The existing `@media (prefers-reduced-motion: reduce)` block (previously
just the dash animation) was extended to also disable the combiner pulse,
the battery glow pulse, and both shimmer/sheen sweeps (hidden outright via
`opacity: 0` rather than left as a static diagonal streak, which would
just look like a rendering glitch once motionless). In every case the
underlying colour/border/background/box-shadow is set unconditionally in
the base rule, not only via the `animation` keyframes, so disabling
`animation` alone falls back to a correct static appearance - state
information is never lost, only the movement.

### Bug notes (self-caught, not user-reported)

Reintroduced the exact "backtick inside a `css` tagged-template literal
comment" bug from round 4 - three more times, in three different new
comments, while writing the extensive doc-comments for this round's CSS.
Each one silently truncated the JS template string and produced the same
misleading cascade of unrelated-looking `tsc` errors (`TS1005`/`TS1144`/
`TS1135`/`TS1128`) rather than pointing at the actual backtick. Caught via
`npm run typecheck` before any other validation step, same as round 4;
fixed by rewriting each comment to avoid backticks entirely and
re-scanning the whole `static styles` block with a small `awk` one-liner
for any remaining backtick before re-running typecheck. Worth remembering
for any future pass that edits comments inside this specific block.

## Update 2026-09-19 (round 6) - live entity correction: AC/DC transformer temperature

The maintainer confirmed the actual live entity ids for the two transformer
temperature sensors, correcting the round-5 quick-metrics-strip guess.
`examples/ecco-example.yaml`'s `inverter_details.ac_temperature`/
`dc_temperature` now point at
`sensor.ecco_clock_dongle_ecco_temperature_ac_transformer` /
`..._ecco_temperature_dc_transformer` (previously
`..._ecco_ac_temperature` / `..._ecco_dc_temperature`, which were the
ESPHome-slugification *guess* flagged as unconfirmed in that file's own
ASSUMPTIONS block). Confirmed live values at the time of this correction:
AC ~40.2°C, DC ~46.9°C. No `src/` code changed - this is example-config
data only, the card itself never hard-codes an entity id.

Also recorded (not fixed, out of scope for this card): Home Assistant
currently reports these two sensors' `unit_of_measurement` attribute with
a stray extra character before the degree symbol - a UTF-8-read-as-
Latin-1 mojibake artifact, an upstream firmware/metadata encoding issue.
This card never reads or displays that attribute itself (its
quick-metrics/details panel always renders its own literal degrees-Celsius
suffix via `toFixed()` + a hard-coded unit string), so the card's own
rendered output is unaffected either way - flagged here purely as a live
finding for whoever eventually looks at the firmware/ESPHome config.

## Update 2026-09-19 (round 5) - live-review visual polish pass

The maintainer live-tested round 4 in Home Assistant and approved the topology and
routing "in principle" (explicitly: do not redesign again) - this round is
styling/sizing only, no layout, routing, entity, or calculation changes:

- **Solar Total combiner**: was getting visually lost against the solar
  line - its box was translucent (`opacity: 0.9` on the whole box plus a
  `color-mix(..., transparent)` background), which let the incoming line
  show through instead of appearing to terminate cleanly at the node. Fixed
  by making the background fully opaque (same solid `--ecco-surface` as
  every other node box) and enlarging the box (70px -> 92px) with a larger,
  bolder value (`0.85rem`/700 weight, up from `0.56rem`) and a larger label
  - while staying narrower than the inverter's 124px box, so it remains
  visually secondary as required.
- **Inverter "AC Output" caption**: bumped from `0.55rem`/600 weight/muted
  to `0.64rem`/700 weight with a blended (muted+text) colour for more
  contrast, without touching the dominant power value's own size/weight or
  the state pill's styling.
- **Battery status word** (Charging/Discharging/Idle): bumped from
  `0.58rem` fully-muted to `0.66rem` at `--ecco-text` colour (78% opacity)
  - more prominent, still visually secondary to the bold SOC/power lines
  above it.
- **Solar Share**: moved out of its own `.badges` row (which, with
  self-sufficiency off as in the ECCO example, was a standalone row holding
  a single pill) and into the "Today" heading row itself, right-aligned
  (`_renderToday()`'s new `_solarShareText()` helper). Self-sufficiency,
  where still enabled elsewhere, keeps its own `.badges` row via
  `_renderBadges()` - it's a distinct metric from Solar Share, not folded
  into this change.
- **Quick metrics strip**: already used `flex: 1 1 0` per tile, which
  already produces equal-width cells regardless of how many of the three
  (Grid Voltage/AC Temp/DC Temp) are configured/available - verified, no
  change needed here.

## Update 2026-09-19 (round 4) - Solar Total combiner node; rounded orthogonal routing; polish

The maintainer confirmed round 3's fixes worked live (nodes, multi-solar, animated
lines, inverter-central, battery/grid direction all correct) and asked for
one topology change plus several polish items, all landed together here.

### Solar Total / PV combiner node

Previously, 2+ solar sources each drew their own line straight to the
inverter, with a small detached "Total X kW" pill floating above the row
as a pure annotation (no geometric relationship to the lines at all). That
pill is gone. In its place, `_layout()` now creates a real `FlowNode`
(kind `solar_total`) centred on the same X as the inverter, sitting
between the solar row and the inverter, whenever `solarSources.length > 1`.
`_buildLines()` routes every array's line into that node instead of the
inverter, then adds exactly one more line from the combiner to the
inverter - so the generation is never visually double-counted across two
different line sets. With exactly one solar source, `layout.solarTotal` is
`null` and behaviour is byte-for-byte what it was before this round: the
single source's line goes straight to the inverter.

The combiner's displayed value is `nodes.solar_total`'s live entity value
when configured (shown authoritatively, never recalculated against it),
falling back to the client-side sum of the configured array readings when
it isn't. It renders through the same `node-box` shell as every other
node (for a consistent look) but with a new `.combiner` size modifier -
smaller, lower-opacity, dashed border - so it reads as a secondary merge
point and the inverter stays the visually dominant node, per the maintainer's
explicit requirement.

### Orthogonal routing with rounded corners

`_line()` previously computed a single straight diagonal `M...L...` path
between two inset points. The maintainer's first ask was for Manhattan-style
(horizontal/vertical only) routing; a follow-up refinement (arriving
mid-implementation) asked specifically that the bends NOT be sharp 90°
elbows - they should be smoothly rounded, "a polished fluid energy-flow
diagram rather than a rigid electrical schematic."

The final approach: every row of this diagram (solar row / combiner+
inverter / bottom row) is separated primarily in Y, with X offset only
from fan-out within a row. So each line needs at most one bend. The rule
is direction-agnostic and handles both fan-in (arrays merging into the
combiner from above) and fan-out (the inverter's shared trunk splitting
to battery/home/grid/generator below) with the same formula: leave the
start node moving vertically until reaching the end node's Y, then move
horizontally into the end node. The hard corner point is
`B = (startNode.x, endNode.y)`.

When start and end already share an X or Y (the combiner sitting exactly
above the inverter; a single centred bottom node with no siblings to fan
around), `rawDx` or `rawDy` is ~0 and the whole bend logic is skipped in
favour of a plain straight line - the general case doesn't need a special
early-return check for these, they just naturally have a zero-length
segment on one side, but skipping avoids generating a degenerate/zero-
length quadratic curve.

The corner itself is never drawn as a hard elbow. The path pulls back a
clamped radius `r = min(12, 0.6 * vLen, 0.6 * hLen)` on both sides of the
corner and joins the two pull-back points with a quadratic Bezier (`Q`)
through the original corner point as the control point:

```
M sx,sy  L sx,(cornerY - r*vsign)  Q sx,cornerY (cornerX + r*hsign),cornerY  L ex,ey
```

The `0.6 *` clamp prevents the curve from overshooting a short segment
(e.g. a shallow fan-out with a small X offset). If a segment is so short
`r` would round to under 1 logical unit, the code falls back to a hard
two-segment corner rather than emitting a degenerate/invisible curve.

SVG's dash animation (`stroke-dasharray`/`stroke-dashoffset`, used for the
moving "current direction" indicator) is computed from the path's real arc
length by the browser, so it already flows continuously through mixed
`L`+`Q` segments - no extra animation code was needed for this. The arrow
angle is derived only from the FINAL straight segment (always horizontal
in the bent case, whatever direction the single straight run is in the
aligned case), so it stays correct regardless of which branch produced the
path.

### AC Output caption, battery layout, self-sufficiency, quick metrics

- The inverter's centre figure is genuinely AC output only (confirmed live:
  Home ~1.05 kW, Grid import ~56 W, Inverter ~990 W - these don't sum,
  because the inverter figure is AC-side throughput specifically). Added a
  small "AC Output" caption under the value; the underlying entity/
  calculation is unchanged, this is a labelling fix only.
- The battery node's `.node-text` was forced to `flex-direction: row`,
  cramming "Battery 94%", the power figure, and the Charging/Discharging/
  Idle status onto one line. The markup already emitted these as three
  separate `<div>`s (label, value, sub) - the fix was simply letting them
  stack vertically (the `.node-text` default), plus bumping the power
  figure's font size and making the status line bold/uppercase for
  clearer hierarchy. No markup restructuring was actually needed, only CSS.
- `features.self_sufficiency` keeps its schema/behaviour unchanged (still
  computed as `1 - today.import/today.load`) - no new formula was
  invented, per the maintainer's explicit instruction. Its doc comment now states
  the battery-system caveat plainly, and the maintainer's own `examples/ecco-example.yaml`
  now sets it to `false` (ECCO has a battery, so the simple ratio can be
  misleading there); `solar_contribution` is unaffected by this caveat and
  stays enabled.
- A new always-visible compact "quick metrics" strip (`_renderQuickMetrics()`)
  sits between the flow diagram and the "Today" totals, showing up to three
  tiles - Grid Voltage, AC Temperature, DC Temperature - each independently
  optional based on whether `inverter_details.grid_voltage`/
  `ac_temperature`/`dc_temperature` are configured. It reuses those same
  `InverterDetailsConfig` fields (a new `grid_voltage` field was added to
  that interface; `ac_temperature`/`dc_temperature` already existed) rather
  than inventing a parallel config block - the collapsible "Inverter
  details" panel still shows the full set of fields on that interface
  (including these three) on demand; this strip is just the quick-glance
  subset shown without an extra click. Styled deliberately quieter than the
  "Today" tiles (no heading row, smaller text/icons) so it reads as
  secondary, not a second headline section.

### Explicitly NOT regressed

Multi-solar schema and single-solar backward compatibility (unchanged
`normaliseSolarSources()`), live animated flows, the Lit `svg`
tagged-template fix from round 3, HTML node overlays (still no
`foreignObject`), no `<marker>`/`marker-end="url(#id)"` dependency (the
computed-`<polygon>` arrowhead approach is untouched, just repositioned by
the new routing), grid/battery sign-convention handling and dynamic arrow
reversal, `prefers-reduced-motion` support (still only disables the
animated dash layer), frontend-only architecture, HACS portability
(nothing hard-codes an entity id anywhere in `src/`), optional generator/
AUX support, "Exported Today", daily totals, and responsive behaviour.

## Update 2026-09-19 (continued) - fixed: flow lines still not visible; multi-solar support

Nodes rendered correctly after the previous fix (commit `8d25336`), but the
flow lines/arrows themselves still did not render live. Two independent
things were addressed in this pass.

### Real root cause of the invisible lines (found, not guessed)

`_renderLine()` returned `html\`<path ...></path>\`` - its OWN, separately
tagged `html` template literal, called from inside `_renderFlow`'s
`${lines.map(...)}` interpolation. **This is the actual bug.** Lit parses
each tagged-template-literal callsite independently of where its result
later gets inserted: `_renderFlow`'s own `<svg>...</svg>` markup, written
directly in ITS template string, correctly triggers the HTML parser's
foreign-content (SVG) switching for whatever is written right there - but
that context does NOT extend to a *separately* tagged-template result
produced by another method and merely interpolated in. `_renderLine`'s own
template string was just `<path ...></path>` with no enclosing `<svg>` of
its own, so Lit parsed it via a plain (non-foreign-content) `<template>`,
creating an `HTMLUnknownElement` instead of a real `SVGPathElement`. That
element was structurally present in the DOM, correctly nested inside the
`<svg>` - which is exactly why it looked like "the line should be there"
under inspection - but browsers never paint an element in the wrong
namespace as SVG graphics, so nothing showed. This is a well-documented
Lit/lit-html gotcha (Lit's own docs describe it: any `TemplateResult` whose
own top-level content is raw SVG elements must be built with the `svg`
tagged-template function, not `html`, regardless of where it ends up being
used), not a CSS/z-index/marker/shadow-DOM issue - those were investigated
too (see below) and hardened defensively, but this was the actual cause.

**Fix**: `_renderLine()` now uses `svg\`...\`` (imported from `lit`), and
returns three real SVG elements - see "Line rendering" below. Every other
render helper that returns HTML content (`_renderNode`, node cards, etc.)
correctly stays on `html`, since HTML is exactly what they should produce.

### Other things checked, and hardened regardless of exact contribution

The task asked to check several other risk areas explicitly. None of them
fully explained the symptom on their own (the namespace bug above does),
but each was still a real, worth-fixing risk, so all were addressed:

- **`<marker>`/`marker-end="url(#id)")`**: removed entirely. Even though
  the namespace bug was the actual cause, an internal SVG fragment
  `url(#id)` reference is exactly the kind of "fragile browser/shadow-DOM
  behaviour" the task asked to avoid on principle. Each line's arrowhead is
  now a small `<polygon>` positioned and rotated directly via an SVG
  `transform="translate(x,y) rotate(deg)"` attribute computed in
  `_line()` - no `<defs>`, no id, no reference of any kind.
- **`color-mix()` on the line's critical paint path**: removed. The old
  `.flow-line`'s `filter: drop-shadow(...)` referenced `--ecco-glow`,
  itself defined via `color-mix()`. If a rendering context doesn't support
  `color-mix()`, referencing custom property becomes invalid, and any
  property using it (there, just `filter`) falls back to its initial value
  - `filter: none`, losing the glow but not the stroke itself, so this
  alone wouldn't explain full invisibility, but `.flow-line-anim`'s
  `drop-shadow` still uses `--ecco-glow` today for polish; the STROKE
  colour itself (`.colour-*` rules) now always resolves through a
  dedicated, `color-mix()`-free custom property with a literal hex
  fallback (`--ecco-line-solar: #ffb454;` etc., defined directly on
  `:host`), so the line's own colour can never become invalid for this
  reason even if `--ecco-glow` were to.
- **Stacking/z-index**: node cards (`.node-html`) render after the `<svg>`
  in DOM order and carry `z-index: 1`; the svg itself is `z-index: auto`.
  This was already correct (nodes paint on top, matching the deliberate
  end-inset design so lines don't disappear entirely under a node), not a
  bug - confirmed by re-reading the cascade rules, not assumed.
- **Guaranteed-visible base layer**: each line is now TWO stacked
  `<path>`s sharing the same `d` - an always-solid, non-animated
  `.flow-line-base` at lower opacity, plus the moving-dash
  `.flow-line-anim` on top. Even in a hypothetical future environment
  where the CSS animation mechanism itself fails for some unrelated
  reason, a real, correctly-coloured, correctly-oriented line remains
  visible - this is deliberate defence in depth, not needed to explain the
  original bug.
- **Reduced-motion**: `@media (prefers-reduced-motion: reduce)` now only
  turns off `.flow-line-anim` (`animation: none; stroke-dasharray: none;`)
  - the base layer is completely unaffected, so a static line (with its
  arrowhead) remains visible either way, addressed more robustly than
  before (previously the single `.flow-line` rule risked reduced-motion
  users seeing nothing extra to indicate direction at all beyond a plain
  line - now the arrow/colour still convey direction without animation).

### A second, real bug found while re-verifying "grid/battery must reverse
    dynamically" (not something the task reported - found by re-deriving
    the direction logic from scratch to answer the question properly)

`_line(key, from, to, value, ..., bidirectional)`'s direction rule is: the
DEFAULT (non-reversed) direction is `from -> to`, used when `value >= 0`;
negative `value` reverses it. The previous battery/grid call sites passed
`(inverterNode, batteryNode)` / `(inverterNode, gridNode)` - "inverter
first" order. Working through what that actually draws: for battery
(internal convention: positive = discharging, i.e. battery -> inverter),
`value >= 0` with `from = inverter` draws **inverter -> battery**, which is
backwards - discharging should point AT the inverter, not away from it.
Same backwards result for grid on import. This was never visible before
now (the lines didn't render at all), so it went undetected through both
previous commits. **Fixed** by swapping the argument order at the two
bidirectional call sites (`_buildLines()`) to `(batteryNode, inverterNode)`
/ `(gridNode, inverterNode)`, so `from -> to` already matches what
`value >= 0` means. Verified by hand for all five flow kinds - see the
`_line()` method's own updated doc comment, which states the convention
explicitly so this cannot silently regress the same way again.

### Line rendering (current design)

Each `FlowLine` (`_line()`) computes, once: a `d` path (both ends already
inset so the stroke/arrowhead sit just outside each node instead of
disappearing underneath it - unchanged from the previous fix), a `colour`
key (`solar` / `home` / `grid` / `battery-charge` / `battery-discharge` /
`generator`), and an `arrow: {x, y, angleDeg}` for the receiving end.
`_renderLine()` (using `svg\`...\``) emits three elements per line: the
solid base path, the animated dashed path, and the arrow polygon - all
three share the same `colour-*` CSS class, which maps to one of six
literal-fallback CSS custom properties (`--ecco-line-solar` etc.) defined
on `:host`, overridable from outside via a theme or card-mod. Animation
speed (`animation-duration`, inline per line) scales from 2.6s (near-idle)
down to 0.45s (near `MAX_ANIMATION_MAGNITUDE_W`, 6000W) - deliberately
brisk enough at typical household power levels (hundreds of W to a few kW)
to be obviously moving on a normal dashboard glance, without being
frantic.

### Multi-solar support

`nodes.solar` is now `SolarNodeConfig | SolarNodeConfig[]`
(`normaliseSolarSources()` in `config.ts` is the single place this
polymorphism is resolved into a plain array - every other part of the card
only ever deals with "0..N solar sources", nothing assumes exactly one or
exactly two). `_layout()` fans solar nodes out across the top row using the
exact same `_fanOut()` helper already used for the bottom row (battery/
home/grid/generator) - one function, reused, not two separate spacing
algorithms to keep in sync. Each source gets its own `FlowNode`
(`id: "solar-0"`, `"solar-1"`, ...), its own line into the inverter
(always one-directional, solar -> inverter, per the task brief), and its
own live power reading. With 3+ solar sources, node cards switch to a
`.dense` CSS modifier (narrower width, smaller icon/text) so the row
doesn't crowd/overlap at typical card widths - a `nodes.solar_total`
entity, if configured, renders as a small non-node annotation label above
the row (never an extra node or line, which would double the generation
visually). The original single-object shape
(`solar: { power: sensor.x }`) continues to work unchanged - internally it
is just a length-1 array.

### What was NOT re-verified live in this pass

This entire pass (namespace fix, arrow/marker replacement, colour theming,
direction-bug fix, multi-solar layout) has not yet been previewed in Home
Assistant. Everything above is the result of careful code-level
re-derivation and `tsc`/`esbuild` validation, not a live screenshot.

## Update 2026-09-19 - fixed: live flow area rendered blank

**Symptom, reported after the first live preview** (commit `5f85d69`): the
card loaded, the title/Today totals/badges all rendered correctly, but the
entire flow diagram area - solar/inverter/home/battery/grid nodes AND the
connector lines/arrows, everything inside the `<svg>` - was blank.

**Root cause**: the `<svg>` element had a `viewBox` but no explicit
`width`/`height` *attributes*, combined with CSS `width: 100%; height:
auto;`, inside a `display:flex; flex-direction:column;` parent that itself
had no defined height. With no intrinsic size hint anywhere in that chain,
the SVG's own laid-out height resolved to 0 in the live Home Assistant
frontend - collapsing everything inside it, lines included, exactly
matching the report (nothing rendered from the SVG; everything outside it
was unaffected because it never depended on the SVG's own sizing).
Rendering an SVG responsively purely via `width:100%; height:auto` and a
`viewBox`, with no other size hint, is not reliably supported across every
browser/webview context - it happened to work in local testing but not in
the actual live frontend.

**Fix, and the requested foreignObject removal, done together**:

1. The `<svg>` now carries explicit numeric `width`/`height` attributes
   (matching the logical coordinate space, e.g. `width="320" height="224"`)
   in addition to its `viewBox` - it always has a real intrinsic size,
   regardless of CSS support nuances. The `.flow` container additionally
   gets an explicit CSS `aspect-ratio: 320 / <height>` (set inline per
   render, since the height depends on how many bottom-row nodes are
   configured) so it reserves the correct space before the SVG or the node
   cards paint at all.
2. `<foreignObject>` is gone entirely (`grep -c foreignObject dist/*.js` =
   0). The SVG now contains ONLY `<path>` flow lines and the arrow
   `<marker>` - nothing else. Every node (solar/inverter/home/battery/grid/
   generator) is now a plain HTML `<div>`, a sibling of the `<svg>` inside
   `.flow`, absolutely positioned by percentage
   (`left: <x/320*100>%; top: <y/height*100>%;`) plus
   `transform: translate(-50%, -50%)` to centre it on its point. Both
   layers share the exact same logical coordinate space, so they stay in
   sync at any card width without any JS recomputation on resize.
3. Because node cards now sit on top of the SVG (ordinary DOM stacking - no
   z-index trick needed) rather than being SVG content themselves, a line
   drawn to a node's exact centre point would be invisibly hidden behind
   that node's opaque background. `_line()` now pulls both the start and
   end of each path in slightly (15/20 logical units) along the line's own
   direction, so the stroke and - importantly - the arrowhead marker stay
   visible just outside each node card instead of disappearing underneath
   it.
4. Fixed pixel widths (96px / 100px for battery / 124px for the inverter -
   the same numbers the old `foreignObject` elements used) are set
   directly on the node card CSS. This is a deliberate choice, not an
   oversight: node card *text* stays a fixed, legible size at any diagram
   scale, rather than shrinking proportionally with the SVG viewBox on a
   narrow phone screen the way foreignObject content would have.

**What did not change**: the config schema (`src/config.ts`), the
bidirectional sign-normalisation logic, the flow-line animation/dash
mechanism and its `prefers-reduced-motion` handling, and the inverter's
central/visually-dominant placement in `_layout()` - all untouched. This
was a rendering-layer fix only.

**Not yet re-verified live** (this fix has not been previewed in Home
Assistant again as of this note): the exact behaviour at very narrow card
widths (well under typical mobile dashboard widths), where the bottom
row's three-to-four fixed-width node cards could theoretically begin to
crowd each other before the container itself gets that narrow.

## 1. What was inspected first

- `home-assistant/dashboards/ecco_pro_dashboard_v7_13_0_power_portability.yaml`
  (the current authoritative dashboard, per `VERSION.yaml`) - to see what a
  "live flow" section currently looks like and which entities it already
  uses.
- `firmware/ecco_clock_dongle_stage3_4_free_power.yaml` - for every sensor
  `name:`/`id:` this card's example config references (inverter output
  power, battery output power, PV power, load power, grid frequency,
  AC/DC temperature, grid-connected binary sensor, and the six Stage 2b
  daily energy counters).
- `registry/inverter_capabilities.yaml` - for documented sign conventions
  (`battery_power`: "positive = discharge, negative = charge";
  `grid_power_ct_clamp`: "positive = import, negative = export" per
  `ecco_canonical_telemetry.yaml`'s own comment).
- `home-assistant/packages/ecco_canonical_telemetry.yaml` - the four
  already-portable canonical aliases (`sensor.ecco_battery_soc`,
  `sensor.ecco_house_power`, `sensor.ecco_pv_power`, `sensor.ecco_grid_power`).
  No canonical alias exists yet for inverter power/state or battery power
  (charge/discharge rate) - the ECCO example config uses the raw
  `sensor.ecco_clock_dongle_*` entities for those, flagged in the
  example file itself.

## 2. Why a standalone `frontend/` subproject, not something wired into the
   existing HA packages

This card is a Lovelace **resource** (a JS file the frontend loads), not a
`home-assistant/packages/*.yaml` config package - it has nothing in common
with how the rest of this repository's HA-side files work (those are all
plain YAML consumed directly by Home Assistant; this is TypeScript that
must be *built* into JS). Keeping it in its own `frontend/ecco-energy-flow-card/`
subtree with its own `package.json`/`tsconfig.json`/build script means:

- it can be reviewed as a coherent unit,
- it does not touch or risk anything under `home-assistant/`, `firmware/`,
  `registry/`, or `health/` (none of which this task touches at all), and
- splitting it into its own public repository later is a straight
  `git subtree split` (or just copying the directory) - nothing inside it
  references the rest of this repository except the two example config
  files, which are illustrative content, not code dependencies.

## 3. Frontend-only, no backend

Everything the card needs is already exposed as plain HA entity states -
power/energy sensors, a state/status text sensor, a binary_sensor for grid
connectivity. There is no case for a custom_component or add-on to render
a Lovelace card; HA's own `hass.states` object (passed to every Lovelace
card via the `hass` property) is sufficient. If a genuinely useful backend
feature emerges later (e.g. server-side history aggregation beyond what a
card can reasonably compute client-side), it would be documented as an
optional future extension, not a dependency - see "Future extensions"
below.

## 4. Stack

- **TypeScript + Lit 3** (`LitElement`, decorators). This is the de facto
  standard for modern HA custom cards (Home Assistant's own frontend, the
  official Energy Distribution card, and most popular HACS cards -
  `power-flow-card-plus`, `mushroom`, `button-card`'s successor patterns -
  are all Lit-based). Using the same library the HA frontend itself already
  loads (as a shared dependency at runtime in a real installation) keeps
  this idiomatic rather than reinventing web-component plumbing.
- **esbuild** for bundling, not Rollup/Webpack. A HACS "plugin" resource is
  a single browser-loadable JS file with no build step for the *end user* -
  esbuild produces that in one fast, dependency-light step
  (`npm run build` -> `dist/ecco-energy-flow-card.js`, ~35 KB minified,
  Lit bundled in). No CSS preprocessor, no JSX, no framework beyond Lit
  itself - a heavier bundler wasn't needed.
- **`dist/ecco-energy-flow-card.js` is committed**, not gitignored. HACS
  "plugin" repositories conventionally ship the built file directly (via
  `hacs.json`'s `filename`) so installing the card never requires the end
  user (or HACS itself) to run a build - only a repository maintainer
  rebuilds it, from `src/`, before tagging a release.
- **No visual config editor yet** (`getConfigElement()` is not implemented).
  The card is configured via the Lovelace YAML/code editor for now. A GUI
  editor is real, useful future work, but building one before the visual
  design itself is approved would be effort spent on the wrong thing at
  this stage - noted in "Future extensions".

## 5. The inverter as a first-class centre node

The layout is computed in `_layout()`: the inverter node is always placed
at the horizontal centre, solar (if configured) directly above it, and the
"bottom row" (battery, home, grid, plus generator if configured) fanned out
evenly beneath it - directly matching the topology in the task brief. Every
flow line's SVG path either starts or ends at the inverter's own
coordinates; nothing routes solar/battery/grid/home to each other directly.
The inverter box is visually distinct from the other nodes (larger,
gradient-highlighted background, its own optional state pill with
severity colouring) rather than being an unlabelled junction point - this
was the task's explicit "most important change" versus a conventional
solar/battery/grid/home-only flow diagram.

## 6. Bidirectional flow direction

Internally, the card always normalises to one fixed convention regardless
of what the user's sensors report:

- **battery**: positive = discharging (flowing out towards the
  inverter/home)
- **grid**: positive = importing (flowing in from the grid)

`config.ts`'s `normaliseBatteryPower()`/`normaliseGridPower()` apply the
per-installation `power_sign` (`charge_positive`/`discharge_positive` for
battery, `import_positive`/`export_positive` for grid) to convert the raw
reading into that internal convention once, at read time - every other
part of the card only ever deals with the normalised value, so no sign
logic is duplicated in the rendering code. The drawn SVG path for a
bidirectional line is built with its start/end swapped based on the
*current* sign (`_line()`'s `bidirectional`/`reversed` handling), so the
arrowhead marker and the animated dash travel are always oriented toward
wherever power is actually flowing right now, every re-render - never a
separately-toggled "reverse" CSS class layered on fixed geometry.

Solar and home are treated as one-directional (solar -> inverter,
inverter -> home) per the task brief; a negative reading on either (not
expected from a generation/consumption sensor) is not given special
handling in this prototype.

## 7. "Exported Today"

`today.export` is one of six independently-optional fields under `today:`
(solar/load/import/export/battery_charge/battery_discharge) - rendered in
a single small-tile strip below the flow diagram, each tile only appearing
if its entity is configured. It is not treated as more special than the
other five in the schema (all six are equally optional, equally rendered),
but the ECCO example config explicitly comments on why it matters here -
The maintainer's existing dashboard has the underlying entity
(`sensor.ecco_clock_dongle_ecco_day_grid_export`) but does not
surface it prominently, and this card does.

## 8. Configuration schema shape

Grouped by diagram node (`nodes.solar`/`nodes.inverter`/`nodes.home`/
`nodes.battery`/`nodes.grid`/`nodes.generator`) rather than a flat map of
entity ids, because several nodes need more than one entity plus per-node
options (a sign convention, a label/icon override) - a flat
`entities.battery_power`/`entities.battery_soc`/`entities.battery_sign` map
would scale worse as more per-node options get added later, and reads less
clearly once every optional field is present. Every top-level section
(`nodes`, `today`, `inverter_details`, `features`, `format`) and every
field inside them is independently optional except that at least one entry
under `nodes:` must exist (enforced in `setConfig()`) - the card has to
draw *something*. See `src/config.ts` for the full TypeScript shape (which
is the schema's authoritative definition) and `examples/generic-example.yaml`
for every field with inline documentation.

## 9. What is deliberately NOT in this prototype yet

- A GUI config editor.
- Localisation (all label defaults are English; `label:` overrides exist
  per node today, but there's no strings-table/language-negotiation layer).
- Tap actions (the task listed this as "consider, but do not let them
  clutter the core card" - omitted from the prototype rather than adding
  an under-tested interaction surface before the visual design is approved).
- Any CO2/environmental estimate (no real configured entity for it exists
  anywhere in this repository, and the task explicitly says not to invent
  one).
- Unit/component tests. Validation performed for this prototype is
  `tsc --noEmit` (strict mode, passes cleanly) and a real `esbuild`
  production build (succeeds, ~35 KB output) - see the top-level report for
  the exact commands run.

## Future extensions (not dependencies of this prototype)

- A small optional backend/helper (e.g. a `sensor` template or a tiny
  custom_component) that pre-computes something HA doesn't expose today,
  IF a real need for it turns up - e.g. a rolling self-sufficiency trend
  server-side rather than the simple live today/today ratio this prototype
  computes client-side. Not needed for anything in this task.
- A GUI config editor (`getConfigElement()`), once the visual design itself
  is settled and worth building a picker/editor UX around.
