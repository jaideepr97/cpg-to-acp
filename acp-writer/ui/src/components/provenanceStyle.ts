import type { CSSProperties } from "react";

// Widen the horizontal DescriptionList term column (PatternFly default is 12ch)
// so long provenance labels like "Source recommendation" render on one line
// instead of wrapping. Shared by GoalCard and ActivityCard.
export const provenanceListStyle = {
  "--pf-v6-c-description-list--m-horizontal__term--width": "24ch",
  "--pf-v6-c-description-list__term--width": "24ch",
} as CSSProperties;
