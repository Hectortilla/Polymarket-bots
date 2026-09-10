import { expect, it } from 'vitest';
import { isPublicInformationPath, PUBLIC_INFORMATION_PATH } from './navigation';
import { NAVIGATION_PATH, botPath, runPath } from '$lib/navigation';

it('admits exactly the information routes without treating nested/private routes as public', () => {
  for (const path of Object.values(PUBLIC_INFORMATION_PATH)) {
    expect(isPublicInformationPath(path)).toBe(true);
    expect(isPublicInformationPath(`${path}/private`)).toBe(false);
  }
  for (const path of [NAVIGATION_PATH.HOME, NAVIGATION_PATH.NEW_BOT, NAVIGATION_PATH.START, botPath('private'), runPath('private')]) expect(isPublicInformationPath(path)).toBe(false);
});

it('classifies encoded information paths once without admitting malformed or nested routes', () => {
  expect(isPublicInformationPath('/%77elcome')).toBe(true);
  expect(isPublicInformationPath('/h%65lp')).toBe(true);
  for (const path of ['/%2577elcome', '/welcome%2Fprivate', '/%zz', '/%']) expect(isPublicInformationPath(path)).toBe(false);
});
