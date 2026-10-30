// СГЕНЕРИРОВАНО scripts/gen_enums.py из contracts/events/common.schema.json — не редактировать руками.

export const Segment = {
  MASS: "mass",
  SALARY: "salary",
  SOCIAL: "social",
  YOUTH: "youth",
  PREMIUM: "premium",
  VIP: "vip",
  ULTRA_VIP: "ultra_vip",
} as const;
export type Segment = (typeof Segment)[keyof typeof Segment];

export const Product = {
  DEPOSIT: "deposit",
  DEBIT_CARD: "debit_card",
  CREDIT: "credit",
  CREDIT_CARD: "credit_card",
} as const;
export type Product = (typeof Product)[keyof typeof Product];

export const System = {
  MOBILE_APP: "mobile_app",
  WEB_BANK: "web_bank",
  CONTACT_CENTER: "contact_center",
  SOCIAL_LISTENING: "social_listening",
  PROCESSING: "processing",
  NOTIFICATION_GW: "notification_gw",
  PROMO_ENGINE: "promo_engine",
  ANTIFRAUD: "antifraud",
  SUB_DEPOSITS: "sub_deposits",
  SUB_LENDING: "sub_lending",
  SUB_DEBIT: "sub_debit",
  CORE_ABS: "core_abs",
} as const;
export type System = (typeof System)[keyof typeof System];

export const Team = {
  TEAM_CX: "team_cx",
  TEAM_DEPOSITS: "team_deposits",
  TEAM_LENDING: "team_lending",
  TEAM_DEBIT: "team_debit",
  TEAM_FRONT: "team_front",
  TEAM_PROCESSING: "team_processing",
  TEAM_NOTIFICATIONS: "team_notifications",
  TEAM_CONTACT_CENTER: "team_contact_center",
  TEAM_PROMO: "team_promo",
  TEAM_ANTIFRAUD: "team_antifraud",
  TEAM_COMPLIANCE: "team_compliance",
  TEAM_BRANCH_NETWORK: "team_branch_network",
} as const;
export type Team = (typeof Team)[keyof typeof Team];

export const Channel = {
  SOCIAL: "social",
  CALL: "call",
  CHAT: "chat",
  EMAIL: "email",
  BRANCH: "branch",
  LANDING: "landing",
  TELEGRAM_BOT: "telegram_bot",
  PROACTIVE: "proactive",
  REVIEW_PORTAL: "review_portal",
  VOICE_INPUT: "voice_input",
  BRANCH_AUDIO: "branch_audio",
  CSI_SURVEY: "csi_survey",
} as const;
export type Channel = (typeof Channel)[keyof typeof Channel];

export const ProductLine = {
  DEPOSITS: "deposits",
  MORTGAGE: "mortgage",
  LOANS: "loans",
  CREDIT_CARDS: "credit_cards",
  DEBIT_CARDS: "debit_cards",
  TRANSFERS_PAYMENTS: "transfers_payments",
  MOBILE_APP: "mobile_app",
  INVESTMENTS: "investments",
  INSURANCE: "insurance",
  BONUSES_SUBSCRIPTION: "bonuses_subscription",
  BRANCHES_SERVICE: "branches_service",
  SUPPORT: "support",
  BUSINESS_BANKING: "business_banking",
  ATM_SELF_SERVICE: "atm_self_service",
  FRAUD_SECURITY: "fraud_security",
  OTHER: "other",
} as const;
export type ProductLine = (typeof ProductLine)[keyof typeof ProductLine];

export const BranchType = {
  FLAGSHIP: "flagship",
  STANDARD: "standard",
  ADDITIONAL: "additional",
  MOBILE: "mobile",
} as const;
export type BranchType = (typeof BranchType)[keyof typeof BranchType];

export const BranchStatus = {
  OPEN: "open",
  CLOSED: "closed",
} as const;
export type BranchStatus = (typeof BranchStatus)[keyof typeof BranchStatus];

export const SignalType = {
  TECH_FAULT: "tech_fault",
  CLIENT_ERROR: "client_error",
  TARIFF_TERMS: "tariff_terms",
  SERVICE_QUALITY: "service_quality",
  FRAUD_SUSPICION: "fraud_suspicion",
  LEGAL_REGULATORY: "legal_regulatory",
  INFO_REQUEST: "info_request",
  GRATITUDE: "gratitude",
  SUGGESTION: "suggestion",
  CHURN: "churn",
} as const;
export type SignalType = (typeof SignalType)[keyof typeof SignalType];

export const Flag = {
  CHURN_INTENT: "churn_intent",
  REPEAT: "repeat",
  SARCASM: "sarcasm",
  AGGRESSION: "aggression",
  MASS_IMPACT: "mass_impact",
  PUBLIC: "public",
  RULE_CONFIRMED: "rule_confirmed",
  REGULATOR_THREAT: "regulator_threat",
  PASSIVE_AGGRESSION: "passive_aggression",
  REPEAT_CONTACT_7D: "repeat_contact_7d",
  RED_WORD: "red_word",
} as const;
export type Flag = (typeof Flag)[keyof typeof Flag];

export const Complexity = {
  INSTANT: "instant",
  EASY: "easy",
  MEDIUM: "medium",
  HARD: "hard",
} as const;
export type Complexity = (typeof Complexity)[keyof typeof Complexity];

export const Criticality = {
  LOW: "low",
  MEDIUM: "medium",
  HIGH: "high",
} as const;
export type Criticality = (typeof Criticality)[keyof typeof Criticality];

export const Psychotype = {
  LOYAL_PRAGMATIC: "loyal_pragmatic",
  ANXIOUS: "anxious",
  DEMANDING_RATIONAL: "demanding_rational",
  PUBLIC_EMOTIONAL: "public_emotional",
  SILENT_CHURNER: "silent_churner",
  BONUS_HUNTER: "bonus_hunter",
  NOVICE: "novice",
  STATUS_ORIENTED: "status_oriented",
} as const;
export type Psychotype = (typeof Psychotype)[keyof typeof Psychotype];

export const ClientState = {
  CALM: "calm",
  AFFECTED: "affected",
  COMPLAINING: "complaining",
  WAITING: "waiting",
  SATISFIED: "satisfied",
  ASKS_AGAIN: "asks_again",
  ESCALATES: "escalates",
  CHURN_INTENT: "churn_intent",
  RETAINED: "retained",
  CHURNED: "churned",
} as const;
export type ClientState = (typeof ClientState)[keyof typeof ClientState];

export const IncidentStatus = {
  NEW: "new",
  CLASSIFIED: "classified",
  ROUTED: "routed",
  IN_PROGRESS: "in_progress",
  FIX_PROPOSED: "fix_proposed",
  FIX_DEPLOYED: "fix_deployed",
  VERIFYING: "verifying",
  RESOLVED: "resolved",
  CLOSED: "closed",
  AWAITING_HUMAN: "awaiting_human",
  AWAITING_CLIENT: "awaiting_client",
  ESCALATED: "escalated",
  DUPLICATE: "duplicate",
  REJECTED: "rejected",
} as const;
export type IncidentStatus = (typeof IncidentStatus)[keyof typeof IncidentStatus];

export const Tone = {
  NEUTRAL: "neutral",
  POSITIVE: "positive",
  IRRITATED: "irritated",
  ANGRY: "angry",
  SARCASTIC: "sarcastic",
  FORMAL: "formal",
} as const;
export type Tone = (typeof Tone)[keyof typeof Tone];

export const IncidentType = {
  TECH_FAULT: "tech_fault",
  CLIENT_ERROR: "client_error",
  TARIFF_TERMS: "tariff_terms",
  SERVICE_QUALITY: "service_quality",
  FRAUD_SUSPICION: "fraud_suspicion",
  LEGAL_REGULATORY: "legal_regulatory",
  INFO_REQUEST: "info_request",
  SUGGESTION: "suggestion",
  ACCOUNT_CLOSURE: "account_closure",
  PROACTIVE: "proactive",
  FEE_REFUND: "fee_refund",
  MISSELLING: "misselling",
} as const;
export type IncidentType = (typeof IncidentType)[keyof typeof IncidentType];

export const SignalOrigin = {
  SIM: "sim",
  SCENARIO: "scenario",
  JURY: "jury",
  LANDING: "landing",
  TELEGRAM_BOT: "telegram_bot",
  PROACTIVE: "proactive",
  TWIN: "twin",
  REVIEW_PORTAL: "review_portal",
  VOICE_INPUT: "voice_input",
  API: "api",
  TRANSCRIPT: "transcript",
  POLLING: "polling",
} as const;
export type SignalOrigin = (typeof SignalOrigin)[keyof typeof SignalOrigin];

export const SimRunKind = {
  BASELINE: "baseline",
  FREE: "free",
  SCENARIO: "scenario",
  LIVE: "live",
} as const;
export type SimRunKind = (typeof SimRunKind)[keyof typeof SimRunKind];

export const Intent = {
  CHURN_THREAT: "churn_threat",
  REFUND_REQUEST: "refund_request",
  COMPLAINT: "complaint",
  QUESTION: "question",
  PUBLIC_SHAMING: "public_shaming",
  REGULATOR_THREAT: "regulator_threat",
  GRATITUDE: "gratitude",
} as const;
export type Intent = (typeof Intent)[keyof typeof Intent];

export const PaymentMethod = {
  QR_SBP: "qr_sbp",
  CARD: "card",
  TRANSFER: "transfer",
  CASH: "cash",
  ONLINE: "online",
} as const;
export type PaymentMethod = (typeof PaymentMethod)[keyof typeof PaymentMethod];

export const LedgerKind = {
  DEBIT: "debit",
  CREDIT: "credit",
  FEE: "fee",
  REFUND: "refund",
  REVERSAL: "reversal",
} as const;
export type LedgerKind = (typeof LedgerKind)[keyof typeof LedgerKind];

export const RuleAction = {
  REFUND_FEE: "refund_fee",
  PROPOSE_HITL: "propose_hitl",
  NOTIFY_ONLY: "notify_only",
  SUPPRESS_DUPLICATES: "suppress_duplicates",
} as const;
export type RuleAction = (typeof RuleAction)[keyof typeof RuleAction];

export const MissellingPattern = {
  TIE_IN: "tie_in",
  SUBSTITUTION: "substitution",
  CONCEALMENT: "concealment",
  PRESSURE: "pressure",
  GUARANTEE: "guarantee",
  RUDENESS: "rudeness",
  SCRIPT_VIOLATION: "script_violation",
  MISINFORMATION: "misinformation",
} as const;
export type MissellingPattern = (typeof MissellingPattern)[keyof typeof MissellingPattern];

export const Speaker = {
  EMPLOYEE: "employee",
  CLIENT: "client",
  UNKNOWN: "unknown",
} as const;
export type Speaker = (typeof Speaker)[keyof typeof Speaker];

export const DiarizationMode = {
  STEREO: "stereo",
  MANUAL: "manual",
  AUTO: "auto",
} as const;
export type DiarizationMode = (typeof DiarizationMode)[keyof typeof DiarizationMode];

export const SttProvider = {
  VOSK: "vosk",
  BROWSER: "browser",
  SALUTESPEECH: "salutespeech",
  OPENAI_COMPATIBLE_AUDIO: "openai_compatible_audio",
  NONE: "none",
} as const;
export type SttProvider = (typeof SttProvider)[keyof typeof SttProvider];

export const AudioSource = {
  MIC: "mic",
  FILE: "file",
  TRANSCRIPT: "transcript",
} as const;
export type AudioSource = (typeof AudioSource)[keyof typeof AudioSource];

export const TriggerStatus = {
  PRELIMINARY: "preliminary",
  CONFIRMED: "confirmed",
  DISMISSED: "dismissed",
} as const;
export type TriggerStatus = (typeof TriggerStatus)[keyof typeof TriggerStatus];

export const LlmSource = {
  LIVE: "live",
  REPLAY: "replay",
  MOCK: "mock",
} as const;
export type LlmSource = (typeof LlmSource)[keyof typeof LlmSource];

export const Platform = {
  REVIEW_PORTAL: "review_portal",
  TELEGRAM_CHANNEL: "telegram_channel",
} as const;
export type Platform = (typeof Platform)[keyof typeof Platform];

export const Sentiment = {
  POSITIVE: "positive",
  NEUTRAL: "neutral",
  NEGATIVE: "negative",
} as const;
export type Sentiment = (typeof Sentiment)[keyof typeof Sentiment];

export const Severity = {
  LOW: "low",
  MEDIUM: "medium",
  HIGH: "high",
  CRITICAL: "critical",
} as const;
export type Severity = (typeof Severity)[keyof typeof Severity];

export const RouterAction = {
  ROUTE: "route",
  ESCALATE: "escalate",
  REQUEST_CLARIFICATION: "request_clarification",
  NONE: "none",
} as const;
export type RouterAction = (typeof RouterAction)[keyof typeof RouterAction];

export const RoutingStatus = {
  PENDING: "pending",
  ROUTED: "routed",
  ESCALATED: "escalated",
  CLARIFICATION: "clarification",
  REJECTED: "rejected",
} as const;
export type RoutingStatus = (typeof RoutingStatus)[keyof typeof RoutingStatus];

export const EscalationRole = {
  CX_LEAD: "cx_lead",
  BRANCH_MANAGER: "branch_manager",
} as const;
export type EscalationRole = (typeof EscalationRole)[keyof typeof EscalationRole];

export const EscalationStatus = {
  OPEN: "open",
  ACKNOWLEDGED: "acknowledged",
  RESOLVED: "resolved",
  DISMISSED: "dismissed",
} as const;
export type EscalationStatus = (typeof EscalationStatus)[keyof typeof EscalationStatus];

export const ViolationFamily = {
  MISSELLING: "misselling",
  CONDUCT: "conduct",
} as const;
export type ViolationFamily = (typeof ViolationFamily)[keyof typeof ViolationFamily];

export const AlertPolicy = {
  COUNTER: "counter",
  IMMEDIATE: "immediate",
  REPORT: "report",
} as const;
export type AlertPolicy = (typeof AlertPolicy)[keyof typeof AlertPolicy];

export const Pacing = {
  REALTIME: "realtime",
  BATCH: "batch",
} as const;
export type Pacing = (typeof Pacing)[keyof typeof Pacing];

export const TranscriptKind = {
  BRANCH_RETAIL: "branch_retail",
  CONTACT_CENTER_CALL: "contact_center_call",
  CONTACT_CENTER_CHAT: "contact_center_chat",
} as const;
export type TranscriptKind = (typeof TranscriptKind)[keyof typeof TranscriptKind];

export const IngestSourceKind = {
  REST: "rest",
  POLLING: "polling",
  FILE: "file",
} as const;
export type IngestSourceKind = (typeof IngestSourceKind)[keyof typeof IngestSourceKind];

export const GeoSource = {
  CLIENT_PROFILE: "client_profile",
  MESSAGE: "message",
  CONTACT: "contact",
  IP_MOCK: "ip_mock",
  NONE: "none",
} as const;
export type GeoSource = (typeof GeoSource)[keyof typeof GeoSource];

export const Zone = {
  GREEN: "green",
  YELLOW: "yellow",
  RED: "red",
} as const;
export type Zone = (typeof Zone)[keyof typeof Zone];

export const TracePhase = {
  BEFORE: "before",
  SUBJECT: "subject",
  AFTER: "after",
} as const;
export type TracePhase = (typeof TracePhase)[keyof typeof TracePhase];

export const TraceActor = {
  CLIENT: "client",
  AGENT: "agent",
  HUMAN: "human",
  TEAM: "team",
  SYSTEM: "system",
  SIM: "sim",
} as const;
export type TraceActor = (typeof TraceActor)[keyof typeof TraceActor];

export const JourneyStage = {
  INTAKE: "intake",
  UNDERSTANDING: "understanding",
  IDENTITY: "identity",
  RULES: "rules",
  DECISION: "decision",
  ACTION: "action",
  EXECUTION: "execution",
  CLIENT_OUTCOME: "client_outcome",
} as const;
export type JourneyStage = (typeof JourneyStage)[keyof typeof JourneyStage];

export const JourneyMessageKind = {
  ACK: "ack",
  PUBLIC_REPLY: "public_reply",
  STATUS: "status",
  FINAL: "final",
  GIFT: "gift",
  CLARIFICATION: "clarification",
} as const;
export type JourneyMessageKind = (typeof JourneyMessageKind)[keyof typeof JourneyMessageKind];

export const SearchMode = {
  ID: "id",
  HINTS: "hints",
  TEXT: "text",
} as const;
export type SearchMode = (typeof SearchMode)[keyof typeof SearchMode];

export const TraceEventKind = {
  SOURCE_MESSAGE: "source_message",
  OPERATION: "operation",
  FAULT: "fault",
  FEE: "fee",
  SIGNAL_CREATED: "signal_created",
  SIGNAL_NORMALIZED: "signal_normalized",
  CLIENT_IDENTIFIED: "client_identified",
  RULE_EVALUATION: "rule_evaluation",
  POLICY_CHECK: "policy_check",
  CLASSIFICATION: "classification",
  DECISION: "decision",
  TOOL_CALL: "tool_call",
  HUMAN_REQUEST: "human_request",
  HUMAN_DECISION: "human_decision",
  ESCALATION: "escalation",
  INCIDENT_CREATED: "incident_created",
  INCIDENT_LINKED: "incident_linked",
  INCIDENT_STATUS: "incident_status",
  TEAM_ACTION: "team_action",
  TASK: "task",
  NOTIFICATION: "notification",
  PUBLIC_REPLY: "public_reply",
  REFUND: "refund",
  FOLLOWUP: "followup",
  CLIENT_REACTION: "client_reaction",
  GIFT: "gift",
  ECONOMICS: "economics",
  TERMINAL: "terminal",
  CHURN: "churn",
  ZONE_CHANGED: "zone_changed",
  COMPLIANCE_ALERT: "compliance_alert",
} as const;
export type TraceEventKind = (typeof TraceEventKind)[keyof typeof TraceEventKind];

export const SignalStatus = {
  NEW: "new",
  PROCESSING: "processing",
  CLASSIFIED: "classified",
  LINKED: "linked",
  DEFERRED: "deferred",
  AWAITING_HUMAN: "awaiting_human",
  AWAITING_CLIENT: "awaiting_client",
  ANSWERED: "answered",
  CLOSED: "closed",
  NOISE: "noise",
  ERROR: "error",
} as const;
export type SignalStatus = (typeof SignalStatus)[keyof typeof SignalStatus];
