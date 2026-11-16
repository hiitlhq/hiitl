import { describe, expect, it, vi } from 'vitest';
import { recordMeasurement } from '../../../../test-support/measurements.js';

describe('test measurements are recorded at their producer', () => {
  it('writes exactly the supplied measurement as one readable JSON event', () => {
    const measurement = {
      metric: 'fixture duration', unit: 'ms', source: 'authored-fixture#the-cell', value: 2.75,
      sample_count: 4, statistic: 'arithmetic mean',
    };
    const output = vi.spyOn(console, 'log').mockImplementation(() => {});
    try {
      recordMeasurement(measurement);
      expect(output.mock.calls).toEqual([[`HTL30_MEASUREMENT ${JSON.stringify(measurement)}`]]);
      const encoded = output.mock.calls[0][0] as string;
      expect(JSON.parse(encoded.slice('HTL30_MEASUREMENT '.length))).toEqual(measurement);
    } finally {
      output.mockRestore();
    }
  });
});
