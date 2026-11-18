// @ts-check
// Dates as the redesigned screens show them, by this machine's clock: "Tuesday, 17 November",
// "Fri 20 Nov", "2 days late".

const DAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
  "September", "October", "November", "December"];
const DAY_MS = 24 * 60 * 60 * 1000;

/** @param {string} iso `YYYY-MM-DD` */
function toDate(iso) {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d);
}

/** "Tuesday, 17 November". @param {string} iso */
export function longDate(iso) {
  const d = toDate(iso);
  return `${DAYS[d.getDay()]}, ${d.getDate()} ${MONTHS[d.getMonth()]}`;
}

/** "Fri 20 Nov". @param {string} iso */
export function shortDate(iso) {
  const d = toDate(iso);
  return `${DAYS[d.getDay()].slice(0, 3)} ${d.getDate()} ${MONTHS[d.getMonth()].slice(0, 3)}`;
}

/** Whole days from `a` to `b`. @param {string} a @param {string} b */
export function daysBetween(a, b) {
  return Math.round((toDate(b).getTime() - toDate(a).getTime()) / DAY_MS);
}

/**
 * A due date as the Due block shows it: "2 days late", "Today" or "Fri 20 Nov".
 * @param {string} due
 * @param {string} now
 */
export function dueLabel(due, now) {
  const late = daysBetween(due, now);
  if (late > 0) return `${late} day${late === 1 ? "" : "s"} late`;
  return late === 0 ? "Today" : shortDate(due);
}

/**
 * A Note's day in Recent notes: "Today", a weekday this past week, else "12 Nov".
 * @param {string} day
 * @param {string} now
 */
export function noteDay(day, now) {
  const ago = daysBetween(day, now);
  if (ago === 0) return "Today";
  const d = toDate(day);
  if (ago > 0 && ago < 7) return DAYS[d.getDay()].slice(0, 3);
  return `${d.getDate()} ${MONTHS[d.getMonth()].slice(0, 3)}`;
}

/** "Tue 17 Nov 2026". @param {string} iso */
export function dayDate(iso) {
  return `${shortDate(iso)} ${toDate(iso).getFullYear()}`;
}

/** "11 Dec". @param {string} iso */
export function dayMonth(iso) {
  const d = toDate(iso);
  return `${d.getDate()} ${MONTHS[d.getMonth()].slice(0, 3)}`;
}

/**
 * When something happened, to the minute: "Mon 16 Nov, 17:12", with the year when it isn't
 * this year's. @param {string} isoDateTime `YYYY-MM-DDTHH:MM[:SS]` @param {string} now `YYYY-MM-DD`
 */
export function dayTime(isoDateTime, now) {
  const [day, time = ""] = isoDateTime.split("T");
  const year = day.slice(0, 4) === now.slice(0, 4) ? "" : ` ${day.slice(0, 4)}`;
  return `${shortDate(day)}${year}, ${time.slice(0, 5)}`;
}
