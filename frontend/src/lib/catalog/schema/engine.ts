import Ajv, { type AnySchemaObject } from "ajv";
import { WIDGET_SCHEMA_KEY } from "./contracts";

const OPENAPI_DISCRIMINATOR_KEY = "discriminator";
export const launchSchemaEngine = new Ajv({ allErrors: true });
launchSchemaEngine.addKeyword(OPENAPI_DISCRIMINATOR_KEY);
launchSchemaEngine.addKeyword(WIDGET_SCHEMA_KEY);

export function isLaunchInputSchema(schema: AnySchemaObject): boolean {
  try {
    return launchSchemaEngine.validateSchema(schema) === true;
  } catch {
    return false;
  }
}
