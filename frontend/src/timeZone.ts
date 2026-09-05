import { ref } from "vue";

const KEY = "subject-hub-tz";

export const ZONES = [
  { id: "Asia/Shanghai", name: "北京" },
  { id: "Asia/Tokyo", name: "东京" },
  { id: "Asia/Singapore", name: "新加坡" },
  { id: "Europe/London", name: "伦敦" },
  { id: "America/New_York", name: "纽约" },
  { id: "America/Los_Angeles", name: "洛杉矶" },
  { id: "UTC", name: "UTC" },
  { id: "local", name: "本机" },
] as const;

export type ZoneId = (typeof ZONES)[number]["id"];

function loadZone(): string {
  try {
    const v = localStorage.getItem(KEY);
    if (v && ZONES.some((z) => z.id === v)) return v;
  } catch {
    /* 无 localStorage 时用北京 */
  }
  return "Asia/Shanghai";
}

export const displayZone = ref(loadZone());

export function setDisplayZone(id: string) {
  if (!ZONES.some((z) => z.id === id)) return;
  displayZone.value = id;
  try {
    localStorage.setItem(KEY, id);
  } catch {
    /* ignore */
  }
}

export function resolvedZone(id = displayZone.value) {
  if (id === "local") return Intl.DateTimeFormat().resolvedOptions().timeZone || "Asia/Shanghai";
  return id;
}

export function zoneName(id = displayZone.value) {
  return ZONES.find((z) => z.id === id)?.name || "北京";
}

function offsetMinutesAt(instant: Date, timeZone: string) {
  const read = (name: "longOffset" | "shortOffset") =>
    new Intl.DateTimeFormat("en-US", {
      timeZone,
      timeZoneName: name,
      year: "numeric",
    })
      .formatToParts(instant)
      .find((p) => p.type === "timeZoneName")?.value || "";
  const raw = read("longOffset") || read("shortOffset");
  if (/^GMT$/i.test(raw.trim()) || raw === "UTC") return 0;
  const m = raw.match(/([+-])(\d{1,2})(?::?(\d{2}))?/);
  if (!m) return timeZone === "Asia/Shanghai" ? 480 : 0;
  return (m[1] === "-" ? -1 : 1) * (Number(m[2]) * 60 + Number(m[3] || 0));
}

export function toZoneInput(iso?: string | null, addMinutes = 0, timeZone = resolvedZone()) {
  const d = iso ? new Date(iso) : new Date();
  if (!Number.isFinite(d.getTime())) return "";
  if (!iso) d.setSeconds(0, 0);
  if (addMinutes) d.setTime(d.getTime() + addMinutes * 60_000);
  const stamp = d.toLocaleString("sv-SE", { timeZone });
  return stamp.slice(0, 16).replace(" ", "T");
}

export function fmtInZone(iso?: string | null, timeZone = resolvedZone()) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (!Number.isFinite(d.getTime())) return "—";
  const stamp = d.toLocaleString("sv-SE", { timeZone });
  const [date, time] = stamp.split(" ");
  const [, month, day] = date.split("-");
  const hm = time.slice(0, 5);
  return `${Number(month)}月${Number(day)}日 ${hm}`;
}

/** 把 datetime-local 数字当成当前所选时区的墙上时间，转成 UTC ISO。 */
export function zoneLocalToIso(local: string, timeZone = resolvedZone()) {
  const m = local.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/);
  if (!m) return new Date(NaN).toISOString();
  const y = Number(m[1]);
  const mo = Number(m[2]) - 1;
  const d = Number(m[3]);
  const h = Number(m[4]);
  const mi = Number(m[5]);
  let utc = Date.UTC(y, mo, d, h, mi);
  let off = offsetMinutesAt(new Date(utc), timeZone);
  utc = Date.UTC(y, mo, d, h, mi) - off * 60_000;
  off = offsetMinutesAt(new Date(utc), timeZone);
  utc = Date.UTC(y, mo, d, h, mi) - off * 60_000;
  return new Date(utc).toISOString();
}
