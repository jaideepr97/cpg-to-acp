// TypeScript mirrors of shared/src/cpg_contracts/ Python models.
// Keep in sync with the Pydantic sources.

// --- guidelines.ts ---

export enum GradingSystem {
  GRADE = "GRADE",
  COR_LOE = "COR-LOE",
  GRADE_COR_HYBRID = "GRADE-COR-hybrid",
  SIMPLIFIED = "simplified",
  VERB_IMPLIED = "verb-implied",
  UNGRADED = "ungraded",
}

export interface CPGMetadata {
  contract_version: string;
  cpg_id: string;
  title: string;
  version?: string;
  publication_date?: string;
  evidence_review_date?: string;
  issuing_body?: string;
  grading_system?: GradingSystem;
  scope?: string;
  supersedes?: string[];
}

// --- recommendations.ts ---

export enum RecommendationStrength {
  STRONG_FOR = "strong-for",
  CONDITIONAL_FOR = "conditional-for",
  CONSENSUS = "consensus",
  NO_RECOMMENDATION = "no-recommendation",
  CONDITIONAL_AGAINST = "conditional-against",
  STRONG_AGAINST = "strong-against",
}

export enum EvidenceQuality {
  HIGH = "high",
  MODERATE = "moderate",
  LOW = "low",
  VERY_LOW = "very-low",
  UNGRADED = "ungraded",
}

export enum RecommendationType {
  TREATMENT = "treatment",
  DIAGNOSTIC = "diagnostic",
  MONITORING = "monitoring",
  LIFESTYLE = "lifestyle",
  EDUCATIONAL = "educational",
  REFERRAL = "referral",
  SCREENING = "screening",
  CONTRAINDICATION = "contraindication",
  PROCESS = "process",
}

export enum RecommendationProvenance {
  REVIEWED = "reviewed",
  NEW_ADDED = "new-added",
  AMENDED = "amended",
  NOT_CHANGED = "not-changed",
  REMOVED = "removed",
}

export enum CrossReferenceRelationship {
  PREREQUISITE = "prerequisite",
  ALTERNATIVE = "alternative",
  CONFLICTS_WITH = "conflicts-with",
  MODIFIES = "modifies",
  RELATED = "related",
  SUPERSEDES = "supersedes",
  OTHER = "other",
}

export interface SourceLocation {
  page_start: number;
  page_end?: number;
  bbox?: number[];
  source_text?: string;
}

export interface CertaintyGrade {
  strength: RecommendationStrength;
  evidence_quality: EvidenceQuality;
  grading_system?: GradingSystem;
  original_grade?: string;
}

export interface CrossReference {
  target_id: string;
  relationship: CrossReferenceRelationship;
  description?: string;
}

export interface Recommendation {
  id: string;
  source_cpg: string;
  section?: string;
  title: string;
  content: string;
  recommendation_type: RecommendationType;
  certainty?: CertaintyGrade;
  scope_notes?: string;
  remarks?: string[];
  rationale?: string;
  cross_references?: CrossReference[];
  provenance?: RecommendationProvenance;
  evidence_review_date?: string;
  source_location?: SourceLocation;
}

export interface RecommendationSummary {
  id: string;
  title: string;
  source_cpg: string;
  recommendation_type: RecommendationType;
  certainty?: CertaintyGrade;
}

export interface RecommendationBundle {
  contract_version: string;
  source_cpg: string;
  recommendations: Recommendation[];
}

// --- decisions.ts ---

export enum DecisionCategory {
  TREATMENT = "treatment",
  SCREENING = "screening",
  MONITORING = "monitoring",
  RISK_ASSESSMENT = "risk-assessment",
  DIAGNOSTIC = "diagnostic",
}

export interface DecisionVariable {
  name: string;
  type: string;
  description?: string;
  codes?: string[];
}

export interface DecisionModelSummary {
  id: string;
  name: string;
  inputs: DecisionVariable[];
  outputs: DecisionVariable[];
  deployed_at?: string;
  source_cpg?: string;
  category?: DecisionCategory;
  modifies?: string[];
  source_location?: SourceLocation;
}

export interface DecisionEvaluationRequest {
  model_id: string;
  inputs: Record<string, unknown>;
}

export interface DecisionEvaluationResponse {
  model_id: string;
  outputs: Record<string, unknown>;
}
