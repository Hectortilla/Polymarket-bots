import { PRESENTATION_COPY } from '$lib/presentation';
export function formatTime(value: string | null | undefined): string {
  return value ? new Date(value).toLocaleString() : PRESENTATION_COPY.NOT_AVAILABLE;
}
