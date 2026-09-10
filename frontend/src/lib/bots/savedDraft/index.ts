import { createBotApiV1BotsPost, type BotRead, type NodeGraph } from "$lib/api/generated";
import type { LaunchInputs } from "$lib/catalog/schema";
import { DraftSaveFailure } from "./failure";
import { resolveDraftWrite } from "./write";

/** Reuse confirmed writes when saving or navigation is retried in this editor. */
export class SavedBotDraft {
  private confirmedBotSave: { signature: string; bot: BotRead } | undefined;

  private uncertainFailure: DraftSaveFailure | undefined;

  async save(definitionId: string, inputs: LaunchInputs, graph: NodeGraph): Promise<BotRead> {
    // An unknown response may have committed; resending could create another bot.
    if (this.uncertainFailure) throw this.uncertainFailure;
    const graphJson = JSON.stringify(graph);
    const signature = JSON.stringify([definitionId, inputs, graphJson]);
    if (this.confirmedBotSave?.signature === signature) return this.confirmedBotSave.bot;
    try {
      const bot = await resolveDraftWrite(
        createBotApiV1BotsPost({
          body: { definition_id: definitionId, inputs, graph },
        }),
      );
      this.confirmedBotSave = { signature, bot };
      return bot;
    } catch (error) {
      if (error instanceof DraftSaveFailure && error.uncertain) this.uncertainFailure = error;
      throw error;
    }
  }
}
