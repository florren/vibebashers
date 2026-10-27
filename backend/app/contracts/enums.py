"""СГЕНЕРИРОВАНО scripts/gen_enums.py из contracts/events/common.schema.json — не редактировать руками."""
from __future__ import annotations

from enum import StrEnum


class Segment(StrEnum):
    MASS = "mass"
    SALARY = "salary"
    SOCIAL = "social"
    YOUTH = "youth"
    PREMIUM = "premium"
    VIP = "vip"
    ULTRA_VIP = "ultra_vip"


class Product(StrEnum):
    DEPOSIT = "deposit"
    DEBIT_CARD = "debit_card"
    CREDIT = "credit"
    CREDIT_CARD = "credit_card"


class System(StrEnum):
    MOBILE_APP = "mobile_app"
    WEB_BANK = "web_bank"
    CONTACT_CENTER = "contact_center"
    SOCIAL_LISTENING = "social_listening"
    PROCESSING = "processing"
    NOTIFICATION_GW = "notification_gw"
    PROMO_ENGINE = "promo_engine"
    ANTIFRAUD = "antifraud"
    SUB_DEPOSITS = "sub_deposits"
    SUB_LENDING = "sub_lending"
    SUB_DEBIT = "sub_debit"
    CORE_ABS = "core_abs"


class Team(StrEnum):
    TEAM_CX = "team_cx"
    TEAM_DEPOSITS = "team_deposits"
    TEAM_LENDING = "team_lending"
    TEAM_DEBIT = "team_debit"
    TEAM_FRONT = "team_front"
    TEAM_PROCESSING = "team_processing"
    TEAM_NOTIFICATIONS = "team_notifications"
    TEAM_CONTACT_CENTER = "team_contact_center"
    TEAM_PROMO = "team_promo"
    TEAM_ANTIFRAUD = "team_antifraud"
    TEAM_COMPLIANCE = "team_compliance"
    TEAM_BRANCH_NETWORK = "team_branch_network"


class Channel(StrEnum):
    SOCIAL = "social"
    CALL = "call"
    CHAT = "chat"
    EMAIL = "email"
    BRANCH = "branch"
    LANDING = "landing"
    TELEGRAM_BOT = "telegram_bot"
    PROACTIVE = "proactive"
    REVIEW_PORTAL = "review_portal"
    VOICE_INPUT = "voice_input"
    BRANCH_AUDIO = "branch_audio"
    CSI_SURVEY = "csi_survey"


class ProductLine(StrEnum):
    DEPOSITS = "deposits"
    MORTGAGE = "mortgage"
    LOANS = "loans"
    CREDIT_CARDS = "credit_cards"
    DEBIT_CARDS = "debit_cards"
    TRANSFERS_PAYMENTS = "transfers_payments"
    MOBILE_APP = "mobile_app"
    INVESTMENTS = "investments"
    INSURANCE = "insurance"
    BONUSES_SUBSCRIPTION = "bonuses_subscription"
    BRANCHES_SERVICE = "branches_service"
    SUPPORT = "support"
    BUSINESS_BANKING = "business_banking"
    ATM_SELF_SERVICE = "atm_self_service"
    FRAUD_SECURITY = "fraud_security"
    OTHER = "other"


class BranchType(StrEnum):
    FLAGSHIP = "flagship"
    STANDARD = "standard"
    ADDITIONAL = "additional"
    MOBILE = "mobile"


class BranchStatus(StrEnum):
    OPEN = "open"
    CLOSED = "closed"


class SignalType(StrEnum):
    TECH_FAULT = "tech_fault"
    CLIENT_ERROR = "client_error"
    TARIFF_TERMS = "tariff_terms"
    SERVICE_QUALITY = "service_quality"
    FRAUD_SUSPICION = "fraud_suspicion"
    LEGAL_REGULATORY = "legal_regulatory"
    INFO_REQUEST = "info_request"
    GRATITUDE = "gratitude"
    SUGGESTION = "suggestion"
    CHURN = "churn"


class Flag(StrEnum):
    CHURN_INTENT = "churn_intent"
    REPEAT = "repeat"
    SARCASM = "sarcasm"
    AGGRESSION = "aggression"
    MASS_IMPACT = "mass_impact"
    PUBLIC = "public"
    RULE_CONFIRMED = "rule_confirmed"
    REGULATOR_THREAT = "regulator_threat"
    PASSIVE_AGGRESSION = "passive_aggression"
    REPEAT_CONTACT_7D = "repeat_contact_7d"
    RED_WORD = "red_word"


class Complexity(StrEnum):
    INSTANT = "instant"
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class Criticality(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Psychotype(StrEnum):
    LOYAL_PRAGMATIC = "loyal_pragmatic"
    ANXIOUS = "anxious"
    DEMANDING_RATIONAL = "demanding_rational"
    PUBLIC_EMOTIONAL = "public_emotional"
    SILENT_CHURNER = "silent_churner"
    BONUS_HUNTER = "bonus_hunter"
    NOVICE = "novice"
    STATUS_ORIENTED = "status_oriented"


class ClientState(StrEnum):
    CALM = "calm"
    AFFECTED = "affected"
    COMPLAINING = "complaining"
    WAITING = "waiting"
    SATISFIED = "satisfied"
    ASKS_AGAIN = "asks_again"
    ESCALATES = "escalates"
    CHURN_INTENT = "churn_intent"
    RETAINED = "retained"
    CHURNED = "churned"


class IncidentStatus(StrEnum):
    NEW = "new"
    CLASSIFIED = "classified"
    ROUTED = "routed"
    IN_PROGRESS = "in_progress"
    FIX_PROPOSED = "fix_proposed"
    FIX_DEPLOYED = "fix_deployed"
    VERIFYING = "verifying"
    RESOLVED = "resolved"
    CLOSED = "closed"
    AWAITING_HUMAN = "awaiting_human"
    AWAITING_CLIENT = "awaiting_client"
    ESCALATED = "escalated"
    DUPLICATE = "duplicate"
    REJECTED = "rejected"


class Tone(StrEnum):
    NEUTRAL = "neutral"
    POSITIVE = "positive"
    IRRITATED = "irritated"
    ANGRY = "angry"
    SARCASTIC = "sarcastic"
    FORMAL = "formal"


class IncidentType(StrEnum):
    TECH_FAULT = "tech_fault"
    CLIENT_ERROR = "client_error"
    TARIFF_TERMS = "tariff_terms"
    SERVICE_QUALITY = "service_quality"
    FRAUD_SUSPICION = "fraud_suspicion"
    LEGAL_REGULATORY = "legal_regulatory"
    INFO_REQUEST = "info_request"
    SUGGESTION = "suggestion"
    ACCOUNT_CLOSURE = "account_closure"
    PROACTIVE = "proactive"
    FEE_REFUND = "fee_refund"
    MISSELLING = "misselling"


class SignalOrigin(StrEnum):
    SIM = "sim"
    SCENARIO = "scenario"
    JURY = "jury"
    LANDING = "landing"
    TELEGRAM_BOT = "telegram_bot"
    PROACTIVE = "proactive"
    TWIN = "twin"
    REVIEW_PORTAL = "review_portal"
    VOICE_INPUT = "voice_input"
    API = "api"
    TRANSCRIPT = "transcript"
    POLLING = "polling"


class SimRunKind(StrEnum):
    BASELINE = "baseline"
    FREE = "free"
    SCENARIO = "scenario"
    LIVE = "live"


class Intent(StrEnum):
    """Намерения автора текста (ТЗ 7, BRD FR 1.2)"""
    CHURN_THREAT = "churn_threat"
    REFUND_REQUEST = "refund_request"
    COMPLAINT = "complaint"
    QUESTION = "question"
    PUBLIC_SHAMING = "public_shaming"
    REGULATOR_THREAT = "regulator_threat"
    GRATITUDE = "gratitude"


class PaymentMethod(StrEnum):
    QR_SBP = "qr_sbp"
    CARD = "card"
    TRANSFER = "transfer"
    CASH = "cash"
    ONLINE = "online"


class LedgerKind(StrEnum):
    DEBIT = "debit"
    CREDIT = "credit"
    FEE = "fee"
    REFUND = "refund"
    REVERSAL = "reversal"


class RuleAction(StrEnum):
    REFUND_FEE = "refund_fee"
    PROPOSE_HITL = "propose_hitl"
    NOTIFY_ONLY = "notify_only"
    SUPPRESS_DUPLICATES = "suppress_duplicates"


class MissellingPattern(StrEnum):
    """Таксономия нарушений сотрудника: семейство misselling (tie_in, substitution, concealment, pressure, guarantee — ТЗ 22.4) и conduct (rudeness, script_violation, misinformation — ТЗ 22.8)"""
    TIE_IN = "tie_in"
    SUBSTITUTION = "substitution"
    CONCEALMENT = "concealment"
    PRESSURE = "pressure"
    GUARANTEE = "guarantee"
    RUDENESS = "rudeness"
    SCRIPT_VIOLATION = "script_violation"
    MISINFORMATION = "misinformation"


class Speaker(StrEnum):
    EMPLOYEE = "employee"
    CLIENT = "client"
    UNKNOWN = "unknown"


class DiarizationMode(StrEnum):
    STEREO = "stereo"
    MANUAL = "manual"
    AUTO = "auto"


class SttProvider(StrEnum):
    VOSK = "vosk"
    BROWSER = "browser"
    SALUTESPEECH = "salutespeech"
    OPENAI_COMPATIBLE_AUDIO = "openai_compatible_audio"
    NONE = "none"


class AudioSource(StrEnum):
    MIC = "mic"
    FILE = "file"
    TRANSCRIPT = "transcript"


class TriggerStatus(StrEnum):
    PRELIMINARY = "preliminary"
    CONFIRMED = "confirmed"
    DISMISSED = "dismissed"


class LlmSource(StrEnum):
    """Откуда взят ответ модели: живой вызов, кассета replay, rule-based mock (ТЗ 5.2, 5.4)"""
    LIVE = "live"
    REPLAY = "replay"
    MOCK = "mock"


class Platform(StrEnum):
    REVIEW_PORTAL = "review_portal"
    TELEGRAM_CHANNEL = "telegram_channel"


class Sentiment(StrEnum):
    """Трёхклассная тональность (ДТЗ FR-2.1); сверяется с порогами negativity ≤33 / 34–66 / ≥67"""
    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"


class Severity(StrEnum):
    """problem_summary.severity (ДТЗ FR-2.3); low/medium/high = criticality, critical = high + признак обязательного HITL"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RouterAction(StrEnum):
    """Решение агента-маршрутизатора в терминах ДТЗ FR-3.1"""
    ROUTE = "route"
    ESCALATE = "escalate"
    REQUEST_CLARIFICATION = "request_clarification"
    NONE = "none"


class RoutingStatus(StrEnum):
    PENDING = "pending"
    ROUTED = "routed"
    ESCALATED = "escalated"
    CLARIFICATION = "clarification"
    REJECTED = "rejected"


class EscalationRole(StrEnum):
    CX_LEAD = "cx_lead"
    BRANCH_MANAGER = "branch_manager"


class EscalationStatus(StrEnum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


class ViolationFamily(StrEnum):
    MISSELLING = "misselling"
    CONDUCT = "conduct"


class AlertPolicy(StrEnum):
    COUNTER = "counter"
    IMMEDIATE = "immediate"
    REPORT = "report"


class Pacing(StrEnum):
    REALTIME = "realtime"
    BATCH = "batch"


class TranscriptKind(StrEnum):
    BRANCH_RETAIL = "branch_retail"
    CONTACT_CENTER_CALL = "contact_center_call"
    CONTACT_CENTER_CHAT = "contact_center_chat"


class IngestSourceKind(StrEnum):
    REST = "rest"
    POLLING = "polling"
    FILE = "file"


class GeoSource(StrEnum):
    CLIENT_PROFILE = "client_profile"
    MESSAGE = "message"
    CONTACT = "contact"
    IP_MOCK = "ip_mock"
    NONE = "none"


class Zone(StrEnum):
    GREEN = "green"
    YELLOW = "yellow"
    RED = "red"


class TracePhase(StrEnum):
    BEFORE = "before"
    SUBJECT = "subject"
    AFTER = "after"


class TraceActor(StrEnum):
    CLIENT = "client"
    AGENT = "agent"
    HUMAN = "human"
    TEAM = "team"
    SYSTEM = "system"
    SIM = "sim"


class JourneyStage(StrEnum):
    INTAKE = "intake"
    UNDERSTANDING = "understanding"
    IDENTITY = "identity"
    RULES = "rules"
    DECISION = "decision"
    ACTION = "action"
    EXECUTION = "execution"
    CLIENT_OUTCOME = "client_outcome"


class JourneyMessageKind(StrEnum):
    ACK = "ack"
    PUBLIC_REPLY = "public_reply"
    STATUS = "status"
    FINAL = "final"
    GIFT = "gift"
    CLARIFICATION = "clarification"


class SearchMode(StrEnum):
    ID = "id"
    HINTS = "hints"
    TEXT = "text"


class TraceEventKind(StrEnum):
    SOURCE_MESSAGE = "source_message"
    OPERATION = "operation"
    FAULT = "fault"
    FEE = "fee"
    SIGNAL_CREATED = "signal_created"
    SIGNAL_NORMALIZED = "signal_normalized"
    CLIENT_IDENTIFIED = "client_identified"
    RULE_EVALUATION = "rule_evaluation"
    POLICY_CHECK = "policy_check"
    CLASSIFICATION = "classification"
    DECISION = "decision"
    TOOL_CALL = "tool_call"
    HUMAN_REQUEST = "human_request"
    HUMAN_DECISION = "human_decision"
    ESCALATION = "escalation"
    INCIDENT_CREATED = "incident_created"
    INCIDENT_LINKED = "incident_linked"
    INCIDENT_STATUS = "incident_status"
    TEAM_ACTION = "team_action"
    TASK = "task"
    NOTIFICATION = "notification"
    PUBLIC_REPLY = "public_reply"
    REFUND = "refund"
    FOLLOWUP = "followup"
    CLIENT_REACTION = "client_reaction"
    GIFT = "gift"
    ECONOMICS = "economics"
    TERMINAL = "terminal"
    CHURN = "churn"
    ZONE_CHANGED = "zone_changed"
    COMPLIANCE_ALERT = "compliance_alert"


ALL_ENUMS = {"segment": Segment, "product": Product, "system": System, "team": Team, "channel": Channel, "product_line": ProductLine, "branch_type": BranchType, "branch_status": BranchStatus, "signal_type": SignalType, "flag": Flag, "complexity": Complexity, "criticality": Criticality, "psychotype": Psychotype, "client_state": ClientState, "incident_status": IncidentStatus, "tone": Tone, "incident_type": IncidentType, "signal_origin": SignalOrigin, "sim_run_kind": SimRunKind, "intent": Intent, "payment_method": PaymentMethod, "ledger_kind": LedgerKind, "rule_action": RuleAction, "misselling_pattern": MissellingPattern, "speaker": Speaker, "diarization_mode": DiarizationMode, "stt_provider": SttProvider, "audio_source": AudioSource, "trigger_status": TriggerStatus, "llm_source": LlmSource, "platform": Platform, "sentiment": Sentiment, "severity": Severity, "router_action": RouterAction, "routing_status": RoutingStatus, "escalation_role": EscalationRole, "escalation_status": EscalationStatus, "violation_family": ViolationFamily, "alert_policy": AlertPolicy, "pacing": Pacing, "transcript_kind": TranscriptKind, "ingest_source_kind": IngestSourceKind, "geo_source": GeoSource, "zone": Zone, "trace_phase": TracePhase, "trace_actor": TraceActor, "journey_stage": JourneyStage, "journey_message_kind": JourneyMessageKind, "search_mode": SearchMode, "trace_event_kind": TraceEventKind}
