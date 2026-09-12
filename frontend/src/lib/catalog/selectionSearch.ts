export type SelectionSuggestion = {
  id: string;
  title: string;
  subtitle?: string | null;
  detail?: string | null;
  unavailable?: boolean;
};

export type SelectionSource = {
  limits: { minimumQueryLength: number; maximumQueryLength: number; defaultLimit: number; maximumSelections: number };
  copy: {
    PLACEHOLDER: string;
    NO_RESULTS: string;
    SEARCH_ERROR: string;
    RETRY_SEARCH: string;
    RETRY_DETAILS: string;
    UNAVAILABLE: string;
    MISSING: string;
    LOOKUP_ERROR: string;
    TYPE_HINT: string;
    RESULTS_LABEL: string;
    SELECTED_LABEL: string;
    SELECTION_HINT: string;
  };
  search: (query: string, signal: AbortSignal) => Promise<{ items: SelectionSuggestion[]; has_more: boolean }>;
  lookup: (ids: string[], signal: AbortSignal) => Promise<SelectionSuggestion[]>;
};
