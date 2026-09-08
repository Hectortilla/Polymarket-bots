import { readBotApiV1BotsBotIdGet, type BotRead } from '$lib/api/generated';
import { HTTP_STATUS } from '$lib/api/http';

export class BotNotFoundError extends Error {}

export async function readSavedBot(botId: string): Promise<BotRead> {
  const result = await readBotApiV1BotsBotIdGet({ path: { bot_id: botId } });
  if (result.data) return result.data;
  if (result.response?.status === HTTP_STATUS.NOT_FOUND) throw new BotNotFoundError();
  throw new Error('Saved bot unavailable');
}
