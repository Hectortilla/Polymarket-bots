import {
  createBotApiV1BotsPost,
  createGraphTemplateApiV1GraphTemplatesPost,
  type BotRead,
  type NodeGraph,
} from '$lib/api/generated';
import type { LaunchInputs } from '$lib/catalog/schema';
import { DraftSaveFailure, DRAFT_WRITE } from './failure';
import { resolveDraftWrite } from './write';

/** Reuse confirmed writes when saving or navigation is retried in this editor. */
export class SavedBotDraft {
  private template: { id: string; graphJson: string } | undefined;
  private confirmedBotSave: { signature: string; bot: BotRead } | undefined;

  private uncertainFailure: DraftSaveFailure | undefined;

  async save(definitionId: string, inputs: LaunchInputs, graph: NodeGraph): Promise<BotRead> {
    // An unknown response may have committed; resending could create another bot.
    if (this.uncertainFailure) throw this.uncertainFailure;
    const graphJson = JSON.stringify(graph);
    const signature = JSON.stringify([definitionId, inputs, graphJson]);
    if (this.confirmedBotSave?.signature === signature) return this.confirmedBotSave.bot;
    try {
      if (this.template?.graphJson !== graphJson) {
        const template = await resolveDraftWrite(DRAFT_WRITE.TEMPLATE, createGraphTemplateApiV1GraphTemplatesPost({
          body: { name: `bot-draft-${Date.now()}`, graph },
        }));
        this.template = { id: template.id, graphJson };
      }
      const bot = await resolveDraftWrite(DRAFT_WRITE.BOT, createBotApiV1BotsPost({
        body: { definition_id: definitionId, inputs, graph_template_id: this.template.id },
      }));
      this.confirmedBotSave = { signature, bot };
      return bot;
    } catch (error) {
      if (error instanceof DraftSaveFailure && error.uncertain) this.uncertainFailure = error;
      throw error;
    }
  }
}
