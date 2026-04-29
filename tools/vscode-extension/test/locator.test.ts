import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { locateFinding } from "../src/locator";
import { Finding } from "../src/types";

const FIXTURE_DIR = join(__dirname, "fixtures");
const loadFixture = (name: string) =>
  readFileSync(join(FIXTURE_DIR, name), "utf8");

describe("locateFinding", () => {
  it("anchors a feed-keyed finding to the matching feedId value", () => {
    const text = loadFixture("one-feed.json");
    const finding: Finding = {
      rule_id: "E001",
      severity: "ERROR",
      message: "feedId 327 is duplicated",
      feed_id: 327,
      symbol: null,
    };
    const range = locateFinding(text, finding);
    // The feedId value "327" appears once in the fixture.
    const idx = text.indexOf("327");
    expect(range.startOffset).toBe(idx);
    expect(range.endOffset).toBe(idx + "327".length);
  });
});
