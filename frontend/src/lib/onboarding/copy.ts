export const ONBOARDING_COPY = {
  START: "Create your first paper bot",
  TITLE: "Start with an example",
  CHOOSE: "Choose an example",
  SETTINGS: "Paper settings",
  REVIEW: "Review and save",
  CONTINUE: "Continue to settings",
  BACK: "Back",
  SAVE: "Save private bot",
  SAVING: "Saving private bot…",
  LOADING: "Loading examples…",
  LOAD_ERROR: "Examples are unavailable. Try again, or return to your bots.",
  SAVE_ERROR: "The bot could not be saved. Your choices are still here; review them and retry.",
  RETRY: "Try again",
  NO_LAUNCH: "Saving creates a private bot. Nothing runs until you choose Run bot on its saved page.",
  PARAMETERS: "Example conditions",
  PAPER_ONLY:
    "Paper cash and fills are simulated. Conditions may never be met; this example does not promise a trade or a return.",
  ADVANCED: "Open the full strategy editor",
  VERIFY: "Verify your email in Account settings before your first Run.",
} as const;

export const ONBOARDING_STEP = { EXAMPLE: "example", SETTINGS: "settings", REVIEW: "review" } as const;
export type OnboardingStep = (typeof ONBOARDING_STEP)[keyof typeof ONBOARDING_STEP];

export const ONBOARDING_STEP_LABEL = {
  [ONBOARDING_STEP.EXAMPLE]: ONBOARDING_COPY.CHOOSE,
  [ONBOARDING_STEP.SETTINGS]: ONBOARDING_COPY.SETTINGS,
  [ONBOARDING_STEP.REVIEW]: ONBOARDING_COPY.REVIEW,
} as const satisfies Record<OnboardingStep, string>;
