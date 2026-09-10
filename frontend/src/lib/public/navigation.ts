export const PUBLIC_INFORMATION_PATH = {
  WELCOME: "/welcome",
  HELP: "/help",
  PRIVACY: "/privacy",
  TERMS: "/terms",
  SUPPORT: "/support",
} as const;
export const PUBLIC_INFORMATION_LABEL = {
  [PUBLIC_INFORMATION_PATH.WELCOME]: "Overview",
  [PUBLIC_INFORMATION_PATH.HELP]: "Help",
  [PUBLIC_INFORMATION_PATH.PRIVACY]: "Privacy",
  [PUBLIC_INFORMATION_PATH.TERMS]: "Terms",
  [PUBLIC_INFORMATION_PATH.SUPPORT]: "Support",
} as const;

export const PUBLIC_INFORMATION_NAV_LABEL = "Public information";
export const PUBLIC_PRELOAD_DATA_POLICY = "off" as const;

export function isPublicInformationPath(path: string): boolean {
  // Match encoded route names without decoding reserved separators or double-encoded paths.
  let decodedPath: string;
  try {
    decodedPath = decodeURI(path);
  } catch {
    return false;
  }
  return Object.values(PUBLIC_INFORMATION_PATH).some((publicPath) => decodedPath === publicPath);
}
