export function annotationProgress(
  turnIds: string[],
  annotations: Record<string, { scores: Record<string, number | null> }>,
  prefix: string,
  dimensions: string[],
  min: number,
  max: number,
  skipped = false,
) {
  const done = turnIds.filter((id) => {
    const scores = annotations[prefix + '/' + id]?.scores;
    return (
      scores &&
      dimensions.length > 0 &&
      dimensions.every(
        (key) =>
          typeof scores[key] === 'number' &&
          Number.isFinite(scores[key]) &&
          scores[key]! >= min &&
          scores[key]! <= max,
      )
    );
  }).length;
  return {
    done,
    total: turnIds.length,
    pending: skipped ? 0 : turnIds.length - done,
    ignored: skipped ? turnIds.length - done : 0,
    status: skipped
      ? 'skipped'
      : turnIds.length && done === turnIds.length
        ? 'done'
        : done
          ? 'partial'
          : 'pending',
  };
}
