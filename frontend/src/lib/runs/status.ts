import type { RunStatus } from '$lib/api/generated';
import runtimeContract from '$lib/runtimeContract.fixture.json';

type StatusPresentation = {
  label: string;
  tone: 'neutral' | 'active' | 'waiting' | 'success' | 'danger';
  stopLabel: string | null;
  canStop: boolean;
  terminal: boolean;
};

export const INITIAL_RUN_STATUS = runtimeContract.runStatus.initial as RunStatus;
type RunStatusContract = {
  [Key in keyof typeof runtimeContract.runStatus.values]: Extract<
    RunStatus,
    Lowercase<Key>
  >;
};
export const RUN_STATUS = runtimeContract.runStatus.values as RunStatusContract;
const TERMINAL_RUN_STATUSES = new Set<RunStatus>(
  runtimeContract.runStatus.terminal as RunStatus[]
);
const STOPPABLE_RUN_STATUSES = new Set<RunStatus>(
  runtimeContract.runStatus.stoppable as RunStatus[]
);
const ALL_RUN_STATUSES = new Set<RunStatus>(Object.values(RUN_STATUS));

const STOP_RUN_LABEL = 'Stop run';
const STOP_REQUESTED_LABEL = 'Stop requested';
const STOPPING_LABEL = 'Stopping';

export const RUN_STATUS_PRESENTATION: Record<RunStatus, StatusPresentation> = {
  [RUN_STATUS.QUEUED]: {
    label: 'Queued',
    tone: 'waiting',
    stopLabel: 'Cancel queued run',
    canStop: STOPPABLE_RUN_STATUSES.has(RUN_STATUS.QUEUED),
    terminal: TERMINAL_RUN_STATUSES.has(RUN_STATUS.QUEUED)
  },
  [RUN_STATUS.STARTING]: {
    label: 'Starting',
    tone: 'waiting',
    stopLabel: STOP_RUN_LABEL,
    canStop: STOPPABLE_RUN_STATUSES.has(RUN_STATUS.STARTING),
    terminal: TERMINAL_RUN_STATUSES.has(RUN_STATUS.STARTING)
  },
  [RUN_STATUS.RUNNING]: {
    label: 'Running',
    tone: 'active',
    stopLabel: STOP_RUN_LABEL,
    canStop: STOPPABLE_RUN_STATUSES.has(RUN_STATUS.RUNNING),
    terminal: TERMINAL_RUN_STATUSES.has(RUN_STATUS.RUNNING)
  },
  [RUN_STATUS.STOP_REQUESTED]: {
    label: STOP_REQUESTED_LABEL,
    tone: 'waiting',
    stopLabel: STOP_REQUESTED_LABEL,
    canStop: STOPPABLE_RUN_STATUSES.has(RUN_STATUS.STOP_REQUESTED),
    terminal: TERMINAL_RUN_STATUSES.has(RUN_STATUS.STOP_REQUESTED)
  },
  [RUN_STATUS.STOPPING]: {
    label: STOPPING_LABEL,
    tone: 'waiting',
    stopLabel: STOPPING_LABEL,
    canStop: STOPPABLE_RUN_STATUSES.has(RUN_STATUS.STOPPING),
    terminal: TERMINAL_RUN_STATUSES.has(RUN_STATUS.STOPPING)
  },
  [RUN_STATUS.STOPPED]: {
    label: 'Stopped',
    tone: 'neutral',
    stopLabel: null,
    canStop: STOPPABLE_RUN_STATUSES.has(RUN_STATUS.STOPPED),
    terminal: TERMINAL_RUN_STATUSES.has(RUN_STATUS.STOPPED)
  },
  [RUN_STATUS.FAILED]: {
    label: 'Failed',
    tone: 'danger',
    stopLabel: null,
    canStop: STOPPABLE_RUN_STATUSES.has(RUN_STATUS.FAILED),
    terminal: TERMINAL_RUN_STATUSES.has(RUN_STATUS.FAILED)
  },
  [RUN_STATUS.INTERRUPTED]: {
    label: 'Interrupted',
    tone: 'danger',
    stopLabel: null,
    canStop: STOPPABLE_RUN_STATUSES.has(RUN_STATUS.INTERRUPTED),
    terminal: TERMINAL_RUN_STATUSES.has(RUN_STATUS.INTERRUPTED)
  }
};

export function runStatusLabel(status: RunStatus): string {
  return RUN_STATUS_PRESENTATION[status].label;
}

export function isRunStatus(value: unknown): value is RunStatus {
  return typeof value === 'string' && ALL_RUN_STATUSES.has(value as RunStatus);
}

export function isTerminalRunStatus(status: RunStatus): boolean {
  return TERMINAL_RUN_STATUSES.has(status);
}
