import { findNodeAtLocation, Node, parseTree } from "jsonc-parser";
import { Finding, OffsetRange } from "./types";

const FALLBACK: OffsetRange = { startOffset: 0, endOffset: 1 };

export function locateFinding(text: string, finding: Finding): OffsetRange {
  const tree = parseTree(text);
  if (!tree) return FALLBACK;

  // E017: feed_id slot holds the duplicated publisherId.
  if (finding.rule_id === "E017" && finding.feed_id != null) {
    const node = findInArrayByProperty(
      tree,
      "publishers",
      "publisherId",
      finding.feed_id,
    );
    if (node) return toRange(node);
    return FALLBACK;
  }

  // Default: match feeds[*].feedId == finding.feed_id
  if (finding.feed_id != null) {
    const node = findInArrayByProperty(
      tree,
      "feeds",
      "feedId",
      finding.feed_id,
    );
    if (node) return toRange(node);
  }
  return FALLBACK;
}

function findInArrayByProperty(
  tree: Node,
  arrayPath: string,
  propertyName: string,
  propertyValue: number | string,
): Node | null {
  const arrayNode = findNodeAtLocation(tree, [arrayPath]);
  if (!arrayNode || arrayNode.type !== "array" || !arrayNode.children) {
    return null;
  }
  for (let i = 0; i < arrayNode.children.length; i++) {
    const propNode = findNodeAtLocation(arrayNode, [i, propertyName]);
    if (propNode && propNode.value === propertyValue) {
      return propNode;
    }
  }
  return null;
}

function toRange(node: Node): OffsetRange {
  return { startOffset: node.offset, endOffset: node.offset + node.length };
}
