/** Read declarations as declarations: a missing anchor or malformed row is an error, never an empty test loop. */
export function requiredMatch(text: string, pattern: RegExp, declaration: string): RegExpMatchArray {
  const match = text.match(pattern);
  if (!match) throw new Error(`Unread declaration: ${declaration}`);
  return match;
}

/** A numeric target is read from its source sentence's first capture, never supplied by a test-local fallback. */
export function declaredNumber(text: string, pattern: RegExp, declaration: string): number {
  const captured = requiredMatch(text, pattern, declaration)[1];
  const value = Number(captured);
  if (captured === undefined || captured.trim() === '' || !Number.isFinite(value)) {
    throw new Error(`Unread declaration: ${declaration}`);
  }
  return value;
}

export function typicalCoreBudgetMs(source: string): number {
  return declaredNumber(source,
    /^- \*\*Typical core evaluation\*\*: < ([\d.]+)ms for typical policies\.$/m,
    'decision_response.md typical-core target');
}

export function declaredTable(text: string, heading: string): string[][] {
  const escaped = heading.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const following = requiredMatch(text, new RegExp(`^(?:- )?${escaped}[^\\n]*\\n([\\s\\S]*)`, 'm'), heading)[1];
  const table = requiredMatch(following, /^(?:(?!#{1,6} )[^|\n][^\n]*\n|\n)*(\|[^\n]+\n\|[- :|]+\n(?:\|[^\n]+(?:\n|$))+)/,
    `${heading}: its table, including data rows`)[1];
  return table.trimEnd().split('\n').slice(2)
    .map((line) => line.split(/(?<!\\)\|/).slice(1, -1).map((cell) => cell.trim()));
}
