import type { ErrorObject, ValidateFunction } from "ajv";
import { GRAPH_REQUEST_FIELD, readableValidationMessage, requestValidationIssues } from "$lib/api/requestErrors";
import { decodeJsonPointerSegment } from "$lib/jsonPointer";
import { type LaunchInputs, type LaunchValidationIssue } from "./contracts";
import { fieldLabel } from "./presentation";

const REQUEST_INPUTS_FIELD = "inputs";

export function launchValidationIssues(
  validator: ValidateFunction<LaunchInputs>,
  inputs: LaunchInputs,
): LaunchValidationIssue[] {
  if (validator(inputs)) return [];

  const uniqueIssues = new Map<string, LaunchValidationIssue>();
  for (const error of validator.errors ?? []) {
    const issue = launchValidationIssue(error);
    uniqueIssues.set(`${issue.field ?? ""}:${issue.message}`, issue);
  }
  return [...uniqueIssues.values()];
}

export function launchRequestValidationIssues(error: unknown): LaunchValidationIssue[] {
  return requestValidationIssues(error)
    .filter((issue) => !issue.loc.includes(GRAPH_REQUEST_FIELD))
    .map((issue) => ({
      field: requestInputField(issue.loc),
      message: readableValidationMessage(issue.msg),
    }));
}

export function visibleLaunchIssues(
  localIssues: LaunchValidationIssue[],
  serverIssues: LaunchValidationIssue[],
  touchedFields: ReadonlySet<string>,
  submitted: boolean,
): LaunchValidationIssue[] {
  return [
    ...localIssues.filter((issue) => (issue.field ? submitted || touchedFields.has(issue.field) : submitted)),
    ...serverIssues,
  ];
}

function launchValidationIssue(error: ErrorObject): LaunchValidationIssue {
  const path = error.instancePath.split("/").filter(Boolean).map(decodeJsonPointerSegment);
  const missingProperty =
    error.keyword === "required" && typeof error.params.missingProperty === "string"
      ? error.params.missingProperty
      : undefined;
  return {
    field: path[0] ?? missingProperty,
    message: ajvIssueMessage(error),
  };
}

function requestInputField(location: Array<string | number>): string | undefined {
  const inputsIndex = location.lastIndexOf(REQUEST_INPUTS_FIELD);
  if (inputsIndex < 0) return undefined;
  const field = location[inputsIndex + 1];
  return typeof field === "string" ? field : undefined;
}

function ajvIssueMessage(error: ErrorObject): string {
  const limit = error.params.limit;
  switch (error.keyword) {
    case "required": {
      const field = error.params.missingProperty;
      return typeof field === "string" ? `${fieldLabel(field, {})} is required.` : "This field is required.";
    }
    case "minLength":
      return typeof limit === "number"
        ? `Enter at least ${limit} ${limit === 1 ? "character" : "characters"}.`
        : "Enter a longer value.";
    case "maxLength":
      return typeof limit === "number" ? `Enter no more than ${limit} characters.` : "Enter a shorter value.";
    case "minItems":
      return typeof limit === "number"
        ? `Add at least ${limit} ${limit === 1 ? "item" : "items"}.`
        : "Add another item.";
    case "minimum":
      return typeof limit === "number" ? `Enter ${limit} or more.` : "Enter a larger value.";
    case "maximum":
      return typeof limit === "number" ? `Enter ${limit} or less.` : "Enter a smaller value.";
    case "type":
      return typeof error.params.type === "string"
        ? `Enter a valid ${friendlyJsonType(error.params.type)}.`
        : "Enter a valid value.";
    default:
      return readableValidationMessage(error.message ?? "This value is invalid");
  }
}

function friendlyJsonType(type: string): string {
  if (type === "array") return "list";
  if (type === "integer" || type === "number") return "number";
  return type;
}
