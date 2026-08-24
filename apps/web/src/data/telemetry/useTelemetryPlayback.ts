// =====================================================================
// Full Shelf — deterministic presentation clock for telemetry playback
// ---------------------------------------------------------------------
// Advances a presentation clock from the start of the telemetry window
// to the projection boundary, so markers move along their planned runs
// and then settle exactly at the boundary. The boundary is the stopping
// point: playback never runs past the as_of the projection was read at.
//
// Under `prefers-reduced-motion` there is no animation at all — the
// clock is pinned to the boundary and markers are drawn once, at their
// last reported sample position.
// =====================================================================

import { useEffect, useMemo, useState } from "react";
import { FixtureTelemetryDataSource, minutesOf } from "./fixture";
import { playbackAt, type TelemetryPlayback } from "./playback";
import type { VehicleTelemetryDataSource } from "./types";

/** Wall-clock ms per simulated minute; ~28s for the full 07:30→08:20 run. */
const MS_PER_SIM_MINUTE = 560;
const FRAME_MS = 80;

const DEFAULT_SOURCE = new FixtureTelemetryDataSource();

function prefersReducedMotion(): boolean {
  return typeof window !== "undefined" && !!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
}

/**
 * @param asOf The projection boundary. Playback is bounded by it, so no
 *   sample or health event from a later beat can appear early.
 */
export function useTelemetryPlayback(
  asOf: string | undefined,
  source: VehicleTelemetryDataSource = DEFAULT_SOURCE,
): TelemetryPlayback | undefined {
  const boundary = asOf ? minutesOf(asOf) : undefined;
  // The window opens at the earliest sample the boundary actually admits.
  const start = useMemo(() => {
    if (!asOf) return undefined;
    const feed = source.feedAsOf(asOf);
    if (!feed.samples.length) return undefined;
    return Math.min(...feed.samples.map((s) => minutesOf(s.recorded_at)));
  }, [asOf, source]);

  const [at, setAt] = useState<number | undefined>(boundary);

  useEffect(() => {
    if (boundary === undefined || start === undefined) return;
    if (prefersReducedMotion()) {
      setAt(boundary); // settled state, no motion
      return;
    }
    setAt(start);
    let sim = start;
    const id = window.setInterval(() => {
      sim = Math.min(boundary, sim + (FRAME_MS / MS_PER_SIM_MINUTE));
      setAt(sim);
      if (sim >= boundary) window.clearInterval(id);
    }, FRAME_MS);
    return () => window.clearInterval(id);
  }, [boundary, start]);

  return useMemo(() => {
    if (!asOf || boundary === undefined) return undefined;
    // Clamp defensively: the presentation clock may never exceed the
    // boundary, whatever a timer does.
    const clock = Math.min(at ?? boundary, boundary);
    return playbackAt(source, asOf, clock);
  }, [asOf, at, boundary, source]);
}
