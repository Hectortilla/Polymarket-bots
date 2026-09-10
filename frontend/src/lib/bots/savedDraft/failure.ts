export class DraftSaveFailure extends Error {
  constructor(
    readonly detail: unknown,
    readonly uncertain: boolean,
  ) {
    super("Private bot draft write failed");
  }
}
