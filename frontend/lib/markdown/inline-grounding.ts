import type { InlineGroundingCitation } from "@/lib/api";

function markerFor(citation: InlineGroundingCitation): string {
  const safeUrl = citation.url.replace(/[<>\r\n]/g, (character) => encodeURIComponent(character));
  const label = encodeURIComponent(citation.title);
  return ` [↗](<${safeUrl}> "sonia-grounding:${label}")`;
}

/**
 * Adds compact linked markers at provider-reported answer offsets. Positions are UTF-16
 * offsets to match JavaScript string slicing. Process from right to left so earlier offsets
 * remain stable; duplicate support rows for the same source/segment are ignored.
 */
export function applyInlineGroundingCitations(
  answer: string,
  citations: InlineGroundingCitation[],
): string {
  const byPosition = new Map<number, Map<string, InlineGroundingCitation>>();
  for (const citation of citations) {
    if (!Number.isInteger(citation.position) || citation.position < 0 || citation.position > answer.length) continue;
    if (!/^https?:\/\//i.test(citation.url)) continue;
    const atPosition = byPosition.get(citation.position) ?? new Map<string, InlineGroundingCitation>();
    atPosition.set(citation.url, citation);
    byPosition.set(citation.position, atPosition);
  }

  let result = answer;
  for (const [position, sources] of [...byPosition.entries()].sort(([left], [right]) => right - left)) {
    const markers = [...sources.values()].map(markerFor).join("");
    result = `${result.slice(0, position)}${markers}${result.slice(position)}`;
  }
  return result;
}
