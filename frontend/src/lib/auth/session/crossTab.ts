const ACCOUNT_CHANGE_CHANNEL_NAME = 'polybot-account';
const ACCOUNT_CHANGED_EVENT = 'changed';

export class AccountChannel {
  private channel: BroadcastChannel | undefined;

  watch(onChange: () => void): () => void {
    if (typeof BroadcastChannel === 'undefined') return () => {};
    const channel = new BroadcastChannel(ACCOUNT_CHANGE_CHANNEL_NAME);
    this.channel = channel;
    channel.onmessage = (event: MessageEvent<unknown>) => {
      if (event.data === ACCOUNT_CHANGED_EVENT) onChange();
    };
    return () => {
      channel.close();
      if (this.channel === channel) this.channel = undefined;
    };
  }

  announce(): void {
    this.channel?.postMessage(ACCOUNT_CHANGED_EVENT);
  }
}
