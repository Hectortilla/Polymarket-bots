import type { NodeGraph } from "$lib/api/generated";
import { graphValidationIssues, type GraphValidationIssue } from "$lib/catalog/graphValidation";
import { launchRequestValidationIssues, type LaunchValidationIssue } from "$lib/catalog/schema";
import { resourceLimitDetail } from "$lib/limits/validation";
import { DraftSaveFailure, DRAFT_WRITE } from "./failure";

export const DRAFT_SAVE_UNCERTAIN_COPY =
  "The save result is unknown. Return to your bots and check for the saved bot before creating another. This draft will not resend an uncertain write.";

export class DraftSaveFeedback {
  constructor(
    readonly inputIssues: LaunchValidationIssue[] = [],
    readonly graphIssues: GraphValidationIssue[] = [],
    readonly detail: string | undefined = undefined,
    readonly uncertain = false,
  ) {}

  static fromFailure(error: unknown, graph: NodeGraph): DraftSaveFeedback {
    if (!(error instanceof DraftSaveFailure)) return new DraftSaveFeedback();
    return new DraftSaveFeedback(
      error.stage === DRAFT_WRITE.BOT ? launchRequestValidationIssues(error.detail) : [],
      error.stage === DRAFT_WRITE.TEMPLATE ? graphValidationIssues(error.detail, graph) : [],
      error.uncertain ? DRAFT_SAVE_UNCERTAIN_COPY : resourceLimitDetail(error.detail),
      error.uncertain,
    );
  }

  message(fallback: string): string {
    if (this.detail !== undefined) return this.detail;
    if (this.inputIssues.length || this.graphIssues.length) return "";
    return fallback;
  }
}
