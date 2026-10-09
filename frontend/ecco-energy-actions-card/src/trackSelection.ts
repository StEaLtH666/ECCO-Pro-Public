// Pure track (tab) selection logic for the card's `layout: tabbed`
// presentation - no Lit, no DOM, no hass object, no regex literals. Same
// separation of concerns as interlock.ts: the component computes BOTH
// tracks' display states on every render with the very same classifiers
// and overlays its two tiles use, and this module only decides which track
// to show first and whether the hidden track needs a cross-track alert. It
// never gates or issues a service call; each tile's own ARM / START / END
// handlers still target only that tile's own entities.

import type { FreePowerDisplayState } from "./schedule";
import type { DumpDisplayState } from "./dumpState";

export type Track = "free_power" | "dump_to_grid";

/** The two tiles' display states are the same nine-word vocabulary (visual state + the "scheduled" / "interlocked" overlays). */
export type DisplayStateLike = FreePowerDisplayState | DumpDisplayState;

/** Whether, and how loudly, the HIDDEN track's state must be announced above the visible panel. */
export type TrackAlert = "none" | "info" | "warning" | "fault";

/** The card's colour token a track alert is drawn with - null when no banner shows. */
export type AlertTone = "accent" | "warning" | "fault";

/**
 * What the track strip and the alert banner need to know about one track -
 * computed by the component from the same classifiers its tiles use.
 */
export interface TrackSummary {
  /** The track's display state after the schedule and interlock overlays, exactly as its tile's pill shows it. */
  state: DisplayStateLike;
  /** The `state-<pill>` class of its chip: the display state, or "locked" for the unconfigured Dump to Grid preview shell. */
  pill: DisplayStateLike | "locked";
  /** The pill label the tile shows for that state. */
  label: string;
  /** The firmware's literal status text, exactly as the tile shows it (undefined when the entity is not readable). */
  statusText: string | undefined;
}

// Most urgent first. The initial tab goes to whichever track currently
// needs the operator more; a tie goes to Free Power (the left tab).
const TRACK_PRIORITY: readonly DisplayStateLike[] = [
  "recovery_attention",
  "deferred",
  "busy",
  "active",
  "armed",
  "scheduled",
  "interlocked",
  "ready",
  "unavailable",
];

/** Urgency rank of a display state - 0 is the most urgent; an unknown word ranks after every known one. */
export function trackRank(state: DisplayStateLike): number {
  const index = TRACK_PRIORITY.indexOf(state);
  return index < 0 ? TRACK_PRIORITY.length : index;
}

/**
 * Whether the component may pin the initial track yet: false while BOTH
 * tracks are "unavailable" (device offline, entities not registered yet),
 * because that snapshot says nothing about which track needs the operator.
 * The choice waits for the first real state, so a recovery obligation that
 * surfaces when the device reconnects still wins the initial tab.
 */
export function canChooseTrack(freePower: DisplayStateLike, dumpToGrid: DisplayStateLike): boolean {
  return freePower !== "unavailable" || dumpToGrid !== "unavailable";
}

/**
 * The track to show when the card first has a real state. Dump to Grid is
 * chosen only when its state is STRICTLY more urgent than Free Power's;
 * every tie (including both ready, both unavailable) goes to Free Power.
 * The component calls this exactly once; afterwards only a tab click
 * changes the visible track - never a state change.
 */
export function initialTrack(freePower: DisplayStateLike, dumpToGrid: DisplayStateLike): Track {
  return trackRank(dumpToGrid) < trackRank(freePower) ? "dump_to_grid" : "free_power";
}

/**
 * Whether the hidden track's state earns the non-dismissible banner under
 * the tab selector. Only live inverter ownership or a recovery obligation
 * does: an armed, scheduled, interlocked, ready or unavailable hidden track
 * is announced by its chip in the header alone.
 */
export function hiddenTrackAlert(hiddenState: DisplayStateLike): TrackAlert {
  switch (hiddenState) {
    case "recovery_attention":
      return "fault";
    case "busy":
    case "deferred":
      return "warning";
    case "active":
      return "info";
    default:
      return "none";
  }
}

/** Maps an alert level to the colour token the banner is drawn with (info uses the card's accent, as the Active pill does). */
export function alertTone(alert: TrackAlert): AlertTone | null {
  switch (alert) {
    case "fault":
      return "fault";
    case "warning":
      return "warning";
    case "info":
      return "accent";
    default:
      return null;
  }
}

/** The product name of a track, as the tiles spell it. */
export function trackName(track: Track): string {
  return track === "dump_to_grid" ? "Dump to Grid" : "Free Power";
}

/**
 * The banner's text: the hidden track's name and state label (the same
 * label its own pill shows), followed by the firmware's literal status text
 * when there is one - never wording of our own about what the firmware is
 * doing.
 */
export function hiddenTrackAlertText(name: string, stateLabel: string, statusText: string | undefined): string {
  const status = statusText?.trim() ?? "";
  return status ? `${name}: ${stateLabel} - ${status}` : `${name}: ${stateLabel}`;
}
