export const GRAPH_TEMPLATE_COPY = {
  CREATE: 'Create template',
  LOAD_ERROR: 'Graph templates could not be loaded.',
  MISSING_CAPABILITY: 'No graph-capable bot definition is available.',
  NAME: 'Template name',
  NAME_REQUIRED: 'Enter a template name.',
  NAME_TOO_LONG: (maximumLength: number) =>
    `Use ${maximumLength} characters or fewer.`,
  NEW: 'New template',
  SAVE: 'Save template',
  SAVE_ERROR: 'The graph template could not be saved. Its name must be unique and its graph valid.'
} as const;
