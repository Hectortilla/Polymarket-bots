import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { spawnSync } from 'node:child_process';

function snapshot(directory) {
  const result = {};
  for (const entry of readdirSync(directory, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name))) {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) Object.assign(result, snapshot(path));
    else result[path] = readFileSync(path, 'utf8');
  }
  return JSON.stringify(result);
}

const before = snapshot('src/lib/api/generated');
const generated = spawnSync('npm', ['run', 'generate'], { stdio: 'inherit' });
if (generated.status !== 0) process.exit(generated.status ?? 1);
if (before !== snapshot('src/lib/api/generated')) {
  console.error('Generated client was stale. Review and retain the regenerated files.');
  process.exit(1);
}
console.log('Generated client matches the exported OpenAPI schema.');
