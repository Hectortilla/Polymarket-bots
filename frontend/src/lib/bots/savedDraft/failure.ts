export const DRAFT_WRITE = { TEMPLATE: 'template', BOT: 'bot' } as const;
export type DraftWrite = typeof DRAFT_WRITE[keyof typeof DRAFT_WRITE];

export class DraftSaveFailure extends Error {
  constructor(readonly stage: DraftWrite, readonly detail: unknown, readonly uncertain: boolean) {
    super('Private bot draft write failed');
  }
}
