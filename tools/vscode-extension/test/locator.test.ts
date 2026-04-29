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

  it("anchors E017 finding to the matching publishers[*].publisherId value", () => {
    const text = loadFixture("one-publisher.json");
    const finding: Finding = {
      rule_id: "E017",
      severity: "ERROR",
      message: "publisherId 55 is duplicated",
      feed_id: 55, // E017 convention: feed_id slot holds the publisherId
      symbol: null,
    };
    const range = locateFinding(text, finding);
    const idx = text.indexOf("55");
    expect(range.startOffset).toBe(idx);
    expect(range.endOffset).toBe(idx + "55".length);
  });

  it("anchors E018 finding to the matching publishers[*].name value", () => {
    const text = loadFixture("one-publisher.json");
    const finding: Finding = {
      rule_id: "E018",
      severity: "ERROR",
      message: "publisher name 'AcmeMM' is duplicated",
      feed_id: null,
      symbol: "AcmeMM", // E018 convention: symbol slot holds the duplicated name
    };
    const range = locateFinding(text, finding);
    // The string "AcmeMM" appears once in the fixture (as the publisher's name value).
    const idx = text.indexOf('"AcmeMM"');
    expect(range.startOffset).toBe(idx);
    expect(range.endOffset).toBe(idx + '"AcmeMM"'.length);
  });
});
