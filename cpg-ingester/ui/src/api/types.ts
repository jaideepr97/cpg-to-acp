export type RunStatus =
  | 'parsing'
  | 'analyzing'
  | 'awaiting_manifest_review'
  | 'generating'
  | 'awaiting_artifact_review'
  | 'assembling'
  | 'delivering'
  | 'completed'
  | 'failed';

export interface RunSummary {
  id: string;
  status: RunStatus;
  cpgName: string;
  createdAt: string;
  currentStep: string;
}

export interface PipelineStep {
  name: string;
  status: 'pending' | 'active' | 'completed' | 'failed';
  startedAt?: string;
  completedAt?: string;
  iteration?: number;
}

export interface CPGMetadata {
  cpg_id: string;
  title: string;
  version?: string;
  issuing_body?: string;
  grading_system?: string;
  scope?: string;
}

export interface SectionMapEntry {
  heading: string;
  page_start?: number;
  page_end?: number;
  classification: string;
}

export interface DecisionVariable {
  name: string;
  type: string;
}

export interface DecisionResult {
  dmn_xml: string;
  item: {
    name: string;
    type: string;
    category?: string;
    section?: string;
    tier?: string;
  };
  decision_model_summary: {
    id: string;
    name: string;
    inputs: DecisionVariable[];
    outputs: DecisionVariable[];
    category?: string;
  };
}

export interface RecommendationResult {
  id: string;
  source_cpg: string;
  title: string;
  content: string;
  recommendation_type: string;
  section?: string;
  certainty?: {
    strength: string;
    evidence_quality?: string;
    grading_system?: string;
    original_grade?: string;
  };
  rationale?: string;
  scope_notes?: string;
  remarks?: string[];
  cross_references?: Array<{
    target_id: string;
    target_type: string;
    relationship: string;
  }>;
  source_location?: {
    page_start?: number;
    page_end?: number;
    source_text?: string;
  };
}

export interface AssemblyReport {
  cpg_id: string;
  recommendations_count: number;
  dmn_models_count: number;
  escalated_count: number;
  integrity_errors: string[];
}

export interface EscalatedItem {
  name: string;
  type: string;
  section?: string;
  reason?: string;
}

export interface PublishedArtifact {
  type: 'metadata' | 'dmn' | 'recommendations' | 'assembly_report' | 'escalated_items';
  ref: string;
  name?: string;
  cpg_id?: string;
  count?: number;
}

export interface DeliveryStatus {
  published: boolean;
  cpg_id: string;
  artifact_location?: string;
  artifacts: PublishedArtifact[];
  errors: string[];
  escalated_items_count?: number;
  reason?: string;
}

export interface ReviewFeedbackItem {
  itemId: string;
  itemType: 'decision' | 'recommendation' | 'classification';
  comment: string;
}

export interface ReviewAction {
  action: 'approve' | 'request_changes';
  feedback?: ReviewFeedbackItem[];
  overallComment?: string;
}

export interface StepError {
  step: string;
  message: string;
}

export interface RunDetail {
  id: string;
  status: RunStatus;
  cpgName: string;
  createdAt: string;
  steps: PipelineStep[];
  awaitingReview?: 'manifest' | 'pre-delivery';
  reviewIteration?: number;
  previousFeedback?: ReviewAction;
  metadata?: CPGMetadata;
  sectionMap?: SectionMapEntry[];
  decisions?: DecisionResult[];
  recommendations?: RecommendationResult[];
  assemblyReport?: AssemblyReport;
  deliveryStatus?: DeliveryStatus;
  escalatedItems?: EscalatedItem[];
  errors?: StepError[];
}
