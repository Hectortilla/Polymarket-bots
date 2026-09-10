import { get } from "svelte/store";
import { client } from "$lib/api/generated/client.gen";
import { CONTENT_TYPE_HEADER, HTTP_STATUS, JSON_CONTENT_TYPE } from "$lib/api/http";
import runtimeContract from "$lib/runtimeContract.fixture.json";
import { accountSession } from "./index";

let configured = false;

export function configureAccountBoundary(): void {
  if (configured) return;
  configured = true;
  client.setConfig({ credentials: "same-origin", headers: { [CONTENT_TYPE_HEADER]: JSON_CONTENT_TYPE } });
  client.interceptors.request.use((request) => {
    // The generated transport removes Content-Type from requests without bodies.
    if (!runtimeContract.auth.csrfSafeMethods.includes(request.method)) {
      request.headers.set(CONTENT_TYPE_HEADER, JSON_CONTENT_TYPE);
    }
    return request;
  });
  client.interceptors.response.use((response) => {
    if (response.status === HTTP_STATUS.UNAUTHORIZED && get(accountSession.account) !== null) {
      accountSession.expire();
    }
    return response;
  });
}
