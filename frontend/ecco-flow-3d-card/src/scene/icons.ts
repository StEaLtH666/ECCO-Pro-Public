// Inline icon paths (24 x 24 viewBox), drawn for this card so it has no
// dependency on ha-icon or any external icon font. Stroke-based, 1.8 px.

export type IconName =
  | "sun"
  | "pylon"
  | "home"
  | "battery"
  | "clock"
  | "plug"
  | "target"
  | "leaf"
  | "swap"
  | "heart"
  | "chevron"
  | "forecast"
  | "inverter"
  | "alert"
  | "moon";

export const ICONS: Record<IconName, string> = {
  sun: "M12 7.5a4.5 4.5 0 1 0 0 9 4.5 4.5 0 0 0 0-9zM12 2v2.2M12 19.8V22M2 12h2.2M19.8 12H22M4.9 4.9l1.6 1.6M17.5 17.5l1.6 1.6M4.9 19.1l1.6-1.6M17.5 6.5l1.6-1.6",
  pylon: "M9 22l3-19 3 19M6 22h12M7.2 9h9.6M8.4 14.5h7.2M4 9l3.2 3.5M20 9l-3.2 3.5M5 14.5l3.4 3M19 14.5l-3.4 3",
  home: "M3.5 11.5L12 4l8.5 7.5M6 10v10h12V10M10 20v-5h4v5",
  battery: "M7 5.5h10a1.5 1.5 0 0 1 1.5 1.5v13A1.5 1.5 0 0 1 17 21.5H7A1.5 1.5 0 0 1 5.5 20V7A1.5 1.5 0 0 1 7 5.5zM9.5 2.5h5M8.5 13.5h7v5h-7z",
  clock: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM12 7v5l3.5 2",
  plug: "M9 3v5M15 3v5M6 8h12v4a6 6 0 0 1-12 0V8zM12 18v3",
  target: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM12 7.5a4.5 4.5 0 1 0 0 9 4.5 4.5 0 0 0 0-9zM12 11a1 1 0 1 0 0 2 1 1 0 0 0 0-2z",
  leaf: "M5 19C6 11 11 5 20 4c0 9-5 15-13 15M5 19l7-7",
  swap: "M4 8h13l-3-3M20 16H7l3 3",
  heart: "M12 20s-7-4.5-7-10a4 4 0 0 1 7-2.5A4 4 0 0 1 19 10c0 5.5-7 10-7 10z",
  chevron: "M9 6l6 6-6 6",
  forecast: "M12 6.5a4 4 0 1 0 0 8 4 4 0 0 0 0-8zM12 2v1.6M4.9 4.9l1.2 1.2M19.1 4.9l-1.2 1.2M2 10.5h1.6M20.4 10.5H22M3 19h18M6 22h12",
  inverter: "M4 5h16v14H4zM8 9h8M8 13h5M16 15.5h.01",
  alert: "M12 3l10 18H2L12 3zM12 10v5M12 18v.5",
  moon: "M20 14.5A8.5 8.5 0 0 1 9.5 4 8.5 8.5 0 1 0 20 14.5z",
};
