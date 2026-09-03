import runtimeContract from '$lib/runtimeContract.fixture.json';

export function chartWindowPoints(
  basePoints: number,
  zoomLevel: number,
  minimumPoints: number,
  maximumPoints: number
): number {
  const scaled = basePoints * runtimeContract.dashboard.timeZoomFactor ** zoomLevel;
  const policy = runtimeContract.dashboard.chartWindowPolicy;
  let points: number;
  switch (policy.rounding) {
    case runtimeContract.dashboard.walletBucketRounding.FLOOR:
      points = Math.floor(scaled);
      break;
    default:
      throw new Error('Unsupported chart-window rounding policy');
  }
  if (policy.clampMinimum) points = Math.max(minimumPoints, points);
  if (policy.clampMaximum) points = Math.min(maximumPoints, points);
  return points;
}
