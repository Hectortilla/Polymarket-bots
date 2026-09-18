export const ONBOARDING_COPY = {
  START: "Create a bot from an example",
  TITLE: "Start with an example",
  CHOOSE: "Choose an example",
  SETTINGS: "Paper settings",
  REVIEW: "Review and save",
  CONTINUE: "Continue to settings",
  BACK: "Back",
  SAVE: "Save bot",
  SAVING: "Saving bot…",
  LOADING: "Loading examples…",
  LOAD_ERROR: "Examples are unavailable. Try again, or return to your bots.",
  SAVE_ERROR: "The bot could not be saved. Your choices are still here; review them and retry.",
  NO_LAUNCH: "Saving does not start a run. Choose Run bot on the saved bot page when you’re ready.",
  PARAMETERS: "Example conditions",
  PAPER_ONLY: "Runs use simulated funds. No real trades are placed.",
  ADVANCED: "Open the full strategy editor",
} as const;

export const ONBOARDING_STEP = { EXAMPLE: "example", SETTINGS: "settings", REVIEW: "review" } as const;
export type OnboardingStep = (typeof ONBOARDING_STEP)[keyof typeof ONBOARDING_STEP];

export const ONBOARDING_STEP_LABEL = {
  [ONBOARDING_STEP.EXAMPLE]: ONBOARDING_COPY.CHOOSE,
  [ONBOARDING_STEP.SETTINGS]: ONBOARDING_COPY.SETTINGS,
  [ONBOARDING_STEP.REVIEW]: ONBOARDING_COPY.REVIEW,
} as const satisfies Record<OnboardingStep, string>;
