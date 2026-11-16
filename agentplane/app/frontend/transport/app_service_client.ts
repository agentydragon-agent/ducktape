import { fromJson } from "@bufbuild/protobuf";

import { WatchSessionInventoryResponseSchema, type WatchSessionInventoryResponse } from "../../app_service_pb";
import { fetchText } from "./client";
import { followWatch, type WatchHandlers } from "./watch_stream";

/** One browser client for the AppService's generated JSON endpoints. */
export const appServiceClient = {
  getText(path: string): Promise<string> {
    return fetchText(path, { headers: { Accept: "application/json" } });
  },
  watchSessionInventory(
    handlers: Omit<WatchHandlers, "onFrame"> & {
      onFrame: (frame: WatchSessionInventoryResponse) => void;
    }
  ): () => void {
    return followWatch("/upstream/app/v1/sessions:watch", {
      ...handlers,
      onFrame: (value) => handlers.onFrame(fromJson(WatchSessionInventoryResponseSchema, value)),
    });
  },
};
