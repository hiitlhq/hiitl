/**
 * A date-time: the one reader of every field the specs type `date-time` (ecp_evaluate_spec.md "A date-time is read by
 * RFC 3339's grammar"; HTL-29 review, condition 5). Mirrors python/hiitl/core/date_time.py: both read the value by
 * RFC 3339 section 5.6's grammar and section 5.7's ranges, and one table of written values holds them to one answer
 * (tests/conformance/date_time/).
 *
 * A refusal names the element and its range; the field it was read for prefixes it with its name. The elements are
 * checked in the order they are written, so the first out of its range is the one named.
 */

import { z } from 'zod';

// Section 5.6: full-date "T" full-time, the offset "Z" or numeric; its note lets T and Z be lower case. A digit is
// DIGIT, 0-9 (RFC 5234's core rules)
const FORM_PATTERN =
  /^([0-9]{4})-([0-9]{2})-([0-9]{2})[Tt]([0-9]{2}):([0-9]{2}):([0-9]{2})(?:\.([0-9]+))?(?:[Zz]|([+-])([0-9]{2}):([0-9]{2}))$/;
const EXAMPLE = '2026-11-10T12:00:00Z';
export const FORM =
  "is not in RFC 3339's date-time form: a full date, T, a full time and its offset (Z, or +hh:mm or -hh:mm), " +
  `e.g. ${EXAMPLE}`;
export const NOT_A_STRING = `is not a string: a date-time is written in RFC 3339's form, e.g. ${EXAMPLE}`;
export const LEAP_SECOND = 'has second 60, a leap second: no core holds one, so it is refused rather than moved';
// What a core holds: the instants Python's datetime holds, the years 1 to 9999, read in UTC
const FIRST_YEAR = 1;
const LAST_YEAR = 9999;
const year4 = (y: number): string => String(y).padStart(4, '0');
export const HELD =
  `is outside the instants a core holds, ${year4(FIRST_YEAR)}-01-01T00:00:00Z to ` +
  `${year4(LAST_YEAR)}-12-31T23:59:59Z in UTC`;
// What is held is the instant with its offset as written, so a date written in a year no core holds is refused whatever
// its offset: hiitl's limit, not RFC 3339's, whose grammar writes the year 0000 (HTL-29 second review, condition 5)
export const YEAR =
  `has year 0000; a core holds the years ${year4(FIRST_YEAR)} to ${year4(LAST_YEAR)} as written, whatever the offset`;

// Section 5.6's ranges, each element's (what it is, low, high); a day's high is section 5.7's table, a second's 60 a
// leap second
const ELEMENTS: Record<string, [string, number, number]> = {
  month: ['a month', 1, 12],
  hour: ['an hour', 0, 23],
  minute: ['a minute', 0, 59],
  second: ['a second', 0, 59],
  'offset hour': ["an offset's hour", 0, 23],
  'offset minute': ["an offset's minute", 0, 59],
};
const DAYS = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
const LEAP_SECOND_WRITTEN = 60;
const MILLI = 3; // a Date holds a second's fraction to the millisecond
const MINUTE_MS = 60_000;

/** Section 5.7: February has 29 days in a year divisible by 4, and not by 100 unless by 400. */
function days(year: number, month: number): number {
  const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  return month === 2 && leap ? 29 : DAYS[month - 1];
}

const pad2 = (n: number): string => String(n).padStart(2, '0');

function outside(element: string, written: string): string | null {
  const [what, low, high] = ELEMENTS[element];
  const n = Number(written);
  return low <= n && n <= high ? null : `has ${element} ${written}; ${what} is ${pad2(low)} to ${pad2(high)}`;
}

/** The UTC epoch milliseconds of a written instant; years below 100 are set as written, never as 1900 plus. */
function epochMs(parts: number[], offsetMinutes: number): number {
  const [year, month, day, hour, minute, second, ms] = parts;
  const d = new Date(0);
  d.setUTCFullYear(year, month - 1, day);
  d.setUTCHours(hour, minute, second, ms);
  return d.getTime() - offsetMinutes * MINUTE_MS;
}

const FIRST = epochMs([FIRST_YEAR, 1, 1, 0, 0, 0, 0], 0);
const LAST = epochMs([LAST_YEAR, 12, 31, 23, 59, 59, 999], 0);

type Read = { instant: number; refusal: null } | { instant: null; refusal: string };

function readOrRefuse(value: unknown): Read {
  const refuse = (refusal: string): Read => ({ instant: null, refusal });
  if (typeof value !== 'string') return refuse(NOT_A_STRING);
  const m = FORM_PATTERN.exec(value);
  if (m === null) return refuse(FORM);
  const [, y, mo, d, h, mi, s, fraction, sign, oh, om] = m;
  const year = Number(y);
  const month = Number(mo);
  const first =
    (year < FIRST_YEAR ? YEAR : null) ??
    outside('month', mo) ??
    (1 <= Number(d) && Number(d) <= days(year, month)
      ? null
      : `has day ${d}; ${y}-${mo} has days 01 to ${pad2(days(year, month))}`) ??
    outside('hour', h) ??
    outside('minute', mi) ??
    (Number(s) === LEAP_SECOND_WRITTEN ? LEAP_SECOND : outside('second', s)) ??
    (sign ? outside('offset hour', oh) ?? outside('offset minute', om) : null);
  if (first !== null) return refuse(first);
  const ms = Number((fraction ?? '').slice(0, MILLI).padEnd(MILLI, '0')); // truncated, never rounded
  const offset = sign ? (sign === '-' ? -1 : 1) * (Number(oh) * 60 + Number(om)) : 0;
  const instant = epochMs([year, month, Number(d), Number(h), Number(mi), Number(s), ms], offset);
  return FIRST <= instant && instant <= LAST ? { instant, refusal: null } : refuse(HELD);
}

/** The sentence naming the element that refuses `value` and its range, or null when it is a date-time. */
export function dateTimeRefusal(value: unknown): string | null {
  return readOrRefuse(value).refusal;
}

/** The instant `value` writes, in UTC epoch milliseconds; throws carrying the refusal when it is none. */
export function readDateTime(value: unknown): number {
  const read = readOrRefuse(value);
  if (read.refusal !== null) throw new Error(read.refusal);
  return read.instant;
}

/** A core schema's date-time field: the written string, kept as written, refused by the reader naming the field. */
export const DateTimeSchema = z.custom<string>((value) => dateTimeRefusal(value) === null, {
  // Zod 4 finalizes an issue after its enclosing object supplies the path. The refinement context no longer has it.
  error: (issue) => `${String(issue.path?.[issue.path.length - 1])} ${dateTimeRefusal(issue.input)}`,
}).meta({type:'string',format:'date-time'});
