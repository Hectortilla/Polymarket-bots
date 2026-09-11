import type { EventView, StreamRunEventsApiV1RunsRunIdEventsStreamGetData } from "$lib/api/generated";
import runtimeContract from "$lib/runtimeContract.fixture.json";

export const EVENT_VIEW = runtimeContract.eventView as {
  [Key in keyof typeof runtimeContract.eventView]: Extract<EventView, Lowercase<Key>>;
};
export type ActivityEventView = NonNullable<
  NonNullable<StreamRunEventsApiV1RunsRunIdEventsStreamGetData["query"]>["view"]
>;
