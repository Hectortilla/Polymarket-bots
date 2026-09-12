import type { BotDefinitionDescriptor, PaperRunConfig } from "$lib/api/generated";
import { WIDGET_KIND, type LaunchInputs } from "./contracts";
import { launchFields, resolvedFieldSchema, widgetKind } from "./fields";

export function initialLaunchInputs(descriptor: BotDefinitionDescriptor): LaunchInputs {
  return Object.fromEntries(
    launchFields(descriptor).map(([name, field]) => {
      const schema = resolvedFieldSchema(descriptor, field);
      if (field.default !== undefined) return [name, field.default];
      if (schema.default !== undefined) return [name, schema.default];
      if (schema.type === "array") return [name, []];
      if (schema.type === "boolean") return [name, false];
      return [name, ""];
    }),
  );
}

export function launchInputsFromConfig(descriptor: BotDefinitionDescriptor, config: PaperRunConfig): LaunchInputs {
  return Object.fromEntries(
    launchFields(descriptor).map(([name, field]) => {
      const widget = widgetKind(field);
      if (widget === WIDGET_KIND.MARKET_SLUGS) {
        return [name, [...new Set(config.stream_rules.flatMap((rule) => rule.market_slugs ?? []))]];
      }
      if (widget === WIDGET_KIND.WALLET_ADDRESSES) {
        return [name, [...new Set(config.stream_rules.flatMap((rule) => rule.wallet_addresses ?? []))]];
      }
      return [name, config[name as keyof PaperRunConfig]];
    }),
  );
}
