import contract from "$lib/runtimeContract.fixture.json" with { type: "json" };

export const ACCOUNT_COPY = {
  SETTINGS: "Account settings",
  RESET_TITLE: "Reset your password",
  FORGOT: "Forgot password?",
  SEND_RESET: "Send reset link",
  SEND_VERIFICATION: "Send verification link",
  SENT: `If a link can be sent to this address, it will arrive shortly and expire after ${contract.accountManagement.tokenLifetimeMinutes} minutes. Check your spam folder if it doesn’t arrive.`,
  DELIVERY_FAILED: "Email delivery is unavailable. Please try again later.",
  INVALID_LINK: "This link is no longer valid. Request a new one.",
  CURRENT_PASSWORD: "Current password",
  NEW_PASSWORD: "New password",
  CONFIRM_PASSWORD: "Confirm new password",
  PASSWORD_MISMATCH: "The new passwords do not match.",
  COMPLETE_RESET: "Reset password",
  COMPLETE_VERIFICATION: "Verify email and set password",
  CHANGE_PASSWORD: "Change password",
  REVOKE_OTHER: "Sign out other sessions",
  REVOKE_ALL: "Sign out all sessions",
  REAUTH_FAILED: contract.accountManagement.reauthenticationFailedDetail,
  DONE: "Account updated. Sign in to continue.",
  OTHERS_DONE: "Signed out on other browsers and devices. You’re still signed in here.",
  VERIFIED: "Your email is verified.",
  VERIFICATION_REQUIRED:
    "Verify your email before launching a paper run. You can still edit bots and use account settings.",
  LEGACY_ACCOUNT: "Your email is not verified. Verify it to confirm you can receive account emails.",
} as const;
