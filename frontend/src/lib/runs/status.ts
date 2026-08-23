import type { RunStatus } from '$lib/api/generated';

type StatusPresentation = {
  label: string;
  tone: 'neutral' | 'active' | 'waiting' | 'success' | 'danger';
  stopLabel: string | null;
  canStop: boolean;
  terminal: boolean;
};

export const INITIAL_RUN_STATUS: RunStatus = 'starting';

const STOP_RUN_LABEL = 'Stop run';
const STOP_REQUESTED_LABEL = 'Stop requested';
const STOPPING_LABEL = 'Stopping';

export const RUN_STATUS_PRESENTATION: Record<RunStatus, StatusPresentation> = {
  queued: {
    label: 'Queued',
    tone: 'waiting',
    stopLabel: 'Cancel queued run',
    canStop: true,
    terminal: false
  },
  starting: {
    label: 'Starting',
    tone: 'waiting',
    stopLabel: STOP_RUN_LABEL,
    canStop: true,
    terminal: false
  },
  running: {
    label: 'Running',
    tone: 'active',
    stopLabel: STOP_RUN_LABEL,
    canStop: true,
    terminal: false
  },
  stop_requested: {
    label: STOP_REQUESTED_LABEL,
    tone: 'waiting',
    stopLabel: STOP_REQUESTED_LABEL,
    canStop: false,
    terminal: false
  },
  stopping: {
    label: STOPPING_LABEL,
    tone: 'waiting',
    stopLabel: STOPPING_LABEL,
    canStop: false,
    terminal: false
  },
  stopped: {
    label: 'Stopped',
    tone: 'neutral',
    stopLabel: null,
    canStop: false,
    terminal: true
  },
  failed: {
    label: 'Failed',
    tone: 'danger',
    stopLabel: null,
    canStop: false,
    terminal: true
  },
  interrupted: {
    label: 'Interrupted',
    tone: 'danger',
    stopLabel: null,
    canStop: false,
    terminal: true
  }
};

export function runStatusLabel(status: RunStatus): string {
  return RUN_STATUS_PRESENTATION[status].label;
}

export function isRunStatus(value: unknown): value is RunStatus {
  return typeof value === 'string' && value in RUN_STATUS_PRESENTATION;
}

export function isTerminalRunStatus(status: RunStatus): boolean {
  return RUN_STATUS_PRESENTATION[status].terminal;
}
