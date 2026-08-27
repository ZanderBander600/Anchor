/**
 * Presentation-only formatting helpers, mirroring
 * ``src/anchor/formatting.py``. These never alter the underlying
 * numeric value -- only how it is displayed.
 */

export function formatCurrency(value: number | null | undefined): string {
  if (value === null || value === undefined) {
    return 'N/A';
  }
  const sign = value < 0 ? '-' : '';
  const magnitude = Math.abs(value).toLocaleString('en-US', {
    maximumFractionDigits: 0,
  });
  return `${sign}$${magnitude}`;
}

export function formatPercent(
  value: number | null | undefined,
  decimals = 2,
): string {
  if (value === null || value === undefined) {
    return 'N/A';
  }
  return `${(value * 100).toFixed(decimals)}%`;
}

export function formatMultiple(value: number | null | undefined): string {
  if (value === null || value === undefined) {
    return 'N/A';
  }
  return `${value.toFixed(2)}x`;
}
