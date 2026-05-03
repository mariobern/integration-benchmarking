import { existsSync } from "node:fs";
import { dirname, join, parse, sep } from "node:path";

const LINTER_REL = join("tools", "config-linter", "config_linter.py");

const cache = new Map<string, string | null>();

/**
 * Walk up from `startDir` looking for a sibling `tools/config-linter/config_linter.py`.
 * Stops at `workspaceRoot` (inclusive) or the filesystem root, whichever comes first.
 *
 * Returns the absolute linter path or null if not found. Cached per workspaceRoot.
 */
export function resolveLinterPath(
  startDir: string,
  workspaceRoot: string,
): string | null {
  const cached = cache.get(workspaceRoot);
  if (cached !== undefined) return cached;

  const fsRoot = parse(startDir).root;
  let current = startDir;
  // Walk up from startDir up to workspaceRoot inclusive.
  while (true) {
    const candidate = join(current, LINTER_REL);
    if (existsSync(candidate)) {
      cache.set(workspaceRoot, candidate);
      return candidate;
    }
    if (current === workspaceRoot || current === fsRoot) break;
    const parent = dirname(current);
    if (parent === current) break; // safety
    current = parent;
  }

  cache.set(workspaceRoot, null);
  return null;
}

/** For tests: clear the cache. */
export function clearResolverCache(): void {
  cache.clear();
}
