// The ONLY module of this card that touches the Home Assistant connection, and it can send exactly two read-only messages:
//
//   weather/subscribe_forecast            Home Assistant's own way for a frontend card to receive a weather entity's hourly or
//                                         daily forecast (the same data the weather.get_forecasts action returns, pushed on
//                                         every forecast update; unsubscribed when the card leaves the page)
//   recorder/statistics_during_period     hourly long-term statistics (`change`) of one energy counter, for actual PV
//
// Nothing else is reachable: the card stores this reader, never the Home Assistant object or its connection, and the static
// tests pin the message types below as the complete set. No service / action call, no event subscription, no write.
import type { ForecastEntry, StatRow } from "./types.ts";

export const WS_FORECAST = "weather/subscribe_forecast";
export const WS_STATISTICS = "recorder/statistics_during_period";

export interface ConnectionLike {
  subscribeMessage(callback: (msg: unknown) => void, message: Record<string, unknown>): Promise<() => unknown>;
  sendMessagePromise(message: Record<string, unknown>): Promise<unknown>;
}

export interface Reader {
  subscribeForecast(entityId: string, kind: "hourly" | "daily", onForecast: (entries: ForecastEntry[]) => void): Promise<() => void>;
  hourlyStatistics(statisticId: string, startMs: number, endMs: number): Promise<StatRow[]>;
}

function isConnection(c: unknown): c is ConnectionLike {
  return c !== null && typeof c === "object" && typeof (c as ConnectionLike).subscribeMessage === "function" &&
    typeof (c as ConnectionLike).sendMessagePromise === "function";
}

const readers = new WeakMap<object, Reader>();

/** The reader for this connection (one per connection object, so the card can detect a new connection by comparing readers
 *  and never needs to keep the connection itself), or null when the object is not a Home Assistant websocket connection. */
export function readerFor(connection: unknown): Reader | null {
  if (!isConnection(connection)) return null;
  let r = readers.get(connection);
  if (!r) {
    r = makeReader(connection) as Reader;
    readers.set(connection, r);
  }
  return r;
}

/** A reader bound to one connection, or null when the object is not a Home Assistant websocket connection. */
export function makeReader(connection: unknown): Reader | null {
  if (!isConnection(connection)) return null;
  const conn = connection;
  return {
    async subscribeForecast(entityId, kind, onForecast) {
      const unsub = await conn.subscribeMessage((msg) => {
        const f = msg !== null && typeof msg === "object" ? (msg as { forecast?: unknown }).forecast : undefined;
        onForecast(Array.isArray(f) ? (f.filter((x) => x !== null && typeof x === "object") as ForecastEntry[]) : []);
      }, { type: WS_FORECAST, entity_id: entityId, forecast_type: kind });
      return () => {
        try {
          const r = unsub();
          if (r && typeof (r as Promise<unknown>).catch === "function") (r as Promise<unknown>).catch(() => undefined);
        } catch {
          // already closed
        }
      };
    },
    async hourlyStatistics(statisticId, startMs, endMs) {
      const res = await conn.sendMessagePromise({
        type: WS_STATISTICS,
        start_time: new Date(startMs).toISOString(),
        end_time: new Date(endMs).toISOString(),
        statistic_ids: [statisticId],
        period: "hour",
        types: ["change"],
        units: { energy: "kWh" },
      });
      const rows = res !== null && typeof res === "object" ? (res as Record<string, unknown>)[statisticId] : undefined;
      return Array.isArray(rows) ? (rows as StatRow[]) : [];
    },
  };
}
