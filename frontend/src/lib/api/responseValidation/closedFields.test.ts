import document from "../../../../../backend/contracts/openapi/control-plane.json";
import catalogContract from "$lib/catalog/catalogContract.fixture.json";
import previewFixture from "$lib/catalog/graphPreview.fixture.json";
import runtimeContract from "$lib/runtimeContract.fixture.json";
import Ajv from "ajv";
import { describe, expect, it } from "vitest";
import { isAccountUsage } from "$lib/limits/validation";
import { isBot } from "./bots";
import { isDefinition } from "./catalog";
import { isNodeGraph } from "./graph";
import { isGraphCatalog } from "./graph/catalog";
import { isGraphPreviewResponse } from "./graph/preview";
import { isHealthResponse } from "./health";
import { isPaperConfig } from "./paperConfig";
import { isRun } from "./runs";

const ajv = new Ajv({ strict: false, validateFormats: false });
const createdAt = "2026-09-02T00:00:00Z";
const paperConfig = {
  name: "Schema parity",
  paper_portfolio_usdc: "1000",
  max_order_size: "10",
  max_slippage_pct: "0.01",
  paper_latency_ms: 0,
  paper_latency_jitter_ms: 0,
  event_max_age_ms: 5000,
  data_trades_budget_per_10s: 1,
  stream_rules: [],
  graph: previewFixture.request.graph,
};
const definition = {
  definition_id: "parity",
  display_name: "Parity",
  description: "Closed response contracts",
  label: catalogContract.botDefinitionLabel.STANDARD,
  input_schema: {},
  market_selection: catalogContract.selectionMode.USER_CONFIGURED,
  wallet_selection: catalogContract.selectionMode.ABSENT,
  graph_catalog: catalogContract.graphNodeCatalog,
  starter_graph: previewFixture.request.graph,
};
const bot = {
  id: "00000000-0000-4000-8000-000000000001",
  definition_id: definition.definition_id,
  created_at: createdAt,
  updated_at: createdAt,
  config: paperConfig,
};
const cases: [string, (value: Record<string, unknown>) => boolean, object][] = [
  ["HealthResponse", isHealthResponse, { status: runtimeContract.healthStatus }],
  ["PaperRunConfig", isPaperConfig, paperConfig],
  ["BotRead", isBot, bot],
  [
    "RunRead",
    isRun,
    { ...bot, bot_id: bot.id, status: runtimeContract.runStatus.values.RUNNING, updated_at: undefined },
  ],
  ["BotDefinitionDescriptor", isDefinition, definition],
  ["GraphNodeCatalog", isGraphCatalog, catalogContract.graphNodeCatalog],
  ["NodeGraph", isNodeGraph, previewFixture.request.graph],
  ["GraphPreviewResponse", isGraphPreviewResponse, previewFixture.response],
  [
    "AccountUsage",
    isAccountUsage,
    { active_runs: 0, queued_runs: 0, saved_bots: 0, retained_runs: 0, policy: runtimeContract.resourcePolicy },
  ],
];

describe("closed response objects", () => {
  it.each(cases)("rejects extra fields at every closed %s boundary", (model, guard, fixture) => {
    const validate = ajv.compile({ components: document.components, $ref: `#/components/schemas/${model}` });
    const value = JSON.parse(JSON.stringify(fixture));
    expect(validate(value), JSON.stringify(validate.errors)).toBe(true);
    expect(guard(value)).toBe(true);
    let checked = 0;
    for (const path of objectPaths(value)) {
      const changed = structuredClone(value);
      const target = path.reduce((nested, key) => nested[key], changed);
      target.unexpected_contract_field = true;
      // Open dictionaries and SDK dataclass projections intentionally allow extras.
      if (validate(changed)) continue;
      expect(guard(changed), `${model}.${path.join(".")}`).toBe(false);
      checked += 1;
    }
    expect(checked).toBeGreaterThan(0);
  });
});

function objectPaths(value: unknown, path: string[] = []): string[][] {
  if (value === null || typeof value !== "object") return [];
  const children = Object.entries(value).flatMap(([key, child]) => objectPaths(child, [...path, key]));
  return Array.isArray(value) ? children : [path, ...children];
}
