export const RUN_COPY = { READ_ONLY: "Read only", STREAM_HEALTH: "Stream health" } as const;

export const RUN_EVENT_COPY = {
  RUN_STATUS: "Run status",
  RUN_ERROR: "Run error",
  ORDER_ERROR: "Order error",
  ORDER_RESULT: "Order result",
  SETTLEMENT: "Settlement",
  WARNING: "Warning",
  ERROR: "Error",
  BOT_ACTIVITY: "Bot activity",
  STARTUP_PROGRESS: "Startup progress",
  ORDER_SUBMITTED: "Order submitted",
  PORTFOLIO_UPDATE: "Portfolio update",
  FOLLOWED_WALLET_TRADE: "Followed wallet trade",
  CHART_UPDATE: "Chart update",
} as const;
