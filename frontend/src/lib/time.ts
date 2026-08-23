export function formatTime(value: string | null | undefined): string {
  return value ? new Date(value).toLocaleString() : 'Not available';
}
