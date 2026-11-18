import { describe, expect, it } from 'vitest';
import { declaredNumber, declaredTable, requiredMatch, typicalCoreBudgetMs } from '../../../../test-support/declarations.js';

describe('test declarations are read completely at their anchors', () => {
  const rows = [['alpha', '`local`'], ['beta', '`remote`']];
  const table = ['| Option | Mode |', '|---|---|', ...rows.map((row) => `| ${row.join(' | ')} |`)].join('\n');
  const heading = '### Modes';
  it('reads every declared row in order, without the header', () => {
    expect(declaredTable(`${heading}\n\nThe declaration follows.\n\n${table}\n\nOther prose`, heading)).toEqual(rows);
  });
  it('also anchors a declaration written as a list item', () => {
    expect(declaredTable(`- **Settings.** The declared settings.\n\n${table}`, '**Settings.**')).toEqual(rows);
  });
  it.each([
    table,
    `${heading}\n\n| Option | Mode |\n|---|---|\n`,
    `${heading}\n\n### A different declaration\n\n${table}`,
  ])('refuses a missing anchor, missing data or a different section', (source) => {
    expect(() => declaredTable(source, heading)).toThrow(/Unread declaration/);
  });
  it('names the unread sentence instead of returning empty matches', () => {
    expect(() => requiredMatch('another statement', /^Required: (.+)$/, 'the required statement'))
      .toThrow('Unread declaration: the required statement');
  });
  it('reads the number the declaration states without substituting a target', () => {
    const target = 17.25;
    expect(declaredNumber(`Budget: < ${target} ms`, /^Budget: < ([\d.]+) ms$/, 'fixture budget')).toBe(target);
  });
  it.each(['absent budget', 'Budget: < unread ms'])('refuses an unread numeric declaration', (source) => {
    expect(() => declaredNumber(source, /^Budget: < (.+) ms$/, 'fixture budget'))
      .toThrow('Unread declaration: fixture budget');
  });
  it('reads the typical-core budget from public timing metadata', () => {
    const target = 7.25;
    const source = `Example: 999ms\n- **Typical core evaluation**: < ${target}ms for typical policies.\n`;
    expect(typicalCoreBudgetMs(source)).toBe(target);
  });
  it('refuses a missing public typical-core declaration', () => {
    expect(() => typicalCoreBudgetMs('- **Pure local mode**: Single-digit milliseconds (< 10ms)\n'))
      .toThrow('Unread declaration: decision_response.md typical-core target');
  });
});
