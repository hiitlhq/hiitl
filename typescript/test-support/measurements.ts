/** Test-run evidence, not a baseline or an undeclared pass/fail limit. */
export interface Measurement {
  metric: string;
  unit: string;
  source: string;
  value: number;
  sample_count?: number;
  statistic?: string;
}

export function recordMeasurement(measurement: Measurement): void {
  console.log(`HTL30_MEASUREMENT ${JSON.stringify(measurement)}`);
}
