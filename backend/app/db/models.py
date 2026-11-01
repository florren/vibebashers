"""СГЕНЕРИРОВАНО scripts/gen_models.py (sqlacodegen) из contracts/db/schema.sql — не редактировать руками.

Источник истины — schema.sql; при изменении контракта: make sync-contracts (с DATABASE_URL) → этот файл обновится.
Индексы и представления намеренно не включены (их сравнение отключено в alembic/env.py)."""
from typing import Optional
import datetime
import decimal
import uuid

from sqlalchemy import BigInteger, Boolean, CHAR, CheckConstraint, Column, Computed, Date, DateTime, ForeignKeyConstraint, Identity, Integer, LargeBinary, Numeric, PrimaryKeyConstraint, SmallInteger, Table, Text, UniqueConstraint, Uuid, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

class Base(DeclarativeBase):
    pass


class AgentRuns(Base):
    __tablename__ = 'agent_runs'
    __table_args__ = (
        CheckConstraint("kind = ANY (ARRAY['agent'::text, 'client_twin'::text, 'team_emulator'::text, 'bench'::text, 'compare'::text, 'compliance_detector'::text, 'speaker_attribution'::text, 'operator_review'::text])", name='agent_runs_kind_check'),
        CheckConstraint("outcome = ANY (ARRAY['completed'::text, 'awaiting_human'::text, 'deferred'::text, 'failed'::text, 'fallback_mock'::text, 'cancelled'::text])", name='agent_runs_outcome_check'),
        ForeignKeyConstraint(['client_id'], ['clients.id'], name='agent_runs_client_id_fkey'),
        ForeignKeyConstraint(['incident_id'], ['incidents.id'], name='agent_runs_incident_id_fkey'),
        ForeignKeyConstraint(['llm_profile_id'], ['llm_profiles.id'], name='agent_runs_llm_profile_id_fkey'),
        ForeignKeyConstraint(['signal_id'], ['signals.id'], name='agent_runs_signal_id_fkey'),
        ForeignKeyConstraint(['sim_run_id'], ['sim_runs.id'], ondelete='CASCADE', name='agent_runs_sim_run_id_fkey'),
        PrimaryKeyConstraint('id', name='agent_runs_pkey')
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True, start=1, increment=1, minvalue=1, maxvalue=9223372036854775807, cycle=False, cache=1), primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'agent'::text"))
    prompt_version: Mapped[str] = mapped_column(Text, nullable=False)
    graph_version: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'1'::text"))
    started_at: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False, server_default=text('now()'))
    needed_human: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text('false'))
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text('0'))
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text('0'))
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text('0'))
    total_latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text('0'))
    cost_estimate: Mapped[decimal.Decimal] = mapped_column(Numeric(10, 6), nullable=False, server_default=text('0'))
    sim_run_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    signal_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    incident_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    client_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    llm_profile_id: Mapped[Optional[int]] = mapped_column(Integer)
    thread_id: Mapped[Optional[str]] = mapped_column(Text)
    finished_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(True))
    started_sim: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(True))
    outcome: Mapped[Optional[str]] = mapped_column(Text)
    error: Mapped[Optional[str]] = mapped_column(Text)
    public_id: Mapped[Optional[str]] = mapped_column(Text, Computed("('AR-'::text || lpad((id)::text, 6, '0'::text))", persisted=True))

    client: Mapped[Optional['Clients']] = relationship('Clients', back_populates='agent_runs')
    incident: Mapped[Optional['Incidents']] = relationship('Incidents', foreign_keys=[incident_id], back_populates='agent_runs_incident')
    llm_profile: Mapped[Optional['LlmProfiles']] = relationship('LlmProfiles', back_populates='agent_runs')
    signal: Mapped[Optional['Signals']] = relationship('Signals', back_populates='agent_runs')
    sim_run: Mapped[Optional['SimRuns']] = relationship('SimRuns', back_populates='agent_runs')
    incidents_agent_run: Mapped[list['Incidents']] = relationship('Incidents', foreign_keys='[Incidents.agent_run_id]', back_populates='agent_run')
    agent_steps: Mapped[list['AgentSteps']] = relationship('AgentSteps', back_populates='run')
    compliance_triggers: Mapped[list['ComplianceTriggers']] = relationship('ComplianceTriggers', back_populates='agent_run')
    external_replies: Mapped[list['ExternalReplies']] = relationship('ExternalReplies', back_populates='agent_run')
    followups: Mapped[list['Followups']] = relationship('Followups', back_populates='agent_run')
    rule_evaluations: Mapped[list['RuleEvaluations']] = relationship('RuleEvaluations', back_populates='agent_run')
    client_reactions: Mapped[list['ClientReactions']] = relationship('ClientReactions', back_populates='agent_run')
    human_decisions: Mapped[list['HumanDecisions']] = relationship('HumanDecisions', back_populates='agent_run')
    escalations: Mapped[list['Escalations']] = relationship('Escalations', back_populates='agent_run')
    ledger_entries: Mapped[list['LedgerEntries']] = relationship('LedgerEntries', back_populates='agent_run')
    hitl_feedback_processing: Mapped[list['HitlFeedbackProcessing']] = relationship('HitlFeedbackProcessing', back_populates='agent_run')


class AudioSessions(Base):
    __tablename__ = 'audio_sessions'
    __table_args__ = (
        CheckConstraint("diarization_mode = ANY (ARRAY['stereo'::text, 'manual'::text, 'auto'::text])", name='audio_sessions_diarization_mode_check'),
        CheckConstraint("pacing = ANY (ARRAY['realtime'::text, 'batch'::text])", name='audio_sessions_pacing_check'),
        CheckConstraint("source = ANY (ARRAY['mic'::text, 'file'::text, 'transcript'::text])", name='audio_sessions_source_check'),
        CheckConstraint("status = ANY (ARRAY['live'::text, 'alerted'::text, 'closed'::text])", name='audio_sessions_status_check'),
        ForeignKeyConstraint(['branch_id'], ['branches.id'], name='audio_sessions_branch_id_fkey'),
        ForeignKeyConstraint(['client_id'], ['clients.id'], name='audio_sessions_client_id_fkey'),
        ForeignKeyConstraint(['demo_asset_id'], ['demo_assets.id'], name='audio_sessions_demo_asset_fk'),
        ForeignKeyConstraint(['employee_id'], ['employees.id'], name='audio_sessions_employee_id_fkey'),
        ForeignKeyConstraint(['incident_id'], ['incidents.id'], name='audio_sessions_incident_id_fkey'),
        ForeignKeyConstraint(['run_id'], ['sim_runs.id'], ondelete='CASCADE', name='audio_sessions_run_id_fkey'),
        ForeignKeyConstraint(['transcript_id'], ['transcripts.id'], name='audio_sessions_transcript_fk'),
        PrimaryKeyConstraint('id', name='audio_sessions_pkey')
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True, start=1, increment=1, minvalue=1, maxvalue=9223372036854775807, cycle=False, cache=1), primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    branch_id: Mapped[int] = mapped_column(Integer, nullable=False)
    employee_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    stt_provider: Mapped[str] = mapped_column(Text, nullable=False)
    diarization_mode: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'live'::text"))
    trigger_count: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text('0'))
    alert_threshold: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text('3'))
    started_at: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False, server_default=text('now()'))
    started_sim: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False)
    store_audio: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text('false'))
    pacing: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'realtime'::text"))
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False, server_default=text('now()'))
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False, server_default=text('now()'))
    public_id: Mapped[Optional[str]] = mapped_column(Text, Computed("('AS-'::text || lpad((id)::text, 6, '0'::text))", persisted=True))
    client_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    deal_product: Mapped[Optional[str]] = mapped_column(Text)
    stt_model: Mapped[Optional[str]] = mapped_column(Text)
    incident_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    demo_asset_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    finished_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(True))
    transcript_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    report: Mapped[Optional[dict]] = mapped_column(JSONB)

    branch: Mapped['Branches'] = relationship('Branches', back_populates='audio_sessions')
    client: Mapped[Optional['Clients']] = relationship('Clients', back_populates='audio_sessions')
    demo_asset: Mapped[Optional['DemoAssets']] = relationship('DemoAssets', back_populates='audio_sessions')
    employee: Mapped['Employees'] = relationship('Employees', back_populates='audio_sessions')
    incident: Mapped[Optional['Incidents']] = relationship('Incidents', back_populates='audio_sessions')
    run: Mapped['SimRuns'] = relationship('SimRuns', back_populates='audio_sessions')
    transcript: Mapped[Optional['Transcripts']] = relationship('Transcripts', foreign_keys=[transcript_id], back_populates='audio_sessions_transcript')
    transcripts_audio_session: Mapped[list['Transcripts']] = relationship('Transcripts', foreign_keys='[Transcripts.audio_session_id]', back_populates='audio_session')
    stt_metrics: Mapped[list['SttMetrics']] = relationship('SttMetrics', back_populates='session')
    utterances: Mapped[list['Utterances']] = relationship('Utterances', back_populates='session')
    compliance_triggers: Mapped[list['ComplianceTriggers']] = relationship('ComplianceTriggers', back_populates='session')
    compliance_alerts: Mapped[list['ComplianceAlerts']] = relationship('ComplianceAlerts', back_populates='session')


class BenchDatasets(Base):
    __tablename__ = 'bench_datasets'
    __table_args__ = (
        PrimaryKeyConstraint('id', name='bench_datasets_pkey'),
        UniqueConstraint('code', name='bench_datasets_code_key')
    )

    id: Mapped[int] = mapped_column(Integer, Identity(always=True, start=1, increment=1, minvalue=1, maxvalue=2147483647, cycle=False, cache=1), primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(Text, nullable=False)
    title_ru: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False, server_default=text('now()'))
    description: Mapped[Optional[str]] = mapped_column(Text)

    bench_cases: Mapped[list['BenchCases']] = relationship('BenchCases', back_populates='dataset')
    bench_runs: Mapped[list['BenchRuns']] = relationship('BenchRuns', back_populates='dataset')


class Channels(Base):
    __tablename__ = 'channels'
    __table_args__ = (
        PrimaryKeyConstraint('code', name='channels_pkey'),
    )

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    name_ru: Mapped[str] = mapped_column(Text, nullable=False)
    name_en: Mapped[str] = mapped_column(Text, nullable=False)
    subtypes: Mapped[list[str]] = mapped_column(ARRAY(Text()), nullable=False, server_default=text("'{}'::text[]"))
    identifies_client: Mapped[bool] = mapped_column(Boolean, nullable=False)
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text('false'))

    signals: Mapped[list['Signals']] = relationship('Signals', back_populates='channels')
    bench_cases: Mapped[list['BenchCases']] = relationship('BenchCases', back_populates='channels')
    ingest_sources: Mapped[list['IngestSources']] = relationship('IngestSources', back_populates='channels')
    notification_templates: Mapped[list['NotificationTemplates']] = relationship('NotificationTemplates', back_populates='channels')


class DbActivityLog(Base):
    __tablename__ = 'db_activity_log'
    __table_args__ = (
        CheckConstraint("op = ANY (ARRAY['INSERT'::text, 'UPDATE'::text, 'DELETE'::text])", name='db_activity_log_op_check'),
        PrimaryKeyConstraint('id', name='db_activity_log_pkey'),
        {'comment': 'Лента INSERT/UPDATE/DELETE для демонстрации работы агента с БД'}
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True, start=1, increment=1, minvalue=1, maxvalue=9223372036854775807, cycle=False, cache=1), primary_key=True, autoincrement=True)
    table_name: Mapped[str] = mapped_column(Text, nullable=False)
    op: Mapped[str] = mapped_column(Text, nullable=False)
    pk: Mapped[str] = mapped_column(Text, nullable=False)
    ts: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False, server_default=text('now()'))
    summary: Mapped[Optional[dict]] = mapped_column(JSONB)


class DcltvRates(Base):
    __tablename__ = 'dcltv_rates'
    __table_args__ = (
        CheckConstraint('rate_rub >= 0::numeric', name='dcltv_rates_rate_rub_check'),
        PrimaryKeyConstraint('code', name='dcltv_rates_pkey'),
        {'comment': 'Ставки калькулятора «Потери от сбоев (dCLTV)»; непокрытые системы '
                '→ bank_average 4050 (ТЗ 14.4)'}
    )

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    name_ru: Mapped[str] = mapped_column(Text, nullable=False)
    name_en: Mapped[str] = mapped_column(Text, nullable=False)
    rate_rub: Mapped[decimal.Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    maps_to: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))

    economics_settings: Mapped[list['EconomicsSettings']] = relationship('EconomicsSettings', back_populates='dcltv_rates')
    product_lines: Mapped[list['ProductLines']] = relationship('ProductLines', back_populates='dcltv_rates')
    incident_economics: Mapped[list['IncidentEconomics']] = relationship('IncidentEconomics', back_populates='dcltv_rates')


class DemoAssets(Base):
    __tablename__ = 'demo_assets'
    __table_args__ = (
        CheckConstraint("kind = ANY (ARRAY['audio'::text, 'transcript'::text, 'post'::text, 'cassette'::text])", name='demo_assets_kind_check'),
        PrimaryKeyConstraint('id', name='demo_assets_pkey')
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True, start=1, increment=1, minvalue=1, maxvalue=9223372036854775807, cycle=False, cache=1), primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    title_ru: Mapped[str] = mapped_column(Text, nullable=False)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    checksum: Mapped[str] = mapped_column(Text, nullable=False)
    scenario_id: Mapped[Optional[str]] = mapped_column(Text)
    ref: Mapped[Optional[dict]] = mapped_column(JSONB)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer)

    audio_sessions: Mapped[list['AudioSessions']] = relationship('AudioSessions', back_populates='demo_asset')


class ExternalPosts(Base):
    __tablename__ = 'external_posts'
    __table_args__ = (
        CheckConstraint("origin = ANY (ARRAY['demo'::text, 'api'::text, 'background'::text, 'scenario'::text, 'telegram_bot'::text])", name='external_posts_origin_check'),
        CheckConstraint("platform = ANY (ARRAY['review_portal'::text, 'telegram_channel'::text])", name='external_posts_platform_check'),
        CheckConstraint("status = ANY (ARRAY['new'::text, 'processing'::text, 'replied'::text, 'escalated_to_dm'::text, 'ignored'::text])", name='external_posts_status_check'),
        ForeignKeyConstraint(['author_client_id'], ['clients.id'], name='external_posts_author_client_id_fkey'),
        ForeignKeyConstraint(['run_id'], ['sim_runs.id'], ondelete='CASCADE', name='external_posts_run_id_fkey'),
        ForeignKeyConstraint(['signal_id'], ['signals.id'], name='external_posts_signal_id_fkey'),
        PrimaryKeyConstraint('id', name='external_posts_pkey'),
        {'comment': 'Эмулятор ленты отзовика/Telegram-канала (/feed); реальные '
                'площадки не парсятся'}
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True, start=1, increment=1, minvalue=1, maxvalue=9223372036854775807, cycle=False, cache=1), primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    platform: Mapped[str] = mapped_column(Text, nullable=False)
    author_nick: Mapped[str] = mapped_column(Text, nullable=False)
    text_: Mapped[str] = mapped_column('text', Text, nullable=False)
    mentions: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    posted_at: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False, server_default=text('now()'))
    posted_sim: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False)
    reactions: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text('0'))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'new'::text"))
    origin: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'demo'::text"))
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False, server_default=text('now()'))
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False, server_default=text('now()'))
    public_id: Mapped[Optional[str]] = mapped_column(Text, Computed("('POST-'::text || lpad((id)::text, 6, '0'::text))", persisted=True))
    author_client_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    match_confidence: Mapped[Optional[decimal.Decimal]] = mapped_column(Numeric(4, 3))
    signal_id: Mapped[Optional[int]] = mapped_column(BigInteger)

    author_client: Mapped[Optional['Clients']] = relationship('Clients', back_populates='external_posts')
    run: Mapped['SimRuns'] = relationship('SimRuns', back_populates='external_posts')
    signal: Mapped[Optional['Signals']] = relationship('Signals', foreign_keys=[signal_id], back_populates='external_posts_signal')
    signals_external_post: Mapped[list['Signals']] = relationship('Signals', foreign_keys='[Signals.external_post_id]', back_populates='external_post')
    external_replies: Mapped[list['ExternalReplies']] = relationship('ExternalReplies', back_populates='post')


class Faults(Base):
    __tablename__ = 'faults'
    __table_args__ = (
        ForeignKeyConstraint(['caused_by_incident_id'], ['incidents.id'], name='faults_caused_by_fk'),
        ForeignKeyConstraint(['error_code'], ['error_codes.code'], name='faults_error_code_fkey'),
        ForeignKeyConstraint(['run_id'], ['sim_runs.id'], ondelete='CASCADE', name='faults_run_id_fkey'),
        ForeignKeyConstraint(['system_code'], ['systems.code'], name='faults_system_code_fkey'),
        PrimaryKeyConstraint('id', name='faults_pkey')
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True, start=1, increment=1, minvalue=1, maxvalue=9223372036854775807, cycle=False, cache=1), primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    system_code: Mapped[str] = mapped_column(Text, nullable=False)
    error_code: Mapped[str] = mapped_column(Text, nullable=False)
    started_sim: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False)
    impact_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text('0'))
    affected_clients: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text('0'))
    region_codes: Mapped[list[str]] = mapped_column(ARRAY(Text()), nullable=False, server_default=text("'{}'::text[]"))
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False, server_default=text('now()'))
    resolved_sim: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(True))
    caused_by_incident_id: Mapped[Optional[int]] = mapped_column(BigInteger)

    caused_by_incident: Mapped[Optional['Incidents']] = relationship('Incidents', foreign_keys=[caused_by_incident_id], back_populates='faults_caused_by_incident')
    error_codes: Mapped['ErrorCodes'] = relationship('ErrorCodes', back_populates='faults')
    run: Mapped['SimRuns'] = relationship('SimRuns', back_populates='faults')
    systems: Mapped['Systems'] = relationship('Systems', back_populates='faults')
    incidents_fault: Mapped[list['Incidents']] = relationship('Incidents', foreign_keys='[Incidents.fault_id]', back_populates='fault')
    operations: Mapped[list['Operations']] = relationship('Operations', back_populates='fault')
    signals: Mapped[list['Signals']] = relationship('Signals', back_populates='source_fault')
    system_logs: Mapped[list['SystemLogs']] = relationship('SystemLogs', back_populates='fault')


class FederalDistricts(Base):
    __tablename__ = 'federal_districts'
    __table_args__ = (
        PrimaryKeyConstraint('code', name='federal_districts_pkey'),
    )

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    name_ru: Mapped[str] = mapped_column(Text, nullable=False)
    name_en: Mapped[str] = mapped_column(Text, nullable=False)

    regions: Mapped[list['Regions']] = relationship('Regions', back_populates='federal_districts')


class GiftCatalog(Base):
    __tablename__ = 'gift_catalog'
    __table_args__ = (
        PrimaryKeyConstraint('code', name='gift_catalog_pkey'),
    )

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    name_ru: Mapped[str] = mapped_column(Text, nullable=False)
    name_en: Mapped[str] = mapped_column(Text, nullable=False)
    segments: Mapped[list[str]] = mapped_column(ARRAY(Text()), nullable=False)
    rule: Mapped[dict] = mapped_column(JSONB, nullable=False)
    partner_display_name: Mapped[Optional[str]] = mapped_column(Text)


class Incidents(Base):
    __tablename__ = 'incidents'
    __table_args__ = (
        CheckConstraint("complexity = ANY (ARRAY['instant'::text, 'easy'::text, 'medium'::text, 'hard'::text])", name='incidents_complexity_check'),
        CheckConstraint("created_by = ANY (ARRAY['agent'::text, 'human'::text, 'team'::text, 'behavior_model'::text, 'scenario'::text, 'compliance'::text])", name='incidents_created_by_check'),
        CheckConstraint("criticality = ANY (ARRAY['low'::text, 'medium'::text, 'high'::text])", name='incidents_criticality_check'),
        CheckConstraint("incident_type = ANY (ARRAY['tech_fault'::text, 'client_error'::text, 'tariff_terms'::text, 'service_quality'::text, 'fraud_suspicion'::text, 'legal_regulatory'::text, 'info_request'::text, 'suggestion'::text, 'account_closure'::text, 'proactive'::text, 'fee_refund'::text, 'misselling'::text])", name='incidents_incident_type_check'),
        CheckConstraint("outcome_class = ANY (ARRAY['closed_in_sla_with_gift'::text, 'closed_in_sla'::text, 'closed_late'::text, 'closed_with_regression'::text, 'open'::text, 'rejected'::text, 'churned'::text])", name='incidents_outcome_class_check'),
        CheckConstraint('priority >= 1 AND priority <= 4', name='incidents_priority_check'),
        CheckConstraint("routing_status = ANY (ARRAY['pending'::text, 'routed'::text, 'escalated'::text, 'clarification'::text, 'rejected'::text])", name='incidents_routing_status_check'),
        CheckConstraint("status = ANY (ARRAY['new'::text, 'classified'::text, 'routed'::text, 'in_progress'::text, 'fix_proposed'::text, 'fix_deployed'::text, 'verifying'::text, 'resolved'::text, 'closed'::text, 'awaiting_human'::text, 'awaiting_client'::text, 'escalated'::text, 'duplicate'::text, 'rejected'::text])", name='incidents_status_check'),
        ForeignKeyConstraint(['agent_run_id'], ['agent_runs.id'], name='incidents_agent_run_fk'),
        ForeignKeyConstraint(['duplicate_of_id'], ['incidents.id'], name='incidents_duplicate_of_id_fkey'),
        ForeignKeyConstraint(['error_code'], ['error_codes.code'], name='incidents_error_code_fkey'),
        ForeignKeyConstraint(['fault_id'], ['faults.id'], name='incidents_fault_id_fkey'),
        ForeignKeyConstraint(['primary_client_id'], ['clients.id'], name='incidents_primary_client_id_fkey'),
        ForeignKeyConstraint(['product_code'], ['products.code'], name='incidents_product_code_fkey'),
        ForeignKeyConstraint(['region_code'], ['regions.code'], name='incidents_region_code_fkey'),
        ForeignKeyConstraint(['run_id'], ['sim_runs.id'], ondelete='CASCADE', name='incidents_run_id_fkey'),
        ForeignKeyConstraint(['system_code'], ['systems.code'], name='incidents_system_code_fkey'),
        ForeignKeyConstraint(['team_code'], ['teams.code'], name='incidents_team_code_fkey'),
        PrimaryKeyConstraint('id', name='incidents_pkey')
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True, start=1, increment=1, minvalue=1, maxvalue=9223372036854775807, cycle=False, cache=1), primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    incident_type: Mapped[str] = mapped_column(Text, nullable=False)
    team_code: Mapped[str] = mapped_column(Text, nullable=False)
    co_team_codes: Mapped[list[str]] = mapped_column(ARRAY(Text()), nullable=False, server_default=text("'{}'::text[]"))
    complexity: Mapped[str] = mapped_column(Text, nullable=False)
    criticality: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'new'::text"))
    flags: Mapped[list[str]] = mapped_column(ARRAY(Text()), nullable=False, server_default=text("'{}'::text[]"))
    mass_impact: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text('1'))
    created_by: Mapped[str] = mapped_column(Text, nullable=False)
    created_sim: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False)
    sla_due_sim: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False)
    take_due_sim: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False)
    report_due_sims: Mapped[list[datetime.datetime]] = mapped_column(ARRAY(DateTime(timezone=True)), nullable=False, server_default=text("'{}'::timestamp with time zone[]"))
    sla_breached: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text('false'))
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False, server_default=text('now()'))
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False, server_default=text('now()'))
    routing_status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'pending'::text"))
    public_id: Mapped[Optional[str]] = mapped_column(Text, Computed("('INC-'::text || lpad((id)::text, 6, '0'::text))", persisted=True))
    product_code: Mapped[Optional[str]] = mapped_column(Text)
    system_code: Mapped[Optional[str]] = mapped_column(Text)
    error_code: Mapped[Optional[str]] = mapped_column(Text)
    root_cause: Mapped[Optional[str]] = mapped_column(Text)
    resolution_summary: Mapped[Optional[str]] = mapped_column(Text)
    region_code: Mapped[Optional[str]] = mapped_column(Text)
    primary_client_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    fault_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    duplicate_of_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    taken_sim: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(True))
    resolved_sim: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(True))
    closed_sim: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(True))
    outcome_class: Mapped[Optional[str]] = mapped_column(Text)
    agent_run_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    problem_summary: Mapped[Optional[dict]] = mapped_column(JSONB)

    agent_runs_incident: Mapped[list['AgentRuns']] = relationship('AgentRuns', foreign_keys='[AgentRuns.incident_id]', back_populates='incident')
    audio_sessions: Mapped[list['AudioSessions']] = relationship('AudioSessions', back_populates='incident')
    faults_caused_by_incident: Mapped[list['Faults']] = relationship('Faults', foreign_keys='[Faults.caused_by_incident_id]', back_populates='caused_by_incident')
    agent_run: Mapped[Optional['AgentRuns']] = relationship('AgentRuns', foreign_keys=[agent_run_id], back_populates='incidents_agent_run')
    duplicate_of: Mapped[Optional['Incidents']] = relationship('Incidents', remote_side=[id], back_populates='duplicate_of_reverse')
    duplicate_of_reverse: Mapped[list['Incidents']] = relationship('Incidents', remote_side=[duplicate_of_id], back_populates='duplicate_of')
    error_codes: Mapped[Optional['ErrorCodes']] = relationship('ErrorCodes', back_populates='incidents')
    fault: Mapped[Optional['Faults']] = relationship('Faults', foreign_keys=[fault_id], back_populates='incidents_fault')
    primary_client: Mapped[Optional['Clients']] = relationship('Clients', back_populates='incidents')
    products: Mapped[Optional['Products']] = relationship('Products', back_populates='incidents')
    regions: Mapped[Optional['Regions']] = relationship('Regions', back_populates='incidents')
    run: Mapped['SimRuns'] = relationship('SimRuns', back_populates='incidents')
    systems: Mapped[Optional['Systems']] = relationship('Systems', back_populates='incidents')
    teams: Mapped['Teams'] = relationship('Teams', back_populates='incidents')
    incident_signals: Mapped[list['IncidentSignals']] = relationship('IncidentSignals', back_populates='incident')
    incident_status_history: Mapped[list['IncidentStatusHistory']] = relationship('IncidentStatusHistory', back_populates='incident')
    external_replies: Mapped[list['ExternalReplies']] = relationship('ExternalReplies', back_populates='incident')
    followups: Mapped[list['Followups']] = relationship('Followups', back_populates='incident')
    incident_artifacts: Mapped[list['IncidentArtifacts']] = relationship('IncidentArtifacts', back_populates='incident')
    incident_economics: Mapped['IncidentEconomics'] = relationship('IncidentEconomics', uselist=False, back_populates='incident')
    team_actions: Mapped[list['TeamActions']] = relationship('TeamActions', back_populates='incident')
    churn_events: Mapped[list['ChurnEvents']] = relationship('ChurnEvents', back_populates='closure_incident')
    client_states: Mapped[list['ClientStates']] = relationship('ClientStates', back_populates='incident')
    notifications: Mapped[list['Notifications']] = relationship('Notifications', back_populates='incident')
    tasks: Mapped[list['Tasks']] = relationship('Tasks', back_populates='incident')
    client_reactions: Mapped[list['ClientReactions']] = relationship('ClientReactions', back_populates='incident')
    human_decisions: Mapped[list['HumanDecisions']] = relationship('HumanDecisions', back_populates='incident')
    compliance_alerts: Mapped[list['ComplianceAlerts']] = relationship('ComplianceAlerts', back_populates='incident')
    escalations: Mapped[list['Escalations']] = relationship('Escalations', back_populates='incident')
    financial_evidence: Mapped[list['FinancialEvidence']] = relationship('FinancialEvidence', back_populates='incident')


class LlmApiKeys(Base):
    __tablename__ = 'llm_api_keys'
    __table_args__ = (
        CheckConstraint("provider = ANY (ARRAY['gigachat'::text, 'openai_compatible'::text])", name='llm_api_keys_provider_check'),
        PrimaryKeyConstraint('id', name='llm_api_keys_pkey')
    )

    id: Mapped[int] = mapped_column(Integer, Identity(always=True, start=1, increment=1, minvalue=1, maxvalue=2147483647, cycle=False, cache=1), primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    encrypted_key: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    tokens_used: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text('0'))
    requests_today: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text('0'))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text('true'))
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False, server_default=text('now()'))
    tokens_limit: Mapped[Optional[int]] = mapped_column(BigInteger)
    requests_day: Mapped[Optional[datetime.date]] = mapped_column(Date)
    last_error: Mapped[Optional[str]] = mapped_column(Text)


class LlmCassettes(Base):
    __tablename__ = 'llm_cassettes'
    __table_args__ = (
        PrimaryKeyConstraint('id', name='llm_cassettes_pkey'),
        UniqueConstraint('request_hash', 'model', name='llm_cassettes_request_hash_model_key'),
        {'comment': 'Записанные ответы реальных моделей для провайдера replay (честный '
                'офлайн-режим)'}
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True, start=1, increment=1, minvalue=1, maxvalue=9223372036854775807, cycle=False, cache=1), primary_key=True, autoincrement=True)
    request_hash: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    response: Mapped[dict] = mapped_column(JSONB, nullable=False)
    chunks: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    usage: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    recorded_at: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False, server_default=text('now()'))
    scenario_id: Mapped[Optional[str]] = mapped_column(Text)
    prompt_version: Mapped[Optional[str]] = mapped_column(Text)


class LlmProfiles(Base):
    __tablename__ = 'llm_profiles'
    __table_args__ = (
        CheckConstraint("provider = ANY (ARRAY['gigachat'::text, 'openai_compatible'::text, 'mock'::text])", name='llm_profiles_provider_check'),
        CheckConstraint("role = ANY (ARRAY['main'::text, 'fast'::text, 'twin'::text, 'bench_only'::text])", name='llm_profiles_role_check'),
        PrimaryKeyConstraint('id', name='llm_profiles_pkey'),
        UniqueConstraint('code', name='llm_profiles_code_key')
    )

    id: Mapped[int] = mapped_column(Integer, Identity(always=True, start=1, increment=1, minvalue=1, maxvalue=2147483647, cycle=False, cache=1), primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    temperature: Mapped[decimal.Decimal] = mapped_column(Numeric(3, 2), nullable=False, server_default=text('0'))
    price_in_per_1m: Mapped[decimal.Decimal] = mapped_column(Numeric(10, 4), nullable=False, server_default=text('0'))
    price_out_per_1m: Mapped[decimal.Decimal] = mapped_column(Numeric(10, 4), nullable=False, server_default=text('0'))
    supports_tools: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text('true'))
    supports_stream: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text('true'))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text('true'))
    extra: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    base_url: Mapped[Optional[str]] = mapped_column(Text)
    rpm_limit: Mapped[Optional[int]] = mapped_column(Integer)
    rpd_limit: Mapped[Optional[int]] = mapped_column(Integer)

    agent_runs: Mapped[list['AgentRuns']] = relationship('AgentRuns', back_populates='llm_profile')
    bench_runs: Mapped[list['BenchRuns']] = relationship('BenchRuns', back_populates='llm_profile')
    sim_runs: Mapped[list['SimRuns']] = relationship('SimRuns', back_populates='llm_profile')


class MissellingPatterns(Base):
    __tablename__ = 'misselling_patterns'
    __table_args__ = (
        CheckConstraint("alert_policy = ANY (ARRAY['counter'::text, 'immediate'::text, 'report'::text])", name='misselling_patterns_alert_policy_check'),
        CheckConstraint("family = ANY (ARRAY['misselling'::text, 'conduct'::text])", name='misselling_patterns_family_check'),
        PrimaryKeyConstraint('code', name='misselling_patterns_pkey'),
        {'comment': 'Таксономия нарушений сотрудника: семейства misselling (ТЗ 22.4) и '
                'conduct — rudeness, script_violation, misinformation (ТЗ 22.8); '
                'имя таблицы сохранено для совместимости v1.3'}
    )

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    name_ru: Mapped[str] = mapped_column(Text, nullable=False)
    name_en: Mapped[str] = mapped_column(Text, nullable=False)
    description_ru: Mapped[str] = mapped_column(Text, nullable=False)
    examples: Mapped[list[str]] = mapped_column(ARRAY(Text()), nullable=False, server_default=text("'{}'::text[]"))
    counter_examples: Mapped[list[str]] = mapped_column(ARRAY(Text()), nullable=False, server_default=text("'{}'::text[]"))
    keywords: Mapped[list[str]] = mapped_column(ARRAY(Text()), nullable=False, server_default=text("'{}'::text[]"))
    weight: Mapped[decimal.Decimal] = mapped_column(Numeric(4, 2), nullable=False, server_default=text('1'))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text('true'))
    family: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'misselling'::text"))
    alert_policy: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'counter'::text"))
    immediate_threshold: Mapped[decimal.Decimal] = mapped_column(Numeric(4, 3), nullable=False, server_default=text('0.8'))
    recommendation_ru: Mapped[Optional[str]] = mapped_column(Text)
    training_module: Mapped[Optional[str]] = mapped_column(Text)

    compliance_triggers: Mapped[list['ComplianceTriggers']] = relationship('ComplianceTriggers', back_populates='misselling_patterns')


class Operations(Base):
    __tablename__ = 'operations'
    __table_args__ = (
        CheckConstraint("method = ANY (ARRAY['qr_sbp'::text, 'card'::text, 'transfer'::text, 'cash'::text, 'online'::text])", name='operations_method_check'),
        CheckConstraint("status = ANY (ARRAY['success'::text, 'failed'::text, 'pending'::text, 'reversed'::text])", name='operations_status_check'),
        ForeignKeyConstraint(['client_id'], ['clients.id'], ondelete='CASCADE', name='operations_client_id_fkey'),
        ForeignKeyConstraint(['error_code'], ['error_codes.code'], name='operations_error_code_fkey'),
        ForeignKeyConstraint(['fault_id'], ['faults.id'], name='operations_fault_fk'),
        ForeignKeyConstraint(['product_code'], ['products.code'], name='operations_product_code_fkey'),
        ForeignKeyConstraint(['run_id'], ['sim_runs.id'], ondelete='CASCADE', name='operations_run_id_fkey'),
        PrimaryKeyConstraint('id', name='operations_pkey')
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True, start=1, increment=1, minvalue=1, maxvalue=9223372036854775807, cycle=False, cache=1), primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    client_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    product_code: Mapped[str] = mapped_column(Text, nullable=False)
    op_type: Mapped[str] = mapped_column(Text, nullable=False)
    system_path: Mapped[list[str]] = mapped_column(ARRAY(Text()), nullable=False)
    fee_amount: Mapped[decimal.Decimal] = mapped_column(Numeric(14, 2), nullable=False, server_default=text('0'))
    status: Mapped[str] = mapped_column(Text, nullable=False)
    started_sim: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False, server_default=text('now()'))
    amount_rub: Mapped[Optional[decimal.Decimal]] = mapped_column(Numeric(14, 2))
    method: Mapped[Optional[str]] = mapped_column(Text)
    merchant: Mapped[Optional[str]] = mapped_column(Text)
    error_code: Mapped[Optional[str]] = mapped_column(Text)
    fault_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    finished_sim: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(True))

    client: Mapped['Clients'] = relationship('Clients', back_populates='operations')
    error_codes: Mapped[Optional['ErrorCodes']] = relationship('ErrorCodes', back_populates='operations')
    fault: Mapped[Optional['Faults']] = relationship('Faults', back_populates='operations')
    products: Mapped['Products'] = relationship('Products', back_populates='operations')
    run: Mapped['SimRuns'] = relationship('SimRuns', back_populates='operations')
    signals: Mapped[list['Signals']] = relationship('Signals', back_populates='source_operation')
    system_logs: Mapped[list['SystemLogs']] = relationship('SystemLogs', back_populates='affected_operation')
    ledger_entries: Mapped[list['LedgerEntries']] = relationship('LedgerEntries', back_populates='operation')


class Products(Base):
    __tablename__ = 'products'
    __table_args__ = (
        PrimaryKeyConstraint('code', name='products_pkey'),
    )

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    name_ru: Mapped[str] = mapped_column(Text, nullable=False)
    name_en: Mapped[str] = mapped_column(Text, nullable=False)
    tariffs: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    promos: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))

    incidents: Mapped[list['Incidents']] = relationship('Incidents', back_populates='products')
    operations: Mapped[list['Operations']] = relationship('Operations', back_populates='products')
    error_codes: Mapped[list['ErrorCodes']] = relationship('ErrorCodes', back_populates='products')
    tariffs_: Mapped[list['Tariffs']] = relationship('Tariffs', back_populates='products')
    client_products: Mapped[list['ClientProducts']] = relationship('ClientProducts', back_populates='products')


class Psychotypes(Base):
    __tablename__ = 'psychotypes'
    __table_args__ = (
        PrimaryKeyConstraint('code', name='psychotypes_pkey'),
        {'comment': 'Психотипы клиентов, ТЗ 4.5; params: p_complain, '
                'complain_delay_min[2], patience_days[2], care_sensitivity, '
                'repeat_prob, channel_weights, gift_elasticity, base_churn_hazard, '
                'thank_you_prob'}
    )

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    name_ru: Mapped[str] = mapped_column(Text, nullable=False)
    name_en: Mapped[str] = mapped_column(Text, nullable=False)
    params: Mapped[dict] = mapped_column(JSONB, nullable=False)

    segment_psychotype_mix: Mapped[list['SegmentPsychotypeMix']] = relationship('SegmentPsychotypeMix', back_populates='psychotypes')
    clients: Mapped[list['Clients']] = relationship('Clients', back_populates='psychotypes')


class RoutingRules(Base):
    __tablename__ = 'routing_rules'
    __table_args__ = (
        PrimaryKeyConstraint('id', name='routing_rules_pkey'),
    )

    id: Mapped[int] = mapped_column(Integer, Identity(always=True, start=1, increment=1, minvalue=1, maxvalue=2147483647, cycle=False, cache=1), primary_key=True, autoincrement=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text('100'))
    match: Mapped[dict] = mapped_column(JSONB, nullable=False)
    team_codes: Mapped[list[str]] = mapped_column(ARRAY(Text()), nullable=False)
    notes_ru: Mapped[Optional[str]] = mapped_column(Text)


class Scenarios(Base):
    __tablename__ = 'scenarios'
    __table_args__ = (
        PrimaryKeyConstraint('id', name='scenarios_pkey'),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    title_ru: Mapped[str] = mapped_column(Text, nullable=False)
    title_en: Mapped[str] = mapped_column(Text, nullable=False)
    yaml_source: Mapped[str] = mapped_column(Text, nullable=False)
    expected: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    last_run_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(True))
    last_result: Mapped[Optional[dict]] = mapped_column(JSONB)

    sim_runs: Mapped[list['SimRuns']] = relationship('SimRuns', back_populates='scenario')


class Segments(Base):
    __tablename__ = 'segments'
    __table_args__ = (
        CheckConstraint('population_share >= 0::numeric AND population_share <= 1::numeric', name='segments_population_share_check'),
        PrimaryKeyConstraint('code', name='segments_pkey')
    )

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    name_ru: Mapped[str] = mapped_column(Text, nullable=False)
    name_en: Mapped[str] = mapped_column(Text, nullable=False)
    population_share: Mapped[decimal.Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    first_response_min: Mapped[int] = mapped_column(Integer, nullable=False)
    priority_multiplier: Mapped[decimal.Decimal] = mapped_column(Numeric(3, 2), nullable=False, server_default=text('1.0'))
    clv_min_rub: Mapped[int] = mapped_column(Integer, nullable=False)
    clv_max_rub: Mapped[int] = mapped_column(Integer, nullable=False)
    tone: Mapped[str] = mapped_column(Text, nullable=False)
    hitl_required: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text('false'))
    personal_manager: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text('false'))

    bench_cases: Mapped[list['BenchCases']] = relationship('BenchCases', back_populates='segments')
    notification_templates: Mapped[list['NotificationTemplates']] = relationship('NotificationTemplates', back_populates='segments')
    segment_psychotype_mix: Mapped[list['SegmentPsychotypeMix']] = relationship('SegmentPsychotypeMix', back_populates='segments')
    clients: Mapped[list['Clients']] = relationship('Clients', back_populates='segments')


class ServiceScripts(Base):
    __tablename__ = 'service_scripts'
    __table_args__ = (
        CheckConstraint("kind = ANY (ARRAY['retail_service'::text, 'retail_sales'::text, 'contact_center'::text])", name='service_scripts_kind_check'),
        PrimaryKeyConstraint('code', name='service_scripts_pkey'),
        {'comment': 'Эталонные скрипты обслуживания для проверки script_violation (ТЗ '
                '22.8)'}
    )

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    name_ru: Mapped[str] = mapped_column(Text, nullable=False)
    steps: Mapped[dict] = mapped_column(JSONB, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text('1'))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text('true'))
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False, server_default=text('now()'))


class Settings(Base):
    __tablename__ = 'settings'
    __table_args__ = (
        PrimaryKeyConstraint('key', name='settings_pkey'),
        {'comment': 'Ключи: bank.name, bank.clients_profile, sim.*, policies.*, '
                'i18n.default, tgbot.enabled, twins.daily_limit, bench.* …'}
    )

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[dict] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False, server_default=text('now()'))


class SignalTypes(Base):
    __tablename__ = 'signal_types'
    __table_args__ = (
        CheckConstraint("base_criticality = ANY (ARRAY['low'::text, 'medium'::text, 'high'::text])", name='signal_types_base_criticality_check'),
        PrimaryKeyConstraint('code', name='signal_types_pkey')
    )

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    name_ru: Mapped[str] = mapped_column(Text, nullable=False)
    name_en: Mapped[str] = mapped_column(Text, nullable=False)
    requires_hitl: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text('false'))
    creates_incident: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text('true'))
    base_criticality: Mapped[Optional[str]] = mapped_column(Text)


class Signals(Base):
    __tablename__ = 'signals'
    __table_args__ = (
        CheckConstraint("origin = ANY (ARRAY['sim'::text, 'scenario'::text, 'jury'::text, 'landing'::text, 'telegram_bot'::text, 'proactive'::text, 'twin'::text, 'review_portal'::text, 'voice_input'::text, 'api'::text, 'transcript'::text, 'polling'::text])", name='signals_origin_check'),
        CheckConstraint("sentiment = ANY (ARRAY['positive'::text, 'neutral'::text, 'negative'::text])", name='signals_sentiment_check'),
        CheckConstraint("status = ANY (ARRAY['new'::text, 'processing'::text, 'classified'::text, 'linked'::text, 'deferred'::text, 'awaiting_human'::text, 'awaiting_client'::text, 'answered'::text, 'closed'::text, 'noise'::text, 'error'::text])", name='signals_status_check'),
        ForeignKeyConstraint(['channel_code'], ['channels.code'], name='signals_channel_code_fkey'),
        ForeignKeyConstraint(['client_id'], ['clients.id'], name='signals_client_id_fkey'),
        ForeignKeyConstraint(['external_post_id'], ['external_posts.id'], name='signals_external_post_fk'),
        ForeignKeyConstraint(['parent_signal_id'], ['signals.id'], name='signals_parent_signal_id_fkey'),
        ForeignKeyConstraint(['product_line_code'], ['product_lines.code'], name='signals_product_line_code_fkey'),
        ForeignKeyConstraint(['run_id'], ['sim_runs.id'], ondelete='CASCADE', name='signals_run_id_fkey'),
        ForeignKeyConstraint(['source_fault_id'], ['faults.id'], name='signals_source_fault_id_fkey'),
        ForeignKeyConstraint(['source_operation_id'], ['operations.id'], name='signals_source_operation_id_fkey'),
        ForeignKeyConstraint(['transcript_id'], ['transcripts.id'], name='signals_transcript_fk'),
        PrimaryKeyConstraint('id', name='signals_pkey'),
        UniqueConstraint('tracking_token', name='signals_tracking_token_key')
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True, start=1, increment=1, minvalue=1, maxvalue=9223372036854775807, cycle=False, cache=1), primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    channel_code: Mapped[str] = mapped_column(Text, nullable=False)
    text_: Mapped[str] = mapped_column('text', Text, nullable=False)
    lang: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'ru'::text"))
    received_sim: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False)
    received_at: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False, server_default=text('now()'))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'new'::text"))
    origin: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'sim'::text"))
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False, server_default=text('now()'))
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False, server_default=text('now()'))
    red_words: Mapped[list[str]] = mapped_column(ARRAY(Text()), nullable=False, server_default=text("'{}'::text[]"))
    flags: Mapped[list[str]] = mapped_column(ARRAY(Text()), nullable=False, server_default=text("'{}'::text[]"))
    meta: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    public_id: Mapped[Optional[str]] = mapped_column(Text, Computed("('SIG-'::text || lpad((id)::text, 6, '0'::text))", persisted=True))
    channel_subtype: Mapped[Optional[str]] = mapped_column(Text)
    client_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    external_contact: Mapped[Optional[dict]] = mapped_column(JSONB)
    voice_meta: Mapped[Optional[dict]] = mapped_column(JSONB)
    external_post_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    geo: Mapped[Optional[dict]] = mapped_column(JSONB)
    transcript_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    sentiment: Mapped[Optional[str]] = mapped_column(Text)
    source_operation_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    source_fault_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    parent_signal_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    classification: Mapped[Optional[dict]] = mapped_column(JSONB)
    decision: Mapped[Optional[dict]] = mapped_column(JSONB)
    tracking_token: Mapped[Optional[str]] = mapped_column(Text)
    product_line_code: Mapped[Optional[str]] = mapped_column(Text)

    agent_runs: Mapped[list['AgentRuns']] = relationship('AgentRuns', back_populates='signal')
    external_posts_signal: Mapped[list['ExternalPosts']] = relationship('ExternalPosts', foreign_keys='[ExternalPosts.signal_id]', back_populates='signal')
    channels: Mapped['Channels'] = relationship('Channels', back_populates='signals')
    client: Mapped[Optional['Clients']] = relationship('Clients', back_populates='signals')
    external_post: Mapped[Optional['ExternalPosts']] = relationship('ExternalPosts', foreign_keys=[external_post_id], back_populates='signals_external_post')
    parent_signal: Mapped[Optional['Signals']] = relationship('Signals', remote_side=[id], back_populates='parent_signal_reverse')
    parent_signal_reverse: Mapped[list['Signals']] = relationship('Signals', remote_side=[parent_signal_id], back_populates='parent_signal')
    product_lines: Mapped[Optional['ProductLines']] = relationship('ProductLines', back_populates='signals')
    run: Mapped['SimRuns'] = relationship('SimRuns', back_populates='signals')
    source_fault: Mapped[Optional['Faults']] = relationship('Faults', back_populates='signals')
    source_operation: Mapped[Optional['Operations']] = relationship('Operations', back_populates='signals')
    transcript: Mapped[Optional['Transcripts']] = relationship('Transcripts', foreign_keys=[transcript_id], back_populates='signals_transcript')
    transcripts_signal: Mapped[list['Transcripts']] = relationship('Transcripts', foreign_keys='[Transcripts.signal_id]', back_populates='signal')
    incident_signals: Mapped[list['IncidentSignals']] = relationship('IncidentSignals', back_populates='signal')
    followups: Mapped[list['Followups']] = relationship('Followups', back_populates='signal')
    ingest_messages: Mapped[list['IngestMessages']] = relationship('IngestMessages', back_populates='signal')
    personal_chat_messages: Mapped['PersonalChatMessages'] = relationship('PersonalChatMessages', uselist=False, back_populates='signal')
    rule_evaluations: Mapped[list['RuleEvaluations']] = relationship('RuleEvaluations', back_populates='signal')
    client_states: Mapped[list['ClientStates']] = relationship('ClientStates', back_populates='signal')
    notifications: Mapped[list['Notifications']] = relationship('Notifications', back_populates='signal')
    client_reactions: Mapped[list['ClientReactions']] = relationship('ClientReactions', back_populates='signal')
    csi_responses: Mapped['CsiResponses'] = relationship('CsiResponses', uselist=False, back_populates='signal')
    human_decisions: Mapped[list['HumanDecisions']] = relationship('HumanDecisions', back_populates='signal')
    escalations: Mapped[list['Escalations']] = relationship('Escalations', back_populates='signal')


class SlaMatrix(Base):
    __tablename__ = 'sla_matrix'
    __table_args__ = (
        CheckConstraint("complexity = ANY (ARRAY['easy'::text, 'medium'::text, 'hard'::text])", name='sla_matrix_complexity_check'),
        CheckConstraint("criticality = ANY (ARRAY['low'::text, 'medium'::text, 'high'::text])", name='sla_matrix_criticality_check'),
        CheckConstraint('fix_days >= 1 AND fix_days <= 10', name='sla_matrix_fix_days_check'),
        PrimaryKeyConstraint('complexity', 'criticality', name='sla_matrix_pkey'),
        {'comment': 'ТЗ 8.2: easy 1/2/3, medium 3/4/5, hard 5/5(+д3)/10(+д3,6,9)'}
    )

    complexity: Mapped[str] = mapped_column(Text, primary_key=True)
    criticality: Mapped[str] = mapped_column(Text, primary_key=True)
    fix_days: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    report_days: Mapped[list[int]] = mapped_column(ARRAY(SmallInteger()), nullable=False, server_default=text("'{}'::smallint[]"))
    take_hours: Mapped[int] = mapped_column(SmallInteger, nullable=False)


class Systems(Base):
    __tablename__ = 'systems'
    __table_args__ = (
        CheckConstraint("layer = ANY (ARRAY['front'::text, 'middle'::text, 'product'::text, 'core'::text])", name='systems_layer_check'),
        PrimaryKeyConstraint('code', name='systems_pkey')
    )

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    name_ru: Mapped[str] = mapped_column(Text, nullable=False)
    name_en: Mapped[str] = mapped_column(Text, nullable=False)
    layer: Mapped[str] = mapped_column(Text, nullable=False)

    faults: Mapped[list['Faults']] = relationship('Faults', back_populates='systems')
    incidents: Mapped[list['Incidents']] = relationship('Incidents', back_populates='systems')
    teams: Mapped[list['Teams']] = relationship('Teams', secondary='team_systems', back_populates='systems')
    error_codes: Mapped[list['ErrorCodes']] = relationship('ErrorCodes', back_populates='systems')
    system_logs: Mapped[list['SystemLogs']] = relationship('SystemLogs', back_populates='systems')


class Teams(Base):
    __tablename__ = 'teams'
    __table_args__ = (
        PrimaryKeyConstraint('code', name='teams_pkey'),
    )

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    name_ru: Mapped[str] = mapped_column(Text, nullable=False)
    name_en: Mapped[str] = mapped_column(Text, nullable=False)
    speed_profile: Mapped[dict] = mapped_column(JSONB, nullable=False)
    lead_display_name: Mapped[str] = mapped_column(Text, nullable=False)

    incidents: Mapped[list['Incidents']] = relationship('Incidents', back_populates='teams')
    systems: Mapped[list['Systems']] = relationship('Systems', secondary='team_systems', back_populates='teams')
    product_lines: Mapped[list['ProductLines']] = relationship('ProductLines', back_populates='teams')
    business_rules: Mapped[list['BusinessRules']] = relationship('BusinessRules', back_populates='teams')
    incident_artifacts: Mapped[list['IncidentArtifacts']] = relationship('IncidentArtifacts', back_populates='teams')
    team_actions: Mapped[list['TeamActions']] = relationship('TeamActions', back_populates='teams')
    notifications: Mapped[list['Notifications']] = relationship('Notifications', back_populates='teams')


class Transcripts(Base):
    __tablename__ = 'transcripts'
    __table_args__ = (
        CheckConstraint("format = ANY (ARRAY['json'::text, 'txt'::text])", name='transcripts_format_check'),
        CheckConstraint("kind = ANY (ARRAY['branch_retail'::text, 'contact_center_call'::text, 'contact_center_chat'::text])", name='transcripts_kind_check'),
        CheckConstraint("source = ANY (ARRAY['api'::text, 'file'::text, 'import'::text, 'scenario'::text])", name='transcripts_source_check'),
        CheckConstraint("status = ANY (ARRAY['received'::text, 'analyzing'::text, 'done'::text, 'failed'::text])", name='transcripts_status_check'),
        ForeignKeyConstraint(['audio_session_id'], ['audio_sessions.id'], name='transcripts_audio_session_id_fkey'),
        ForeignKeyConstraint(['branch_id'], ['branches.id'], name='transcripts_branch_id_fkey'),
        ForeignKeyConstraint(['client_id'], ['clients.id'], name='transcripts_client_id_fkey'),
        ForeignKeyConstraint(['employee_id'], ['employees.id'], name='transcripts_employee_id_fkey'),
        ForeignKeyConstraint(['run_id'], ['sim_runs.id'], ondelete='CASCADE', name='transcripts_run_id_fkey'),
        ForeignKeyConstraint(['signal_id'], ['signals.id'], name='transcripts_signal_id_fkey'),
        PrimaryKeyConstraint('id', name='transcripts_pkey'),
        {'comment': 'Готовые текстовые транскрипты диалогов (ДТЗ FR-1.1, FR-4.1): '
                'JSON/TXT файлами и по REST'}
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True, start=1, increment=1, minvalue=1, maxvalue=9223372036854775807, cycle=False, cache=1), primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    format: Mapped[str] = mapped_column(Text, nullable=False)
    turns: Mapped[dict] = mapped_column(JSONB, nullable=False)
    turns_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text('0'))
    analyses: Mapped[list[str]] = mapped_column(ARRAY(Text()), nullable=False, server_default=text("'{client_signal,employee_quality}'::text[]"))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'received'::text"))
    received_at: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False, server_default=text('now()'))
    received_sim: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False, server_default=text('now()'))
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False, server_default=text('now()'))
    public_id: Mapped[Optional[str]] = mapped_column(Text, Computed("('TR-'::text || lpad((id)::text, 6, '0'::text))", persisted=True))
    filename: Mapped[Optional[str]] = mapped_column(Text)
    branch_id: Mapped[Optional[int]] = mapped_column(Integer)
    employee_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    client_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    contact_hints: Mapped[Optional[dict]] = mapped_column(JSONB)
    deal_product: Mapped[Optional[str]] = mapped_column(Text)
    started_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(True))
    geo: Mapped[Optional[dict]] = mapped_column(JSONB)
    signal_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    audio_session_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    report: Mapped[Optional[dict]] = mapped_column(JSONB)
    error: Mapped[Optional[str]] = mapped_column(Text)
    analyzed_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(True))

    audio_sessions_transcript: Mapped[list['AudioSessions']] = relationship('AudioSessions', foreign_keys='[AudioSessions.transcript_id]', back_populates='transcript')
    signals_transcript: Mapped[list['Signals']] = relationship('Signals', foreign_keys='[Signals.transcript_id]', back_populates='transcript')
    audio_session: Mapped[Optional['AudioSessions']] = relationship('AudioSessions', foreign_keys=[audio_session_id], back_populates='transcripts_audio_session')
    branch: Mapped[Optional['Branches']] = relationship('Branches', back_populates='transcripts')
    client: Mapped[Optional['Clients']] = relationship('Clients', back_populates='transcripts')
    employee: Mapped[Optional['Employees']] = relationship('Employees', back_populates='transcripts')
    run: Mapped['SimRuns'] = relationship('SimRuns', back_populates='transcripts')
    signal: Mapped[Optional['Signals']] = relationship('Signals', foreign_keys=[signal_id], back_populates='transcripts_signal')
    compliance_alerts: Mapped[list['ComplianceAlerts']] = relationship('ComplianceAlerts', back_populates='transcript')


class AgentSteps(Base):
    __tablename__ = 'agent_steps'
    __table_args__ = (
        CheckConstraint("status = ANY (ARRAY['ok'::text, 'retry'::text, 'fallback'::text, 'error'::text, 'skipped'::text])", name='agent_steps_status_check'),
        ForeignKeyConstraint(['run_id'], ['agent_runs.id'], ondelete='CASCADE', name='agent_steps_run_id_fkey'),
        PrimaryKeyConstraint('id', name='agent_steps_pkey'),
        UniqueConstraint('run_id', 'seq', name='agent_steps_run_id_seq_key')
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True, start=1, increment=1, minvalue=1, maxvalue=9223372036854775807, cycle=False, cache=1), primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    node: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    tool_calls: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text('0'))
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text('0'))
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text('0'))
    started_at: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False, server_default=text('now()'))
    input: Mapped[Optional[dict]] = mapped_column(JSONB)
    output: Mapped[Optional[dict]] = mapped_column(JSONB)
    prompt: Mapped[Optional[str]] = mapped_column(Text)
    response_raw: Mapped[Optional[str]] = mapped_column(Text)
    reasoning: Mapped[Optional[str]] = mapped_column(Text)
    model: Mapped[Optional[str]] = mapped_column(Text)
    finished_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(True))

    run: Mapped['AgentRuns'] = relationship('AgentRuns', back_populates='agent_steps')


class BenchCases(Base):
    __tablename__ = 'bench_cases'
    __table_args__ = (
        ForeignKeyConstraint(['channel_code'], ['channels.code'], name='bench_cases_channel_code_fkey'),
        ForeignKeyConstraint(['dataset_id'], ['bench_datasets.id'], ondelete='CASCADE', name='bench_cases_dataset_id_fkey'),
        ForeignKeyConstraint(['segment_code'], ['segments.code'], name='bench_cases_segment_code_fkey'),
        PrimaryKeyConstraint('id', name='bench_cases_pkey')
    )

    id: Mapped[int] = mapped_column(Integer, Identity(always=True, start=1, increment=1, minvalue=1, maxvalue=2147483647, cycle=False, cache=1), primary_key=True, autoincrement=True)
    dataset_id: Mapped[int] = mapped_column(Integer, nullable=False)
    channel_code: Mapped[str] = mapped_column(Text, nullable=False)
    text_: Mapped[str] = mapped_column('text', Text, nullable=False)
    gold: Mapped[dict] = mapped_column(JSONB, nullable=False)
    tags: Mapped[list[str]] = mapped_column(ARRAY(Text()), nullable=False, server_default=text("'{}'::text[]"))
    segment_code: Mapped[Optional[str]] = mapped_column(Text)

    channels: Mapped['Channels'] = relationship('Channels', back_populates='bench_cases')
    dataset: Mapped['BenchDatasets'] = relationship('BenchDatasets', back_populates='bench_cases')
    segments: Mapped[Optional['Segments']] = relationship('Segments', back_populates='bench_cases')
    bench_results: Mapped[list['BenchResults']] = relationship('BenchResults', back_populates='case')


class BenchRuns(Base):
    __tablename__ = 'bench_runs'
    __table_args__ = (
        CheckConstraint("status = ANY (ARRAY['queued'::text, 'running'::text, 'done'::text, 'failed'::text, 'cancelled'::text])", name='bench_runs_status_check'),
        ForeignKeyConstraint(['dataset_id'], ['bench_datasets.id'], name='bench_runs_dataset_id_fkey'),
        ForeignKeyConstraint(['llm_profile_id'], ['llm_profiles.id'], name='bench_runs_llm_profile_id_fkey'),
        PrimaryKeyConstraint('id', name='bench_runs_pkey')
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True, start=1, increment=1, minvalue=1, maxvalue=9223372036854775807, cycle=False, cache=1), primary_key=True, autoincrement=True)
    dataset_id: Mapped[int] = mapped_column(Integer, nullable=False)
    llm_profile_id: Mapped[int] = mapped_column(Integer, nullable=False)
    prompt_version: Mapped[str] = mapped_column(Text, nullable=False)
    repeats: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text('1'))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'queued'::text"))
    seed: Mapped[Optional[int]] = mapped_column(BigInteger)
    metrics: Mapped[Optional[dict]] = mapped_column(JSONB)
    started_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(True))
    finished_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(True))
    error: Mapped[Optional[str]] = mapped_column(Text)

    dataset: Mapped['BenchDatasets'] = relationship('BenchDatasets', back_populates='bench_runs')
    llm_profile: Mapped['LlmProfiles'] = relationship('LlmProfiles', back_populates='bench_runs')
    bench_results: Mapped[list['BenchResults']] = relationship('BenchResults', back_populates='run')


class EconomicsSettings(Base):
    __tablename__ = 'economics_settings'
    __table_args__ = (
        CheckConstraint("calibration_mode = ANY (ARRAY['manual'::text, 'simulated'::text])", name='economics_settings_calibration_mode_check'),
        CheckConstraint('id = 1', name='economics_settings_id_check'),
        ForeignKeyConstraint(['fallback_rate_code'], ['dcltv_rates.code'], deferrable=True, initially='DEFERRED', name='economics_settings_fallback_rate_code_fkey'),
        PrimaryKeyConstraint('id', name='economics_settings_pkey')
    )

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, server_default=text('1'))
    detractor_share: Mapped[decimal.Decimal] = mapped_column(Numeric(5, 4), nullable=False, server_default=text('0.10'))
    no_return_share: Mapped[decimal.Decimal] = mapped_column(Numeric(5, 4), nullable=False, server_default=text('0.50'))
    retention_factors: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text('\'{"open": 0, "churned": 0, "rejected": 0, "closed_late": 0.5, "closed_in_sla": 0.9, "closed_with_regression": 0.3, "closed_in_sla_with_gift": 1.0}\'::jsonb'))
    calibration_mode: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'manual'::text"))
    fallback_rate_code: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'bank_average'::text"))
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False, server_default=text('now()'))
    misselling_case_cost_rub: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text('4050'))
    map_zone_thresholds: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text('\'{"red": 0.5, "yellow": 0.25, "copilot_weight": 0.5, "window_sim_hours": 24}\'::jsonb'))

    dcltv_rates: Mapped['DcltvRates'] = relationship('DcltvRates', back_populates='economics_settings')


class ErrorCodes(Base):
    __tablename__ = 'error_codes'
    __table_args__ = (
        CheckConstraint("default_complexity = ANY (ARRAY['easy'::text, 'medium'::text, 'hard'::text])", name='error_codes_default_complexity_check'),
        CheckConstraint("default_criticality = ANY (ARRAY['low'::text, 'medium'::text, 'high'::text])", name='error_codes_default_criticality_check'),
        ForeignKeyConstraint(['product_code'], ['products.code'], name='error_codes_product_code_fkey'),
        ForeignKeyConstraint(['system_code'], ['systems.code'], name='error_codes_system_code_fkey'),
        PrimaryKeyConstraint('code', name='error_codes_pkey')
    )

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    system_code: Mapped[str] = mapped_column(Text, nullable=False)
    title_ru: Mapped[str] = mapped_column(Text, nullable=False)
    default_complexity: Mapped[str] = mapped_column(Text, nullable=False)
    default_criticality: Mapped[str] = mapped_column(Text, nullable=False)
    client_visible: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text('true'))
    product_code: Mapped[Optional[str]] = mapped_column(Text)
    description_ru: Mapped[Optional[str]] = mapped_column(Text)

    faults: Mapped[list['Faults']] = relationship('Faults', back_populates='error_codes')
    incidents: Mapped[list['Incidents']] = relationship('Incidents', back_populates='error_codes')
    operations: Mapped[list['Operations']] = relationship('Operations', back_populates='error_codes')
    products: Mapped[Optional['Products']] = relationship('Products', back_populates='error_codes')
    systems: Mapped['Systems'] = relationship('Systems', back_populates='error_codes')
    business_rules: Mapped[list['BusinessRules']] = relationship('BusinessRules', back_populates='error_codes')
    system_logs: Mapped[list['SystemLogs']] = relationship('SystemLogs', back_populates='error_codes')


class IncidentSignals(Base):
    __tablename__ = 'incident_signals'
    __table_args__ = (
        CheckConstraint("link_type = ANY (ARRAY['primary'::text, 'linked'::text, 'duplicate'::text])", name='incident_signals_link_type_check'),
        ForeignKeyConstraint(['incident_id'], ['incidents.id'], ondelete='CASCADE', name='incident_signals_incident_id_fkey'),
        ForeignKeyConstraint(['signal_id'], ['signals.id'], ondelete='CASCADE', name='incident_signals_signal_id_fkey'),
        PrimaryKeyConstraint('incident_id', 'signal_id', name='incident_signals_pkey')
    )

    incident_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    signal_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    link_type: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'primary'::text"))
    linked_sim: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False)

    incident: Mapped['Incidents'] = relationship('Incidents', back_populates='incident_signals')
    signal: Mapped['Signals'] = relationship('Signals', back_populates='incident_signals')


class IncidentStatusHistory(Base):
    __tablename__ = 'incident_status_history'
    __table_args__ = (
        CheckConstraint("actor_type = ANY (ARRAY['agent'::text, 'human'::text, 'team'::text, 'system'::text, 'behavior_model'::text])", name='incident_status_history_actor_type_check'),
        ForeignKeyConstraint(['incident_id'], ['incidents.id'], ondelete='CASCADE', name='incident_status_history_incident_id_fkey'),
        PrimaryKeyConstraint('id', name='incident_status_history_pkey')
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True, start=1, increment=1, minvalue=1, maxvalue=9223372036854775807, cycle=False, cache=1), primary_key=True, autoincrement=True)
    incident_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    to_status: Mapped[str] = mapped_column(Text, nullable=False)
    actor_type: Mapped[str] = mapped_column(Text, nullable=False)
    changed_sim: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False)
    changed_at: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False, server_default=text('now()'))
    from_status: Mapped[Optional[str]] = mapped_column(Text)
    actor_ref: Mapped[Optional[str]] = mapped_column(Text)
    reason: Mapped[Optional[str]] = mapped_column(Text)

    incident: Mapped['Incidents'] = relationship('Incidents', back_populates='incident_status_history')


class IngestSources(Base):
    __tablename__ = 'ingest_sources'
    __table_args__ = (
        CheckConstraint('interval_s >= 5', name='ingest_sources_interval_s_check'),
        CheckConstraint("kind = ANY (ARRAY['rest'::text, 'polling'::text, 'file'::text])", name='ingest_sources_kind_check'),
        ForeignKeyConstraint(['channel_code'], ['channels.code'], name='ingest_sources_channel_code_fkey'),
        PrimaryKeyConstraint('code', name='ingest_sources_pkey'),
        {'comment': 'Адаптеры источников сообщений (ДТЗ FR-1.2): REST, polling, файлы'}
    )

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    channel_code: Mapped[str] = mapped_column(Text, nullable=False)
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text('true'))
    interval_s: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text('10'))
    stats: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    is_external: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text('false'))
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False, server_default=text('now()'))
    last_polled_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(True))
    cursor: Mapped[Optional[str]] = mapped_column(Text)

    channels: Mapped['Channels'] = relationship('Channels', back_populates='ingest_sources')
    ingest_messages: Mapped[list['IngestMessages']] = relationship('IngestMessages', back_populates='ingest_sources')


class NotificationTemplates(Base):
    __tablename__ = 'notification_templates'
    __table_args__ = (
        ForeignKeyConstraint(['channel_code'], ['channels.code'], name='notification_templates_channel_code_fkey'),
        ForeignKeyConstraint(['segment_code'], ['segments.code'], name='notification_templates_segment_code_fkey'),
        PrimaryKeyConstraint('id', name='notification_templates_pkey')
    )

    id: Mapped[int] = mapped_column(Integer, Identity(always=True, start=1, increment=1, minvalue=1, maxvalue=2147483647, cycle=False, cache=1), primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(Text, nullable=False)
    channel_code: Mapped[str] = mapped_column(Text, nullable=False)
    lang: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'ru'::text"))
    body: Mapped[str] = mapped_column(Text, nullable=False)
    variables: Mapped[list[str]] = mapped_column(ARRAY(Text()), nullable=False, server_default=text("'{}'::text[]"))
    segment_code: Mapped[Optional[str]] = mapped_column(Text)
    subject: Mapped[Optional[str]] = mapped_column(Text)

    channels: Mapped['Channels'] = relationship('Channels', back_populates='notification_templates')
    segments: Mapped[Optional['Segments']] = relationship('Segments', back_populates='notification_templates')


class ProductLines(Base):
    __tablename__ = 'product_lines'
    __table_args__ = (
        ForeignKeyConstraint(['owner_team_code'], ['teams.code'], name='product_lines_owner_team_code_fkey'),
        ForeignKeyConstraint(['rate_code'], ['dcltv_rates.code'], name='product_lines_rate_code_fkey'),
        PrimaryKeyConstraint('code', name='product_lines_pkey'),
        {'comment': '15 продуктовых направлений ЕТЗ; сид из data/product_lines.yaml '
                '(T-240)'}
    )

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    name_ru: Mapped[str] = mapped_column(Text, nullable=False)
    name_en: Mapped[str] = mapped_column(Text, nullable=False)
    rate_code: Mapped[str] = mapped_column(Text, nullable=False)
    owner_team_code: Mapped[str] = mapped_column(Text, nullable=False)
    owner_is_proxy: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text('false'))
    product_codes: Mapped[list[str]] = mapped_column(ARRAY(Text()), nullable=False, server_default=text("'{}'::text[]"))
    sort_order: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text('0'))

    signals: Mapped[list['Signals']] = relationship('Signals', back_populates='product_lines')
    teams: Mapped['Teams'] = relationship('Teams', back_populates='product_lines')
    dcltv_rates: Mapped['DcltvRates'] = relationship('DcltvRates', back_populates='product_lines')
    product_signal_history: Mapped[list['ProductSignalHistory']] = relationship('ProductSignalHistory', back_populates='product_lines')


class Regions(Base):
    __tablename__ = 'regions'
    __table_args__ = (
        CheckConstraint('population > 0', name='regions_population_check'),
        ForeignKeyConstraint(['district_code'], ['federal_districts.code'], name='regions_district_code_fkey'),
        PrimaryKeyConstraint('code', name='regions_pkey'),
        {'comment': 'Все субъекты РФ; источник и лицензия — data/README.md'}
    )

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    name_ru: Mapped[str] = mapped_column(Text, nullable=False)
    name_en: Mapped[str] = mapped_column(Text, nullable=False)
    district_code: Mapped[str] = mapped_column(Text, nullable=False)
    population: Mapped[int] = mapped_column(Integer, nullable=False)
    centroid_lat: Mapped[decimal.Decimal] = mapped_column(Numeric(8, 5), nullable=False)
    centroid_lon: Mapped[decimal.Decimal] = mapped_column(Numeric(8, 5), nullable=False)
    svg_path_id: Mapped[Optional[str]] = mapped_column(Text)
    okato: Mapped[Optional[str]] = mapped_column(Text)

    incidents: Mapped[list['Incidents']] = relationship('Incidents', back_populates='regions')
    federal_districts: Mapped['FederalDistricts'] = relationship('FederalDistricts', back_populates='regions')
    branch_network_history: Mapped[list['BranchNetworkHistory']] = relationship('BranchNetworkHistory', back_populates='regions')
    cities: Mapped[list['Cities']] = relationship('Cities', back_populates='regions')
    branches: Mapped[list['Branches']] = relationship('Branches', back_populates='regions')
    clients: Mapped[list['Clients']] = relationship('Clients', back_populates='regions')


class SegmentPsychotypeMix(Base):
    __tablename__ = 'segment_psychotype_mix'
    __table_args__ = (
        CheckConstraint('share >= 0::numeric AND share <= 1::numeric', name='segment_psychotype_mix_share_check'),
        ForeignKeyConstraint(['psychotype_code'], ['psychotypes.code'], name='segment_psychotype_mix_psychotype_code_fkey'),
        ForeignKeyConstraint(['segment_code'], ['segments.code'], name='segment_psychotype_mix_segment_code_fkey'),
        PrimaryKeyConstraint('segment_code', 'psychotype_code', name='segment_psychotype_mix_pkey')
    )

    segment_code: Mapped[str] = mapped_column(Text, primary_key=True)
    psychotype_code: Mapped[str] = mapped_column(Text, primary_key=True)
    share: Mapped[decimal.Decimal] = mapped_column(Numeric(5, 4), nullable=False)

    psychotypes: Mapped['Psychotypes'] = relationship('Psychotypes', back_populates='segment_psychotype_mix')
    segments: Mapped['Segments'] = relationship('Segments', back_populates='segment_psychotype_mix')


class SimRuns(Base):
    __tablename__ = 'sim_runs'
    __table_args__ = (
        CheckConstraint("kind = ANY (ARRAY['baseline'::text, 'free'::text, 'scenario'::text, 'live'::text])", name='sim_runs_kind_check'),
        CheckConstraint("reset_mode = ANY (ARRAY['none'::text, 'counters'::text, 'baseline'::text])", name='sim_runs_reset_mode_check'),
        CheckConstraint("status = ANY (ARRAY['running'::text, 'paused'::text, 'interrupted'::text, 'completed'::text, 'stopped'::text, 'archived'::text])", name='sim_runs_status_check'),
        ForeignKeyConstraint(['llm_profile_id'], ['llm_profiles.id'], name='sim_runs_llm_profile_fk'),
        ForeignKeyConstraint(['parent_run_id'], ['sim_runs.id'], name='sim_runs_parent_run_id_fkey'),
        ForeignKeyConstraint(['scenario_id'], ['scenarios.id'], name='sim_runs_scenario_fk'),
        PrimaryKeyConstraint('id', name='sim_runs_pkey'),
        {'comment': 'ТЗ 4.6: история запусков эмуляции; run_id в таблицах данных '
                'ссылается сюда'}
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True, start=1, increment=1, minvalue=1, maxvalue=9223372036854775807, cycle=False, cache=1), primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    seed: Mapped[int] = mapped_column(BigInteger, nullable=False)
    settings_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'running'::text"))
    started_sim: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False)
    started_at: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False, server_default=text('now()'))
    resumed_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text('0'))
    scenario_id: Mapped[Optional[str]] = mapped_column(Text)
    llm_profile_id: Mapped[Optional[int]] = mapped_column(Integer)
    reset_mode: Mapped[Optional[str]] = mapped_column(Text)
    parent_run_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    finished_sim: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(True))
    finished_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(True))
    summary: Mapped[Optional[dict]] = mapped_column(JSONB)
    export_path: Mapped[Optional[str]] = mapped_column(Text)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    public_id: Mapped[Optional[str]] = mapped_column(Text, Computed("('SR-'::text || lpad((id)::text, 4, '0'::text))", persisted=True))

    agent_runs: Mapped[list['AgentRuns']] = relationship('AgentRuns', back_populates='sim_run')
    audio_sessions: Mapped[list['AudioSessions']] = relationship('AudioSessions', back_populates='run')
    external_posts: Mapped[list['ExternalPosts']] = relationship('ExternalPosts', back_populates='run')
    faults: Mapped[list['Faults']] = relationship('Faults', back_populates='run')
    incidents: Mapped[list['Incidents']] = relationship('Incidents', back_populates='run')
    operations: Mapped[list['Operations']] = relationship('Operations', back_populates='run')
    signals: Mapped[list['Signals']] = relationship('Signals', back_populates='run')
    transcripts: Mapped[list['Transcripts']] = relationship('Transcripts', back_populates='run')
    llm_profile: Mapped[Optional['LlmProfiles']] = relationship('LlmProfiles', back_populates='sim_runs')
    parent_run: Mapped[Optional['SimRuns']] = relationship('SimRuns', remote_side=[id], back_populates='parent_run_reverse')
    parent_run_reverse: Mapped[list['SimRuns']] = relationship('SimRuns', remote_side=[parent_run_id], back_populates='parent_run')
    scenario: Mapped[Optional['Scenarios']] = relationship('Scenarios', back_populates='sim_runs')
    external_replies: Mapped[list['ExternalReplies']] = relationship('ExternalReplies', back_populates='run')
    followups: Mapped[list['Followups']] = relationship('Followups', back_populates='sim_run')
    incident_artifacts: Mapped[list['IncidentArtifacts']] = relationship('IncidentArtifacts', back_populates='run')
    incident_economics: Mapped[list['IncidentEconomics']] = relationship('IncidentEconomics', back_populates='run')
    ingest_messages: Mapped[list['IngestMessages']] = relationship('IngestMessages', back_populates='run')
    personal_chat_sessions: Mapped[list['PersonalChatSessions']] = relationship('PersonalChatSessions', back_populates='run')
    sim_events: Mapped[list['SimEvents']] = relationship('SimEvents', back_populates='run')
    sim_state: Mapped[list['SimState']] = relationship('SimState', back_populates='current_run')
    system_logs: Mapped[list['SystemLogs']] = relationship('SystemLogs', back_populates='run')
    team_actions: Mapped[list['TeamActions']] = relationship('TeamActions', back_populates='run')
    rule_evaluations: Mapped[list['RuleEvaluations']] = relationship('RuleEvaluations', back_populates='run')
    churn_events: Mapped[list['ChurnEvents']] = relationship('ChurnEvents', back_populates='run')
    client_states: Mapped[list['ClientStates']] = relationship('ClientStates', back_populates='run')
    notifications: Mapped[list['Notifications']] = relationship('Notifications', back_populates='run')
    tasks: Mapped[list['Tasks']] = relationship('Tasks', back_populates='run')
    client_reactions: Mapped[list['ClientReactions']] = relationship('ClientReactions', back_populates='run')
    human_decisions: Mapped[list['HumanDecisions']] = relationship('HumanDecisions', back_populates='sim_run')
    escalations: Mapped[list['Escalations']] = relationship('Escalations', back_populates='run')
    ledger_entries: Mapped[list['LedgerEntries']] = relationship('LedgerEntries', back_populates='run')
    financial_evidence: Mapped[list['FinancialEvidence']] = relationship('FinancialEvidence', back_populates='run')


class SttMetrics(Base):
    __tablename__ = 'stt_metrics'
    __table_args__ = (
        ForeignKeyConstraint(['session_id'], ['audio_sessions.id'], ondelete='CASCADE', name='stt_metrics_session_id_fkey'),
        PrimaryKeyConstraint('id', name='stt_metrics_pkey')
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True, start=1, increment=1, minvalue=1, maxvalue=9223372036854775807, cycle=False, cache=1), primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False, server_default=text('now()'))
    session_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    model: Mapped[Optional[str]] = mapped_column(Text)
    partial_latency_ms: Mapped[Optional[int]] = mapped_column(Integer)
    final_latency_ms: Mapped[Optional[int]] = mapped_column(Integer)
    wer: Mapped[Optional[decimal.Decimal]] = mapped_column(Numeric(5, 4))
    cpu_ms: Mapped[Optional[int]] = mapped_column(Integer)
    audio_seconds: Mapped[Optional[decimal.Decimal]] = mapped_column(Numeric(8, 2))

    session: Mapped[Optional['AudioSessions']] = relationship('AudioSessions', back_populates='stt_metrics')


class Tariffs(Base):
    __tablename__ = 'tariffs'
    __table_args__ = (
        CheckConstraint("method = ANY (ARRAY['qr_sbp'::text, 'card'::text, 'transfer'::text, 'cash'::text, 'online'::text, 'any'::text])", name='tariffs_method_check'),
        ForeignKeyConstraint(['product_code'], ['products.code'], name='tariffs_product_code_fkey'),
        PrimaryKeyConstraint('id', name='tariffs_pkey'),
        UniqueConstraint('product_code', 'operation_kind', 'method', name='tariffs_product_code_operation_kind_method_key'),
        {'comment': 'Тарифы Mock-АБС; QR/СБП для физлиц — 0 ₽ (основание правила '
                'RULE-QR-FEE-001)'}
    )

    id: Mapped[int] = mapped_column(Integer, Identity(always=True, start=1, increment=1, minvalue=1, maxvalue=2147483647, cycle=False, cache=1), primary_key=True, autoincrement=True)
    product_code: Mapped[str] = mapped_column(Text, nullable=False)
    operation_kind: Mapped[str] = mapped_column(Text, nullable=False)
    method: Mapped[str] = mapped_column(Text, nullable=False)
    fee_pct: Mapped[decimal.Decimal] = mapped_column(Numeric(6, 4), nullable=False, server_default=text('0'))
    fee_fixed: Mapped[decimal.Decimal] = mapped_column(Numeric(14, 2), nullable=False, server_default=text('0'))
    free_limit_rub: Mapped[Optional[decimal.Decimal]] = mapped_column(Numeric(14, 2))
    note_ru: Mapped[Optional[str]] = mapped_column(Text)

    products: Mapped['Products'] = relationship('Products', back_populates='tariffs_')


t_team_systems = Table(
    'team_systems', Base.metadata,
    Column('team_code', Text, primary_key=True),
    Column('system_code', Text, primary_key=True),
    ForeignKeyConstraint(['system_code'], ['systems.code'], name='team_systems_system_code_fkey'),
    ForeignKeyConstraint(['team_code'], ['teams.code'], name='team_systems_team_code_fkey'),
    PrimaryKeyConstraint('team_code', 'system_code', name='team_systems_pkey')
)


class Utterances(Base):
    __tablename__ = 'utterances'
    __table_args__ = (
        CheckConstraint("speaker = ANY (ARRAY['employee'::text, 'client'::text, 'unknown'::text])", name='utterances_speaker_check'),
        CheckConstraint("speaker_source = ANY (ARRAY['channel'::text, 'manual'::text, 'llm'::text, 'transcript'::text])", name='utterances_speaker_source_check'),
        ForeignKeyConstraint(['session_id'], ['audio_sessions.id'], ondelete='CASCADE', name='utterances_session_id_fkey'),
        PrimaryKeyConstraint('id', name='utterances_pkey'),
        UniqueConstraint('session_id', 'seq', name='utterances_session_id_seq_key')
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True, start=1, increment=1, minvalue=1, maxvalue=9223372036854775807, cycle=False, cache=1), primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    speaker: Mapped[str] = mapped_column(Text, nullable=False)
    speaker_confidence: Mapped[decimal.Decimal] = mapped_column(Numeric(4, 3), nullable=False, server_default=text('1'))
    speaker_source: Mapped[str] = mapped_column(Text, nullable=False)
    text_: Mapped[str] = mapped_column('text', Text, nullable=False)
    t0_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    t1_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    is_final: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text('true'))
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False, server_default=text('now()'))
    stt_confidence: Mapped[Optional[decimal.Decimal]] = mapped_column(Numeric(4, 3))
    words: Mapped[Optional[dict]] = mapped_column(JSONB)
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer)

    session: Mapped['AudioSessions'] = relationship('AudioSessions', back_populates='utterances')
    compliance_triggers: Mapped['ComplianceTriggers'] = relationship('ComplianceTriggers', uselist=False, back_populates='utterance')


class BenchResults(Base):
    __tablename__ = 'bench_results'
    __table_args__ = (
        ForeignKeyConstraint(['case_id'], ['bench_cases.id'], name='bench_results_case_id_fkey'),
        ForeignKeyConstraint(['run_id'], ['bench_runs.id'], ondelete='CASCADE', name='bench_results_run_id_fkey'),
        PrimaryKeyConstraint('id', name='bench_results_pkey'),
        UniqueConstraint('run_id', 'case_id', 'repeat_no', name='bench_results_run_id_case_id_repeat_no_key')
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True, start=1, increment=1, minvalue=1, maxvalue=9223372036854775807, cycle=False, cache=1), primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    case_id: Mapped[int] = mapped_column(Integer, nullable=False)
    repeat_no: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text('1'))
    predicted: Mapped[dict] = mapped_column(JSONB, nullable=False)
    correct: Mapped[dict] = mapped_column(JSONB, nullable=False)
    json_valid_first_try: Mapped[bool] = mapped_column(Boolean, nullable=False)
    retries: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text('0'))
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text('0'))
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text('0'))
    fallback_mock: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text('false'))

    case: Mapped['BenchCases'] = relationship('BenchCases', back_populates='bench_results')
    run: Mapped['BenchRuns'] = relationship('BenchRuns', back_populates='bench_results')


class BranchNetworkHistory(Base):
    __tablename__ = 'branch_network_history'
    __table_args__ = (
        ForeignKeyConstraint(['region_code'], ['regions.code'], name='branch_network_history_region_code_fkey'),
        PrimaryKeyConstraint('id', name='branch_network_history_pkey'),
        UniqueConstraint('month', 'region_code', name='branch_network_history_month_region_code_key')
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True, start=1, increment=1, minvalue=1, maxvalue=9223372036854775807, cycle=False, cache=1), primary_key=True, autoincrement=True)
    month: Mapped[datetime.date] = mapped_column(Date, nullable=False)
    region_code: Mapped[str] = mapped_column(Text, nullable=False)
    open_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text('0'))
    closed_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text('0'))
    opened_in_month: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text('0'))
    closed_in_month: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text('0'))

    regions: Mapped['Regions'] = relationship('Regions', back_populates='branch_network_history')


class BusinessRules(Base):
    __tablename__ = 'business_rules'
    __table_args__ = (
        CheckConstraint("action = ANY (ARRAY['refund_fee'::text, 'propose_hitl'::text, 'notify_only'::text, 'suppress_duplicates'::text])", name='business_rules_action_check'),
        ForeignKeyConstraint(['error_code'], ['error_codes.code'], name='business_rules_error_code_fkey'),
        ForeignKeyConstraint(['owner_team_code'], ['teams.code'], name='business_rules_owner_team_code_fkey'),
        PrimaryKeyConstraint('code', name='business_rules_pkey'),
        {'comment': 'Детерминированные правила узла check_rules; деньги двигаются '
                'только при matched'}
    )

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    name_ru: Mapped[str] = mapped_column(Text, nullable=False)
    name_en: Mapped[str] = mapped_column(Text, nullable=False)
    condition: Mapped[dict] = mapped_column(JSONB, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    limits: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    owner_team_code: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text('true'))
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text('1'))
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False, server_default=text('now()'))
    error_code: Mapped[Optional[str]] = mapped_column(Text)

    error_codes: Mapped[Optional['ErrorCodes']] = relationship('ErrorCodes', back_populates='business_rules')
    teams: Mapped['Teams'] = relationship('Teams', back_populates='business_rules')
    rule_evaluations: Mapped[list['RuleEvaluations']] = relationship('RuleEvaluations', back_populates='business_rules')


class Cities(Base):
    __tablename__ = 'cities'
    __table_args__ = (
        CheckConstraint('population > 0', name='cities_population_check'),
        ForeignKeyConstraint(['region_code'], ['regions.code'], name='cities_region_code_fkey'),
        PrimaryKeyConstraint('id', name='cities_pkey')
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    region_code: Mapped[str] = mapped_column(Text, nullable=False)
    name_ru: Mapped[str] = mapped_column(Text, nullable=False)
    name_en: Mapped[str] = mapped_column(Text, nullable=False)
    population: Mapped[int] = mapped_column(Integer, nullable=False)
    lat: Mapped[decimal.Decimal] = mapped_column(Numeric(8, 5), nullable=False)
    lon: Mapped[decimal.Decimal] = mapped_column(Numeric(8, 5), nullable=False)
    is_capital: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text('false'))

    regions: Mapped['Regions'] = relationship('Regions', back_populates='cities')
    branches: Mapped[list['Branches']] = relationship('Branches', back_populates='city')
    clients: Mapped[list['Clients']] = relationship('Clients', back_populates='city')


class ComplianceTriggers(Base):
    __tablename__ = 'compliance_triggers'
    __table_args__ = (
        CheckConstraint("detected_by = ANY (ARRAY['rules'::text, 'llm'::text, 'both'::text])", name='compliance_triggers_detected_by_check'),
        CheckConstraint("status = ANY (ARRAY['preliminary'::text, 'confirmed'::text, 'dismissed'::text])", name='compliance_triggers_status_check'),
        ForeignKeyConstraint(['agent_run_id'], ['agent_runs.id'], name='compliance_triggers_agent_run_id_fkey'),
        ForeignKeyConstraint(['pattern_code'], ['misselling_patterns.code'], name='compliance_triggers_pattern_code_fkey'),
        ForeignKeyConstraint(['session_id'], ['audio_sessions.id'], ondelete='CASCADE', name='compliance_triggers_session_id_fkey'),
        ForeignKeyConstraint(['utterance_id'], ['utterances.id'], ondelete='CASCADE', name='compliance_triggers_utterance_id_fkey'),
        PrimaryKeyConstraint('id', name='compliance_triggers_pkey'),
        UniqueConstraint('utterance_id', name='compliance_triggers_utterance_id_key')
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True, start=1, increment=1, minvalue=1, maxvalue=9223372036854775807, cycle=False, cache=1), primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    utterance_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    pattern_code: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[decimal.Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    quote: Mapped[str] = mapped_column(Text, nullable=False)
    detected_by: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'preliminary'::text"))
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False, server_default=text('now()'))
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False, server_default=text('now()'))
    explanation_ru: Mapped[Optional[str]] = mapped_column(Text)
    agent_run_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer)
    recommendation_ru: Mapped[Optional[str]] = mapped_column(Text)
    fact_check: Mapped[Optional[dict]] = mapped_column(JSONB)

    agent_run: Mapped[Optional['AgentRuns']] = relationship('AgentRuns', back_populates='compliance_triggers')
    misselling_patterns: Mapped['MissellingPatterns'] = relationship('MissellingPatterns', back_populates='compliance_triggers')
    session: Mapped['AudioSessions'] = relationship('AudioSessions', back_populates='compliance_triggers')
    utterance: Mapped['Utterances'] = relationship('Utterances', back_populates='compliance_triggers')


class ExternalReplies(Base):
    __tablename__ = 'external_replies'
    __table_args__ = (
        CheckConstraint("author = ANY (ARRAY['agent'::text, 'human'::text, 'client_twin'::text])", name='external_replies_author_check'),
        CheckConstraint("llm_source = ANY (ARRAY['live'::text, 'replay'::text, 'mock'::text])", name='external_replies_llm_source_check'),
        ForeignKeyConstraint(['agent_run_id'], ['agent_runs.id'], name='external_replies_agent_run_id_fkey'),
        ForeignKeyConstraint(['incident_id'], ['incidents.id'], name='external_replies_incident_id_fkey'),
        ForeignKeyConstraint(['post_id'], ['external_posts.id'], ondelete='CASCADE', name='external_replies_post_id_fkey'),
        ForeignKeyConstraint(['run_id'], ['sim_runs.id'], ondelete='CASCADE', name='external_replies_run_id_fkey'),
        PrimaryKeyConstraint('id', name='external_replies_pkey')
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True, start=1, increment=1, minvalue=1, maxvalue=9223372036854775807, cycle=False, cache=1), primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    post_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    author: Mapped[str] = mapped_column(Text, nullable=False)
    text_: Mapped[str] = mapped_column('text', Text, nullable=False)
    published_at: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False, server_default=text('now()'))
    incident_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    agent_run_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer)
    llm_source: Mapped[Optional[str]] = mapped_column(Text)

    agent_run: Mapped[Optional['AgentRuns']] = relationship('AgentRuns', back_populates='external_replies')
    incident: Mapped[Optional['Incidents']] = relationship('Incidents', back_populates='external_replies')
    post: Mapped['ExternalPosts'] = relationship('ExternalPosts', back_populates='external_replies')
    run: Mapped['SimRuns'] = relationship('SimRuns', back_populates='external_replies')


class Followups(Base):
    __tablename__ = 'followups'
    __table_args__ = (
        CheckConstraint("status = ANY (ARRAY['scheduled'::text, 'fired'::text, 'cancelled'::text])", name='followups_status_check'),
        ForeignKeyConstraint(['agent_run_id'], ['agent_runs.id'], name='followups_agent_run_id_fkey'),
        ForeignKeyConstraint(['incident_id'], ['incidents.id'], name='followups_incident_id_fkey'),
        ForeignKeyConstraint(['signal_id'], ['signals.id'], name='followups_signal_id_fkey'),
        ForeignKeyConstraint(['sim_run_id'], ['sim_runs.id'], ondelete='CASCADE', name='followups_sim_run_id_fkey'),
        PrimaryKeyConstraint('id', name='followups_pkey')
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True, start=1, increment=1, minvalue=1, maxvalue=9223372036854775807, cycle=False, cache=1), primary_key=True, autoincrement=True)
    sim_run_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    wake_sim: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'scheduled'::text"))
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False, server_default=text('now()'))
    agent_run_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    signal_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    incident_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    public_id: Mapped[Optional[str]] = mapped_column(Text, Computed("('FUP-'::text || lpad((id)::text, 6, '0'::text))", persisted=True))

    agent_run: Mapped[Optional['AgentRuns']] = relationship('AgentRuns', back_populates='followups')
    incident: Mapped[Optional['Incidents']] = relationship('Incidents', back_populates='followups')
    signal: Mapped[Optional['Signals']] = relationship('Signals', back_populates='followups')
    sim_run: Mapped['SimRuns'] = relationship('SimRuns', back_populates='followups')


class IncidentArtifacts(Base):
    __tablename__ = 'incident_artifacts'
    __table_args__ = (
        CheckConstraint("generated_by = ANY (ARRAY['llm'::text, 'template'::text, 'human'::text])", name='incident_artifacts_generated_by_check'),
        CheckConstraint("kind = ANY (ARRAY['rca'::text, 'fix_decision'::text, 'progress_report'::text, 'release_note'::text, 'verification_report'::text, 'closure_review'::text])", name='incident_artifacts_kind_check'),
        ForeignKeyConstraint(['author_team'], ['teams.code'], name='incident_artifacts_author_team_fkey'),
        ForeignKeyConstraint(['incident_id'], ['incidents.id'], ondelete='CASCADE', name='incident_artifacts_incident_id_fkey'),
        ForeignKeyConstraint(['run_id'], ['sim_runs.id'], ondelete='CASCADE', name='incident_artifacts_run_id_fkey'),
        PrimaryKeyConstraint('id', name='incident_artifacts_pkey')
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True, start=1, increment=1, minvalue=1, maxvalue=9223372036854775807, cycle=False, cache=1), primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    incident_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    body_md: Mapped[str] = mapped_column(Text, nullable=False)
    meta: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    generated_by: Mapped[str] = mapped_column(Text, nullable=False)
    published_sim: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False, server_default=text('now()'))
    author_team: Mapped[Optional[str]] = mapped_column(Text)
    due_sim: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(True))

    teams: Mapped[Optional['Teams']] = relationship('Teams', back_populates='incident_artifacts')
    incident: Mapped['Incidents'] = relationship('Incidents', back_populates='incident_artifacts')
    run: Mapped['SimRuns'] = relationship('SimRuns', back_populates='incident_artifacts')


class IncidentEconomics(Base):
    __tablename__ = 'incident_economics'
    __table_args__ = (
        CheckConstraint("retention_source = ANY (ARRAY['manual'::text, 'simulated'::text])", name='incident_economics_retention_source_check'),
        ForeignKeyConstraint(['incident_id'], ['incidents.id'], ondelete='CASCADE', name='incident_economics_incident_id_fkey'),
        ForeignKeyConstraint(['rate_code'], ['dcltv_rates.code'], name='incident_economics_rate_code_fkey'),
        ForeignKeyConstraint(['run_id'], ['sim_runs.id'], ondelete='CASCADE', name='incident_economics_run_id_fkey'),
        PrimaryKeyConstraint('incident_id', name='incident_economics_pkey')
    )

    incident_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    run_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    affected_count: Mapped[int] = mapped_column(Integer, nullable=False)
    rate_code: Mapped[str] = mapped_column(Text, nullable=False)
    rate_rub: Mapped[decimal.Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    premium_addon_rub: Mapped[decimal.Decimal] = mapped_column(Numeric(12, 3), nullable=False, server_default=text('0'))
    detractor_share: Mapped[decimal.Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    no_return_share: Mapped[decimal.Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    potential_loss_rub: Mapped[decimal.Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    retention_factor: Mapped[decimal.Decimal] = mapped_column(Numeric(5, 4), nullable=False, server_default=text('0'))
    retention_source: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'manual'::text"))
    prevented_loss_rub: Mapped[decimal.Decimal] = mapped_column(Numeric(14, 2), nullable=False, server_default=text('0'))
    realized_loss_rub: Mapped[decimal.Decimal] = mapped_column(Numeric(14, 2), nullable=False, server_default=text('0'))
    breakdown: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    computed_sim: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False)
    computed_at: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False, server_default=text('now()'))
    refund_amount_rub: Mapped[decimal.Decimal] = mapped_column(Numeric(14, 2), nullable=False, server_default=text('0'))

    incident: Mapped['Incidents'] = relationship('Incidents', back_populates='incident_economics')
    dcltv_rates: Mapped['DcltvRates'] = relationship('DcltvRates', back_populates='incident_economics')
    run: Mapped['SimRuns'] = relationship('SimRuns', back_populates='incident_economics')


class IngestMessages(Base):
    __tablename__ = 'ingest_messages'
    __table_args__ = (
        CheckConstraint("status = ANY (ARRAY['accepted'::text, 'duplicate'::text, 'rejected'::text])", name='ingest_messages_status_check'),
        ForeignKeyConstraint(['run_id'], ['sim_runs.id'], ondelete='CASCADE', name='ingest_messages_run_id_fkey'),
        ForeignKeyConstraint(['signal_id'], ['signals.id'], name='ingest_messages_signal_id_fkey'),
        ForeignKeyConstraint(['source_code'], ['ingest_sources.code'], name='ingest_messages_source_code_fkey'),
        PrimaryKeyConstraint('id', name='ingest_messages_pkey'),
        UniqueConstraint('source_code', 'external_id', name='ingest_messages_source_code_external_id_key'),
        {'comment': 'Журнал приёма сообщений адаптерами: идемпотентность по '
                'external_id (ДТЗ FR-1.2–1.3)'}
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True, start=1, increment=1, minvalue=1, maxvalue=9223372036854775807, cycle=False, cache=1), primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_code: Mapped[str] = mapped_column(Text, nullable=False)
    external_id: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    received_at: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False, server_default=text('now()'))
    status: Mapped[str] = mapped_column(Text, nullable=False)
    signal_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    error: Mapped[Optional[str]] = mapped_column(Text)

    run: Mapped['SimRuns'] = relationship('SimRuns', back_populates='ingest_messages')
    signal: Mapped[Optional['Signals']] = relationship('Signals', back_populates='ingest_messages')
    ingest_sources: Mapped['IngestSources'] = relationship('IngestSources', back_populates='ingest_messages')


class PersonalChatSessions(Base):
    __tablename__ = 'personal_chat_sessions'
    __table_args__ = (
        ForeignKeyConstraint(['run_id'], ['sim_runs.id'], ondelete='CASCADE', name='personal_chat_sessions_run_id_fkey'),
        PrimaryKeyConstraint('id', name='personal_chat_sessions_pkey'),
        UniqueConstraint('token_hash', name='personal_chat_sessions_token_hash_key')
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True, start=1, increment=1, minvalue=1, maxvalue=9223372036854775807, cycle=False, cache=1), primary_key=True, autoincrement=True)
    token_hash: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False, server_default=text('now()'))
    run_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    last_message_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(True))

    run: Mapped[Optional['SimRuns']] = relationship('SimRuns', back_populates='personal_chat_sessions')
    personal_chat_messages: Mapped[list['PersonalChatMessages']] = relationship('PersonalChatMessages', back_populates='session')


class ProductSignalHistory(Base):
    __tablename__ = 'product_signal_history'
    __table_args__ = (
        ForeignKeyConstraint(['product_line_code'], ['product_lines.code'], name='product_signal_history_product_line_code_fkey'),
        PrimaryKeyConstraint('id', name='product_signal_history_pkey'),
        UniqueConstraint('product_line_code', 'month', name='product_signal_history_product_line_code_month_key')
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True, start=1, increment=1, minvalue=1, maxvalue=9223372036854775807, cycle=False, cache=1), primary_key=True, autoincrement=True)
    product_line_code: Mapped[str] = mapped_column(Text, nullable=False)
    month: Mapped[datetime.date] = mapped_column(Date, nullable=False)
    signal_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text('0'))
    negative_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text('0'))
    critical_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text('0'))
    by_source: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    loss_rub: Mapped[decimal.Decimal] = mapped_column(Numeric(14, 2), nullable=False, server_default=text('0'))
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text('false'))

    product_lines: Mapped['ProductLines'] = relationship('ProductLines', back_populates='product_signal_history')


class SimEvents(Base):
    __tablename__ = 'sim_events'
    __table_args__ = (
        ForeignKeyConstraint(['run_id'], ['sim_runs.id'], ondelete='CASCADE', name='sim_events_run_id_fkey'),
        PrimaryKeyConstraint('id', name='sim_events_pkey')
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True, start=1, increment=1, minvalue=1, maxvalue=9223372036854775807, cycle=False, cache=1), primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    sim_time: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False)
    real_time: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False, server_default=text('now()'))
    correlation_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, server_default=text('gen_random_uuid()'))
    scenario_id: Mapped[Optional[str]] = mapped_column(Text)

    run: Mapped['SimRuns'] = relationship('SimRuns', back_populates='sim_events')


class SimState(Base):
    __tablename__ = 'sim_state'
    __table_args__ = (
        CheckConstraint('id = 1', name='sim_state_id_check'),
        ForeignKeyConstraint(['current_run_id'], ['sim_runs.id'], name='sim_state_current_run_id_fkey'),
        PrimaryKeyConstraint('id', name='sim_state_pkey')
    )

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, server_default=text('1'))
    sim_time: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False)
    day_no: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text('1'))
    speed: Mapped[decimal.Decimal] = mapped_column(Numeric(8, 2), nullable=False, server_default=text('60'))
    running: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text('false'))
    seed: Mapped[int] = mapped_column(BigInteger, nullable=False)
    phase: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'morning'::text"))
    intensities: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False, server_default=text('now()'))
    current_run_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    rng_state: Mapped[Optional[dict]] = mapped_column(JSONB)
    last_tick_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(True))

    current_run: Mapped[Optional['SimRuns']] = relationship('SimRuns', back_populates='sim_state')


class SystemLogs(Base):
    __tablename__ = 'system_logs'
    __table_args__ = (
        CheckConstraint("level = ANY (ARRAY['INFO'::text, 'WARN'::text, 'ERROR'::text, 'FATAL'::text])", name='system_logs_level_check'),
        ForeignKeyConstraint(['affected_operation_id'], ['operations.id'], name='system_logs_affected_operation_id_fkey'),
        ForeignKeyConstraint(['error_code'], ['error_codes.code'], name='system_logs_error_code_fkey'),
        ForeignKeyConstraint(['fault_id'], ['faults.id'], name='system_logs_fault_id_fkey'),
        ForeignKeyConstraint(['run_id'], ['sim_runs.id'], ondelete='CASCADE', name='system_logs_run_id_fkey'),
        ForeignKeyConstraint(['system_code'], ['systems.code'], name='system_logs_system_code_fkey'),
        PrimaryKeyConstraint('id', name='system_logs_pkey')
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True, start=1, increment=1, minvalue=1, maxvalue=9223372036854775807, cycle=False, cache=1), primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    system_code: Mapped[str] = mapped_column(Text, nullable=False)
    level: Mapped[str] = mapped_column(Text, nullable=False)
    component: Mapped[str] = mapped_column(Text, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    logged_sim: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False, server_default=text('now()'))
    error_code: Mapped[Optional[str]] = mapped_column(Text)
    affected_operation_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    fault_id: Mapped[Optional[int]] = mapped_column(BigInteger)

    affected_operation: Mapped[Optional['Operations']] = relationship('Operations', back_populates='system_logs')
    error_codes: Mapped[Optional['ErrorCodes']] = relationship('ErrorCodes', back_populates='system_logs')
    fault: Mapped[Optional['Faults']] = relationship('Faults', back_populates='system_logs')
    run: Mapped['SimRuns'] = relationship('SimRuns', back_populates='system_logs')
    systems: Mapped['Systems'] = relationship('Systems', back_populates='system_logs')


class TeamActions(Base):
    __tablename__ = 'team_actions'
    __table_args__ = (
        CheckConstraint("action = ANY (ARRAY['take'::text, 'clarify'::text, 'rca'::text, 'fix_decision'::text, 'progress_report'::text, 'release'::text, 'verify'::text, 'close'::text, 'reassign'::text, 'escalate_ack'::text])", name='team_actions_action_check'),
        ForeignKeyConstraint(['incident_id'], ['incidents.id'], ondelete='CASCADE', name='team_actions_incident_id_fkey'),
        ForeignKeyConstraint(['run_id'], ['sim_runs.id'], ondelete='CASCADE', name='team_actions_run_id_fkey'),
        ForeignKeyConstraint(['team_code'], ['teams.code'], name='team_actions_team_code_fkey'),
        PrimaryKeyConstraint('id', name='team_actions_pkey')
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True, start=1, increment=1, minvalue=1, maxvalue=9223372036854775807, cycle=False, cache=1), primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    incident_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    team_code: Mapped[str] = mapped_column(Text, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    action_sim: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False, server_default=text('now()'))

    incident: Mapped['Incidents'] = relationship('Incidents', back_populates='team_actions')
    run: Mapped['SimRuns'] = relationship('SimRuns', back_populates='team_actions')
    teams: Mapped['Teams'] = relationship('Teams', back_populates='team_actions')


class Branches(Base):
    __tablename__ = 'branches'
    __table_args__ = (
        CheckConstraint("branch_status IS NULL OR (branch_status = ANY (ARRAY['open'::text, 'closed'::text]))", name='branches_branch_status_check'),
        CheckConstraint("branch_type IS NULL OR (branch_type = ANY (ARRAY['flagship'::text, 'standard'::text, 'additional'::text, 'mobile'::text]))", name='branches_branch_type_check'),
        ForeignKeyConstraint(['city_id'], ['cities.id'], name='branches_city_id_fkey'),
        ForeignKeyConstraint(['region_code'], ['regions.code'], name='branches_region_code_fkey'),
        PrimaryKeyConstraint('id', name='branches_pkey'),
        UniqueConstraint('code', name='branches_code_key')
    )

    id: Mapped[int] = mapped_column(Integer, Identity(always=True, start=1, increment=1, minvalue=1, maxvalue=2147483647, cycle=False, cache=1), primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(Text, nullable=False)
    name_ru: Mapped[str] = mapped_column(Text, nullable=False)
    city_id: Mapped[int] = mapped_column(Integer, nullable=False)
    region_code: Mapped[str] = mapped_column(Text, nullable=False)
    desks: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text('6'))
    manager_display_name: Mapped[str] = mapped_column(Text, nullable=False)
    product_line_codes: Mapped[list[str]] = mapped_column(ARRAY(Text()), nullable=False, server_default=text("'{}'::text[]"))
    manager_chat_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    branch_type: Mapped[Optional[str]] = mapped_column(Text)
    branch_status: Mapped[Optional[str]] = mapped_column(Text)
    lat: Mapped[Optional[decimal.Decimal]] = mapped_column(Numeric(9, 6))
    lon: Mapped[Optional[decimal.Decimal]] = mapped_column(Numeric(9, 6))
    address_ru: Mapped[Optional[str]] = mapped_column(Text)
    hours_ru: Mapped[Optional[str]] = mapped_column(Text)
    opened_sim: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(True))
    closed_sim: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(True))

    audio_sessions: Mapped[list['AudioSessions']] = relationship('AudioSessions', back_populates='branch')
    transcripts: Mapped[list['Transcripts']] = relationship('Transcripts', back_populates='branch')
    city: Mapped['Cities'] = relationship('Cities', back_populates='branches')
    regions: Mapped['Regions'] = relationship('Regions', back_populates='branches')
    csi_visits_agg: Mapped[list['CsiVisitsAgg']] = relationship('CsiVisitsAgg', back_populates='branch')
    employees: Mapped[list['Employees']] = relationship('Employees', back_populates='branch')
    csi_responses: Mapped[list['CsiResponses']] = relationship('CsiResponses', back_populates='branch')


class Clients(Base):
    __tablename__ = 'clients'
    __table_args__ = (
        CheckConstraint('churn_risk >= 0 AND churn_risk <= 100', name='clients_churn_risk_check'),
        ForeignKeyConstraint(['city_id'], ['cities.id'], name='clients_city_id_fkey'),
        ForeignKeyConstraint(['psychotype_code'], ['psychotypes.code'], name='clients_psychotype_code_fkey'),
        ForeignKeyConstraint(['region_code'], ['regions.code'], name='clients_region_code_fkey'),
        ForeignKeyConstraint(['segment_code'], ['segments.code'], name='clients_segment_code_fkey'),
        PrimaryKeyConstraint('id', name='clients_pkey')
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True, start=1, increment=1, minvalue=1, maxvalue=9223372036854775807, cycle=False, cache=1), primary_key=True, autoincrement=True)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    segment_code: Mapped[str] = mapped_column(Text, nullable=False)
    psychotype_code: Mapped[str] = mapped_column(Text, nullable=False)
    region_code: Mapped[str] = mapped_column(Text, nullable=False)
    city_id: Mapped[int] = mapped_column(Integer, nullable=False)
    contacts: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    consents: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text('\'{"sms": true, "push": true, "email": true}\'::jsonb'))
    churn_risk: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text('10'))
    clv_estimate_rub: Mapped[int] = mapped_column(Integer, nullable=False)
    activity_baseline: Mapped[decimal.Decimal] = mapped_column(Numeric(8, 2), nullable=False, server_default=text('1'))
    social_handles: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    refunds_30d: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text('0'))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text('true'))
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False, server_default=text('now()'))
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False, server_default=text('now()'))
    public_id: Mapped[Optional[str]] = mapped_column(Text, Computed("('CL-'::text || lpad((id)::text, 6, '0'::text))", persisted=True))
    telegram_chat_id: Mapped[Optional[int]] = mapped_column(BigInteger)

    agent_runs: Mapped[list['AgentRuns']] = relationship('AgentRuns', back_populates='client')
    audio_sessions: Mapped[list['AudioSessions']] = relationship('AudioSessions', back_populates='client')
    external_posts: Mapped[list['ExternalPosts']] = relationship('ExternalPosts', back_populates='author_client')
    incidents: Mapped[list['Incidents']] = relationship('Incidents', back_populates='primary_client')
    operations: Mapped[list['Operations']] = relationship('Operations', back_populates='client')
    signals: Mapped[list['Signals']] = relationship('Signals', back_populates='client')
    transcripts: Mapped[list['Transcripts']] = relationship('Transcripts', back_populates='client')
    city: Mapped['Cities'] = relationship('Cities', back_populates='clients')
    psychotypes: Mapped['Psychotypes'] = relationship('Psychotypes', back_populates='clients')
    regions: Mapped['Regions'] = relationship('Regions', back_populates='clients')
    segments: Mapped['Segments'] = relationship('Segments', back_populates='clients')
    churn_events: Mapped[list['ChurnEvents']] = relationship('ChurnEvents', back_populates='client')
    client_products: Mapped[list['ClientProducts']] = relationship('ClientProducts', back_populates='client')
    client_states: Mapped[list['ClientStates']] = relationship('ClientStates', back_populates='client')
    notifications: Mapped[list['Notifications']] = relationship('Notifications', back_populates='client')
    tasks: Mapped[list['Tasks']] = relationship('Tasks', back_populates='client')
    accounts: Mapped[list['Accounts']] = relationship('Accounts', back_populates='client')
    client_reactions: Mapped[list['ClientReactions']] = relationship('ClientReactions', back_populates='client')


class PersonalChatMessages(Base):
    __tablename__ = 'personal_chat_messages'
    __table_args__ = (
        CheckConstraint('length(request_hash) = 64', name='personal_chat_messages_request_hash_check'),
        ForeignKeyConstraint(['session_id'], ['personal_chat_sessions.id'], ondelete='CASCADE', name='personal_chat_messages_session_id_fkey'),
        ForeignKeyConstraint(['signal_id'], ['signals.id'], ondelete='CASCADE', name='personal_chat_messages_signal_id_fkey'),
        PrimaryKeyConstraint('id', name='personal_chat_messages_pkey'),
        UniqueConstraint('session_id', 'request_id', name='personal_chat_messages_session_id_request_id_key'),
        UniqueConstraint('signal_id', name='personal_chat_messages_signal_id_key')
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True, start=1, increment=1, minvalue=1, maxvalue=9223372036854775807, cycle=False, cache=1), primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    request_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    request_hash: Mapped[str] = mapped_column(Text, nullable=False)
    signal_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False, server_default=text('now()'))

    session: Mapped['PersonalChatSessions'] = relationship('PersonalChatSessions', back_populates='personal_chat_messages')
    signal: Mapped['Signals'] = relationship('Signals', back_populates='personal_chat_messages')


class RuleEvaluations(Base):
    __tablename__ = 'rule_evaluations'
    __table_args__ = (
        CheckConstraint("result = ANY (ARRAY['matched'::text, 'not_matched'::text, 'error'::text])", name='rule_evaluations_result_check'),
        ForeignKeyConstraint(['agent_run_id'], ['agent_runs.id'], ondelete='CASCADE', name='rule_evaluations_agent_run_id_fkey'),
        ForeignKeyConstraint(['rule_code'], ['business_rules.code'], name='rule_evaluations_rule_code_fkey'),
        ForeignKeyConstraint(['run_id'], ['sim_runs.id'], ondelete='CASCADE', name='rule_evaluations_run_id_fkey'),
        ForeignKeyConstraint(['signal_id'], ['signals.id'], ondelete='CASCADE', name='rule_evaluations_signal_id_fkey'),
        PrimaryKeyConstraint('id', name='rule_evaluations_pkey')
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True, start=1, increment=1, minvalue=1, maxvalue=9223372036854775807, cycle=False, cache=1), primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    rule_code: Mapped[str] = mapped_column(Text, nullable=False)
    rule_version: Mapped[int] = mapped_column(Integer, nullable=False)
    result: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text('0'))
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False, server_default=text('now()'))
    signal_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    agent_run_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    proposed_action: Mapped[Optional[str]] = mapped_column(Text)
    amount_rub: Mapped[Optional[decimal.Decimal]] = mapped_column(Numeric(14, 2))

    agent_run: Mapped[Optional['AgentRuns']] = relationship('AgentRuns', back_populates='rule_evaluations')
    business_rules: Mapped['BusinessRules'] = relationship('BusinessRules', back_populates='rule_evaluations')
    run: Mapped['SimRuns'] = relationship('SimRuns', back_populates='rule_evaluations')
    signal: Mapped[Optional['Signals']] = relationship('Signals', back_populates='rule_evaluations')


class ChurnEvents(Base):
    __tablename__ = 'churn_events'
    __table_args__ = (
        ForeignKeyConstraint(['client_id'], ['clients.id'], ondelete='CASCADE', name='churn_events_client_id_fkey'),
        ForeignKeyConstraint(['closure_incident_id'], ['incidents.id'], name='churn_events_closure_incident_id_fkey'),
        ForeignKeyConstraint(['run_id'], ['sim_runs.id'], ondelete='CASCADE', name='churn_events_run_id_fkey'),
        PrimaryKeyConstraint('id', name='churn_events_pkey')
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True, start=1, increment=1, minvalue=1, maxvalue=9223372036854775807, cycle=False, cache=1), primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    client_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    churn_sim: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    related_incident_ids: Mapped[list[int]] = mapped_column(ARRAY(BigInteger()), nullable=False, server_default=text("'{}'::bigint[]"))
    offered: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False, server_default=text('now()'))
    days_after_incident: Mapped[Optional[decimal.Decimal]] = mapped_column(Numeric(5, 1))
    closure_incident_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    realized_loss_rub: Mapped[Optional[decimal.Decimal]] = mapped_column(Numeric(14, 2))

    client: Mapped['Clients'] = relationship('Clients', back_populates='churn_events')
    closure_incident: Mapped[Optional['Incidents']] = relationship('Incidents', back_populates='churn_events')
    run: Mapped['SimRuns'] = relationship('SimRuns', back_populates='churn_events')


class ClientProducts(Base):
    __tablename__ = 'client_products'
    __table_args__ = (
        CheckConstraint("status = ANY (ARRAY['active'::text, 'pending'::text, 'closed'::text, 'rejected'::text])", name='client_products_status_check'),
        ForeignKeyConstraint(['client_id'], ['clients.id'], ondelete='CASCADE', name='client_products_client_id_fkey'),
        ForeignKeyConstraint(['product_code'], ['products.code'], name='client_products_product_code_fkey'),
        PrimaryKeyConstraint('id', name='client_products_pkey')
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True, start=1, increment=1, minvalue=1, maxvalue=9223372036854775807, cycle=False, cache=1), primary_key=True, autoincrement=True)
    client_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    product_code: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    terms: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    card_last4: Mapped[Optional[str]] = mapped_column(CHAR(4))
    opened_sim: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(True))
    closed_sim: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(True))

    client: Mapped['Clients'] = relationship('Clients', back_populates='client_products')
    products: Mapped['Products'] = relationship('Products', back_populates='client_products')
    accounts: Mapped[list['Accounts']] = relationship('Accounts', back_populates='product')


class ClientStates(Base):
    __tablename__ = 'client_states'
    __table_args__ = (
        CheckConstraint('care_score >= 0::numeric AND care_score <= 1::numeric', name='client_states_care_score_check'),
        CheckConstraint("state = ANY (ARRAY['calm'::text, 'affected'::text, 'complaining'::text, 'waiting'::text, 'satisfied'::text, 'asks_again'::text, 'escalates'::text, 'churn_intent'::text, 'retained'::text, 'churned'::text])", name='client_states_state_check'),
        ForeignKeyConstraint(['client_id'], ['clients.id'], ondelete='CASCADE', name='client_states_client_id_fkey'),
        ForeignKeyConstraint(['incident_id'], ['incidents.id'], name='client_states_incident_id_fkey'),
        ForeignKeyConstraint(['run_id'], ['sim_runs.id'], ondelete='CASCADE', name='client_states_run_id_fkey'),
        ForeignKeyConstraint(['signal_id'], ['signals.id'], name='client_states_signal_id_fkey'),
        PrimaryKeyConstraint('id', name='client_states_pkey')
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True, start=1, increment=1, minvalue=1, maxvalue=9223372036854775807, cycle=False, cache=1), primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    client_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    state: Mapped[str] = mapped_column(Text, nullable=False)
    since_sim: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False)
    trigger: Mapped[str] = mapped_column(Text, nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text('true'))
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False, server_default=text('now()'))
    incident_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    signal_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    care_score: Mapped[Optional[decimal.Decimal]] = mapped_column(Numeric(4, 3))
    hazard: Mapped[Optional[decimal.Decimal]] = mapped_column(Numeric(6, 4))

    client: Mapped['Clients'] = relationship('Clients', back_populates='client_states')
    incident: Mapped[Optional['Incidents']] = relationship('Incidents', back_populates='client_states')
    run: Mapped['SimRuns'] = relationship('SimRuns', back_populates='client_states')
    signal: Mapped[Optional['Signals']] = relationship('Signals', back_populates='client_states')


class CsiVisitsAgg(Base):
    __tablename__ = 'csi_visits_agg'
    __table_args__ = (
        ForeignKeyConstraint(['branch_id'], ['branches.id'], name='csi_visits_agg_branch_id_fkey'),
        PrimaryKeyConstraint('branch_id', 'day', 'wait_bucket', 'redirects_bucket', name='csi_visits_agg_pkey')
    )

    branch_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    day: Mapped[datetime.date] = mapped_column(Date, primary_key=True)
    wait_bucket: Mapped[str] = mapped_column(Text, primary_key=True)
    redirects_bucket: Mapped[str] = mapped_column(Text, primary_key=True)
    visits: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text('0'))

    branch: Mapped['Branches'] = relationship('Branches', back_populates='csi_visits_agg')


class Employees(Base):
    __tablename__ = 'employees'
    __table_args__ = (
        ForeignKeyConstraint(['branch_id'], ['branches.id'], name='employees_branch_id_fkey'),
        PrimaryKeyConstraint('id', name='employees_pkey')
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True, start=1, increment=1, minvalue=1, maxvalue=9223372036854775807, cycle=False, cache=1), primary_key=True, autoincrement=True)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    branch_id: Mapped[int] = mapped_column(Integer, nullable=False)
    desk_no: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    position: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'client_manager'::text"))
    violations_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text('0'))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text('true'))
    public_id: Mapped[Optional[str]] = mapped_column(Text, Computed("('EMP-'::text || lpad((id)::text, 5, '0'::text))", persisted=True))
    hired_sim: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(True))
    education: Mapped[Optional[str]] = mapped_column(Text)
    position_since_sim: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(True))

    audio_sessions: Mapped[list['AudioSessions']] = relationship('AudioSessions', back_populates='employee')
    transcripts: Mapped[list['Transcripts']] = relationship('Transcripts', back_populates='employee')
    branch: Mapped['Branches'] = relationship('Branches', back_populates='employees')
    csi_responses: Mapped[list['CsiResponses']] = relationship('CsiResponses', back_populates='employee')


class Notifications(Base):
    __tablename__ = 'notifications'
    __table_args__ = (
        CheckConstraint("recipient_type = ANY (ARRAY['client'::text, 'team'::text, 'public'::text, 'cx'::text])", name='notifications_recipient_type_check'),
        CheckConstraint("status = ANY (ARRAY['queued'::text, 'sent'::text, 'delivered'::text, 'failed'::text, 'suppressed'::text])", name='notifications_status_check'),
        ForeignKeyConstraint(['client_id'], ['clients.id'], name='notifications_client_id_fkey'),
        ForeignKeyConstraint(['incident_id'], ['incidents.id'], name='notifications_incident_id_fkey'),
        ForeignKeyConstraint(['run_id'], ['sim_runs.id'], ondelete='CASCADE', name='notifications_run_id_fkey'),
        ForeignKeyConstraint(['signal_id'], ['signals.id'], name='notifications_signal_id_fkey'),
        ForeignKeyConstraint(['team_code'], ['teams.code'], name='notifications_team_code_fkey'),
        PrimaryKeyConstraint('id', name='notifications_pkey')
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True, start=1, increment=1, minvalue=1, maxvalue=9223372036854775807, cycle=False, cache=1), primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    recipient_type: Mapped[str] = mapped_column(Text, nullable=False)
    channel_code: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'queued'::text"))
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False, server_default=text('now()'))
    client_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    team_code: Mapped[Optional[str]] = mapped_column(Text)
    signal_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    incident_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    template_code: Mapped[Optional[str]] = mapped_column(Text)
    subject: Mapped[Optional[str]] = mapped_column(Text)
    sent_sim: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(True))
    sent_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(True))
    external_ref: Mapped[Optional[str]] = mapped_column(Text)
    public_id: Mapped[Optional[str]] = mapped_column(Text, Computed("('NTF-'::text || lpad((id)::text, 6, '0'::text))", persisted=True))

    client: Mapped[Optional['Clients']] = relationship('Clients', back_populates='notifications')
    incident: Mapped[Optional['Incidents']] = relationship('Incidents', back_populates='notifications')
    run: Mapped['SimRuns'] = relationship('SimRuns', back_populates='notifications')
    signal: Mapped[Optional['Signals']] = relationship('Signals', back_populates='notifications')
    teams: Mapped[Optional['Teams']] = relationship('Teams', back_populates='notifications')
    client_reactions: Mapped[list['ClientReactions']] = relationship('ClientReactions', back_populates='notification')


class Tasks(Base):
    __tablename__ = 'tasks'
    __table_args__ = (
        CheckConstraint("kind = ANY (ARRAY['gift'::text, 'callback'::text, 'manual_review'::text, 'clarify_client'::text, 'report_reminder'::text, 'closure_review'::text])", name='tasks_kind_check'),
        CheckConstraint("status = ANY (ARRAY['open'::text, 'approved'::text, 'changed'::text, 'rejected'::text, 'done'::text, 'cancelled'::text])", name='tasks_status_check'),
        ForeignKeyConstraint(['client_id'], ['clients.id'], name='tasks_client_id_fkey'),
        ForeignKeyConstraint(['incident_id'], ['incidents.id'], ondelete='CASCADE', name='tasks_incident_id_fkey'),
        ForeignKeyConstraint(['run_id'], ['sim_runs.id'], ondelete='CASCADE', name='tasks_run_id_fkey'),
        PrimaryKeyConstraint('id', name='tasks_pkey')
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True, start=1, increment=1, minvalue=1, maxvalue=9223372036854775807, cycle=False, cache=1), primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    assignee: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'cx_operator'::text"))
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'open'::text"))
    requires_hitl: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text('false'))
    created_sim: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False, server_default=text('now()'))
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False, server_default=text('now()'))
    incident_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    client_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    due_sim: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(True))
    resolved_sim: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(True))
    public_id: Mapped[Optional[str]] = mapped_column(Text, Computed("('TSK-'::text || lpad((id)::text, 6, '0'::text))", persisted=True))

    client: Mapped[Optional['Clients']] = relationship('Clients', back_populates='tasks')
    incident: Mapped[Optional['Incidents']] = relationship('Incidents', back_populates='tasks')
    run: Mapped['SimRuns'] = relationship('SimRuns', back_populates='tasks')
    human_decisions: Mapped[list['HumanDecisions']] = relationship('HumanDecisions', back_populates='task')


class Accounts(Base):
    __tablename__ = 'accounts'
    __table_args__ = (
        CheckConstraint("status = ANY (ARRAY['active'::text, 'blocked'::text, 'closed'::text])", name='accounts_status_check'),
        ForeignKeyConstraint(['client_id'], ['clients.id'], ondelete='CASCADE', name='accounts_client_id_fkey'),
        ForeignKeyConstraint(['product_id'], ['client_products.id'], ondelete='SET NULL', name='accounts_product_id_fkey'),
        PrimaryKeyConstraint('id', name='accounts_pkey'),
        {'comment': 'Mock-АБС: счета клиентов; баланс = сумма проводок (проверяется '
                'тестом)'}
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True, start=1, increment=1, minvalue=1, maxvalue=9223372036854775807, cycle=False, cache=1), primary_key=True, autoincrement=True)
    client_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    number_masked: Mapped[str] = mapped_column(Text, nullable=False)
    currency: Mapped[str] = mapped_column(CHAR(3), nullable=False, server_default=text("'RUB'::bpchar"))
    balance: Mapped[decimal.Decimal] = mapped_column(Numeric(14, 2), nullable=False, server_default=text('0'))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'active'::text"))
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False, server_default=text('now()'))
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False, server_default=text('now()'))
    product_id: Mapped[Optional[int]] = mapped_column(BigInteger)

    client: Mapped['Clients'] = relationship('Clients', back_populates='accounts')
    product: Mapped[Optional['ClientProducts']] = relationship('ClientProducts', back_populates='accounts')
    ledger_entries: Mapped[list['LedgerEntries']] = relationship('LedgerEntries', back_populates='account')


class ClientReactions(Base):
    __tablename__ = 'client_reactions'
    __table_args__ = (
        CheckConstraint("generated_by = ANY (ARRAY['llm'::text, 'param'::text, 'mock'::text])", name='client_reactions_generated_by_check'),
        CheckConstraint("reaction = ANY (ARRAY['satisfied'::text, 'asks_again'::text, 'escalates'::text, 'silent'::text, 'thanks'::text, 'churn_intent'::text, 'closes_account'::text])", name='client_reactions_reaction_check'),
        CheckConstraint('satisfaction >= 0::numeric AND satisfaction <= 1::numeric', name='client_reactions_satisfaction_check'),
        CheckConstraint("tone = ANY (ARRAY['neutral'::text, 'positive'::text, 'irritated'::text, 'angry'::text, 'sarcastic'::text, 'formal'::text])", name='client_reactions_tone_check'),
        ForeignKeyConstraint(['agent_run_id'], ['agent_runs.id'], name='client_reactions_run_fk'),
        ForeignKeyConstraint(['client_id'], ['clients.id'], ondelete='CASCADE', name='client_reactions_client_id_fkey'),
        ForeignKeyConstraint(['incident_id'], ['incidents.id'], name='client_reactions_incident_id_fkey'),
        ForeignKeyConstraint(['notification_id'], ['notifications.id'], name='client_reactions_notification_id_fkey'),
        ForeignKeyConstraint(['run_id'], ['sim_runs.id'], ondelete='CASCADE', name='client_reactions_run_id_fkey'),
        ForeignKeyConstraint(['signal_id'], ['signals.id'], name='client_reactions_signal_id_fkey'),
        PrimaryKeyConstraint('id', name='client_reactions_pkey')
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True, start=1, increment=1, minvalue=1, maxvalue=9223372036854775807, cycle=False, cache=1), primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    client_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reaction: Mapped[str] = mapped_column(Text, nullable=False)
    tone: Mapped[str] = mapped_column(Text, nullable=False)
    generated_by: Mapped[str] = mapped_column(Text, nullable=False)
    reacted_sim: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False, server_default=text('now()'))
    signal_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    incident_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    notification_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    satisfaction: Mapped[Optional[decimal.Decimal]] = mapped_column(Numeric(4, 3))
    text_: Mapped[Optional[str]] = mapped_column('text', Text)
    agent_run_id: Mapped[Optional[int]] = mapped_column(BigInteger)

    agent_run: Mapped[Optional['AgentRuns']] = relationship('AgentRuns', back_populates='client_reactions')
    client: Mapped['Clients'] = relationship('Clients', back_populates='client_reactions')
    incident: Mapped[Optional['Incidents']] = relationship('Incidents', back_populates='client_reactions')
    notification: Mapped[Optional['Notifications']] = relationship('Notifications', back_populates='client_reactions')
    run: Mapped['SimRuns'] = relationship('SimRuns', back_populates='client_reactions')
    signal: Mapped[Optional['Signals']] = relationship('Signals', back_populates='client_reactions')


class CsiResponses(Base):
    __tablename__ = 'csi_responses'
    __table_args__ = (
        ForeignKeyConstraint(['branch_id'], ['branches.id'], name='csi_responses_branch_id_fkey'),
        ForeignKeyConstraint(['employee_id'], ['employees.id'], name='csi_responses_employee_id_fkey'),
        ForeignKeyConstraint(['signal_id'], ['signals.id'], ondelete='CASCADE', name='csi_responses_signal_id_fkey'),
        PrimaryKeyConstraint('signal_id', name='csi_responses_pkey'),
        UniqueConstraint('csi_no', name='csi_responses_csi_no_key')
    )

    signal_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    csi_no: Mapped[str] = mapped_column(Text, nullable=False)
    complaint_ru: Mapped[str] = mapped_column(Text, nullable=False)
    redirects: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text('0'))
    products: Mapped[list[str]] = mapped_column(ARRAY(Text()), nullable=False, server_default=text("'{}'::text[]"))
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False, server_default=text('now()'))
    ticket_code: Mapped[Optional[str]] = mapped_column(Text)
    waiting_count: Mapped[Optional[int]] = mapped_column(SmallInteger)
    serving_count: Mapped[Optional[int]] = mapped_column(SmallInteger)
    out_of_order_count: Mapped[Optional[int]] = mapped_column(SmallInteger)
    wait_min: Mapped[Optional[decimal.Decimal]] = mapped_column(Numeric(8, 2))
    service_min: Mapped[Optional[decimal.Decimal]] = mapped_column(Numeric(8, 2))
    branch_id: Mapped[Optional[int]] = mapped_column(Integer)
    employee_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    position: Mapped[Optional[str]] = mapped_column(Text)
    education: Mapped[Optional[str]] = mapped_column(Text)
    tenure_position_days: Mapped[Optional[int]] = mapped_column(Integer)
    tenure_org_days: Mapped[Optional[int]] = mapped_column(Integer)

    branch: Mapped[Optional['Branches']] = relationship('Branches', back_populates='csi_responses')
    employee: Mapped[Optional['Employees']] = relationship('Employees', back_populates='csi_responses')
    signal: Mapped['Signals'] = relationship('Signals', back_populates='csi_responses')


class HumanDecisions(Base):
    __tablename__ = 'human_decisions'
    __table_args__ = (
        CheckConstraint("decision = ANY (ARRAY['accept'::text, 'modify'::text, 'reject'::text, 'delegate'::text])", name='human_decisions_decision_check'),
        ForeignKeyConstraint(['agent_run_id'], ['agent_runs.id'], name='human_decisions_agent_run_id_fkey'),
        ForeignKeyConstraint(['incident_id'], ['incidents.id'], name='human_decisions_incident_id_fkey'),
        ForeignKeyConstraint(['signal_id'], ['signals.id'], name='human_decisions_signal_id_fkey'),
        ForeignKeyConstraint(['sim_run_id'], ['sim_runs.id'], ondelete='CASCADE', name='human_decisions_sim_run_id_fkey'),
        ForeignKeyConstraint(['task_id'], ['tasks.id'], name='human_decisions_task_id_fkey'),
        PrimaryKeyConstraint('id', name='human_decisions_pkey')
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True, start=1, increment=1, minvalue=1, maxvalue=9223372036854775807, cycle=False, cache=1), primary_key=True, autoincrement=True)
    sim_run_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    requested_sim: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False)
    requested_at: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False, server_default=text('now()'))
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    agent_proposal: Mapped[dict] = mapped_column(JSONB, nullable=False)
    options: Mapped[dict] = mapped_column(JSONB, nullable=False)
    use_as_fewshot: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text('true'))
    agent_run_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    signal_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    incident_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    task_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    recommendation: Mapped[Optional[str]] = mapped_column(Text)
    decision: Mapped[Optional[str]] = mapped_column(Text)
    modified_proposal: Mapped[Optional[dict]] = mapped_column(JSONB)
    decided_by: Mapped[Optional[str]] = mapped_column(Text)
    comment: Mapped[Optional[str]] = mapped_column(Text)
    decided_sim: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(True))
    decided_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(True))
    public_id: Mapped[Optional[str]] = mapped_column(Text, Computed("('HD-'::text || lpad((id)::text, 6, '0'::text))", persisted=True))

    agent_run: Mapped[Optional['AgentRuns']] = relationship('AgentRuns', back_populates='human_decisions')
    incident: Mapped[Optional['Incidents']] = relationship('Incidents', back_populates='human_decisions')
    signal: Mapped[Optional['Signals']] = relationship('Signals', back_populates='human_decisions')
    sim_run: Mapped['SimRuns'] = relationship('SimRuns', back_populates='human_decisions')
    task: Mapped[Optional['Tasks']] = relationship('Tasks', back_populates='human_decisions')
    compliance_alerts: Mapped[list['ComplianceAlerts']] = relationship('ComplianceAlerts', back_populates='human_decision')
    escalations: Mapped[list['Escalations']] = relationship('Escalations', back_populates='human_decision')
    hitl_feedback: Mapped[list['HitlFeedback']] = relationship('HitlFeedback', back_populates='human_decision')


class ComplianceAlerts(Base):
    __tablename__ = 'compliance_alerts'
    __table_args__ = (
        CheckConstraint("decision = ANY (ARRAY['go'::text, 'false_positive'::text, 'open_incident'::text, 'acknowledged'::text])", name='compliance_alerts_decision_check'),
        CheckConstraint("kind = ANY (ARRAY['threshold'::text, 'immediate'::text, 'report'::text])", name='compliance_alerts_kind_check'),
        ForeignKeyConstraint(['human_decision_id'], ['human_decisions.id'], name='compliance_alerts_human_decision_id_fkey'),
        ForeignKeyConstraint(['incident_id'], ['incidents.id'], name='compliance_alerts_incident_id_fkey'),
        ForeignKeyConstraint(['session_id'], ['audio_sessions.id'], ondelete='CASCADE', name='compliance_alerts_session_id_fkey'),
        ForeignKeyConstraint(['transcript_id'], ['transcripts.id'], name='compliance_alerts_transcript_fk'),
        PrimaryKeyConstraint('id', name='compliance_alerts_pkey')
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True, start=1, increment=1, minvalue=1, maxvalue=9223372036854775807, cycle=False, cache=1), primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sent_at: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False, server_default=text('now()'))
    channels: Mapped[list[str]] = mapped_column(ARRAY(Text()), nullable=False, server_default=text("'{ws}'::text[]"))
    kind: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'threshold'::text"))
    incident_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer)
    acknowledged_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(True))
    acknowledged_by: Mapped[Optional[str]] = mapped_column(Text)
    decision: Mapped[Optional[str]] = mapped_column(Text)
    human_decision_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    recommendation_ru: Mapped[Optional[str]] = mapped_column(Text)
    transcript_id: Mapped[Optional[int]] = mapped_column(BigInteger)

    human_decision: Mapped[Optional['HumanDecisions']] = relationship('HumanDecisions', back_populates='compliance_alerts')
    incident: Mapped[Optional['Incidents']] = relationship('Incidents', back_populates='compliance_alerts')
    session: Mapped['AudioSessions'] = relationship('AudioSessions', back_populates='compliance_alerts')
    transcript: Mapped[Optional['Transcripts']] = relationship('Transcripts', back_populates='compliance_alerts')
    financial_evidence: Mapped[list['FinancialEvidence']] = relationship('FinancialEvidence', back_populates='alert')


class Escalations(Base):
    __tablename__ = 'escalations'
    __table_args__ = (
        CheckConstraint("created_by = ANY (ARRAY['agent'::text, 'human'::text, 'compliance'::text])", name='escalations_created_by_check'),
        CheckConstraint("severity = ANY (ARRAY['low'::text, 'medium'::text, 'high'::text, 'critical'::text])", name='escalations_severity_check'),
        CheckConstraint("status = ANY (ARRAY['open'::text, 'acknowledged'::text, 'resolved'::text, 'dismissed'::text])", name='escalations_status_check'),
        CheckConstraint("to_role = ANY (ARRAY['cx_lead'::text, 'branch_manager'::text])", name='escalations_to_role_check'),
        ForeignKeyConstraint(['agent_run_id'], ['agent_runs.id'], name='escalations_agent_run_id_fkey'),
        ForeignKeyConstraint(['human_decision_id'], ['human_decisions.id'], name='escalations_human_decision_id_fkey'),
        ForeignKeyConstraint(['incident_id'], ['incidents.id'], ondelete='SET NULL', name='escalations_incident_id_fkey'),
        ForeignKeyConstraint(['run_id'], ['sim_runs.id'], ondelete='CASCADE', name='escalations_run_id_fkey'),
        ForeignKeyConstraint(['signal_id'], ['signals.id'], ondelete='SET NULL', name='escalations_signal_id_fkey'),
        PrimaryKeyConstraint('id', name='escalations_pkey'),
        {'comment': 'Эскалации руководителю (ДТЗ FR-3.4): создаются инструментом '
                'escalate_to_manager или человеком'}
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True, start=1, increment=1, minvalue=1, maxvalue=9223372036854775807, cycle=False, cache=1), primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(Text, nullable=False)
    to_role: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'open'::text"))
    created_by: Mapped[str] = mapped_column(Text, nullable=False)
    created_sim: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False, server_default=text('now()'))
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False, server_default=text('now()'))
    public_id: Mapped[Optional[str]] = mapped_column(Text, Computed("('ESC-'::text || lpad((id)::text, 6, '0'::text))", persisted=True))
    incident_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    signal_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    agent_run_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    human_decision_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    acknowledged_by: Mapped[Optional[str]] = mapped_column(Text)
    acknowledged_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(True))
    resolution_ru: Mapped[Optional[str]] = mapped_column(Text)

    agent_run: Mapped[Optional['AgentRuns']] = relationship('AgentRuns', back_populates='escalations')
    human_decision: Mapped[Optional['HumanDecisions']] = relationship('HumanDecisions', back_populates='escalations')
    incident: Mapped[Optional['Incidents']] = relationship('Incidents', back_populates='escalations')
    run: Mapped['SimRuns'] = relationship('SimRuns', back_populates='escalations')
    signal: Mapped[Optional['Signals']] = relationship('Signals', back_populates='escalations')


class HitlFeedback(Base):
    __tablename__ = 'hitl_feedback'
    __table_args__ = (
        CheckConstraint('length(btrim(comment)) >= 1 AND length(btrim(comment)) <= 4000', name='hitl_feedback_comment_check'),
        CheckConstraint('length(btrim(recorded_by)) >= 1 AND length(btrim(recorded_by)) <= 120', name='hitl_feedback_recorded_by_check'),
        CheckConstraint('length(idempotency_key) >= 1 AND length(idempotency_key) <= 120', name='hitl_feedback_idempotency_key_check'),
        ForeignKeyConstraint(['human_decision_id'], ['human_decisions.id'], ondelete='CASCADE', name='hitl_feedback_human_decision_id_fkey'),
        PrimaryKeyConstraint('id', name='hitl_feedback_pkey'),
        UniqueConstraint('human_decision_id', 'idempotency_key', name='hitl_feedback_human_decision_id_idempotency_key_key')
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True, start=1, increment=1, minvalue=1, maxvalue=9223372036854775807, cycle=False, cache=1), primary_key=True, autoincrement=True)
    human_decision_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)
    comment: Mapped[str] = mapped_column(Text, nullable=False)
    recorded_by: Mapped[str] = mapped_column(Text, nullable=False)
    recorded_sim: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False)
    recorded_at: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False, server_default=text('now()'))

    human_decision: Mapped['HumanDecisions'] = relationship('HumanDecisions', back_populates='hitl_feedback')
    hitl_feedback_processing: Mapped['HitlFeedbackProcessing'] = relationship('HitlFeedbackProcessing', uselist=False, back_populates='feedback')


class LedgerEntries(Base):
    __tablename__ = 'ledger_entries'
    __table_args__ = (
        CheckConstraint('amount >= 0::numeric', name='ledger_entries_amount_check'),
        CheckConstraint("created_by = ANY (ARRAY['sim'::text, 'agent'::text, 'human'::text, 'scenario'::text])", name='ledger_entries_created_by_check'),
        CheckConstraint("kind = ANY (ARRAY['debit'::text, 'credit'::text, 'fee'::text, 'refund'::text, 'reversal'::text])", name='ledger_entries_kind_check'),
        ForeignKeyConstraint(['account_id'], ['accounts.id'], ondelete='CASCADE', name='ledger_entries_account_id_fkey'),
        ForeignKeyConstraint(['agent_run_id'], ['agent_runs.id'], name='ledger_entries_agent_run_id_fkey'),
        ForeignKeyConstraint(['operation_id'], ['operations.id'], ondelete='SET NULL', name='ledger_entries_operation_id_fkey'),
        ForeignKeyConstraint(['refund_of_entry_id'], ['ledger_entries.id'], name='ledger_entries_refund_of_entry_id_fkey'),
        ForeignKeyConstraint(['run_id'], ['sim_runs.id'], ondelete='CASCADE', name='ledger_entries_run_id_fkey'),
        PrimaryKeyConstraint('id', name='ledger_entries_pkey'),
        UniqueConstraint('correlation_id', name='ledger_entries_correlation_id_key'),
        {'comment': 'Проводки Mock-АБС; fee — комиссия, refund — возврат (всегда '
                'ссылается на исходную fee)'}
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True, start=1, increment=1, minvalue=1, maxvalue=9223372036854775807, cycle=False, cache=1), primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    account_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    amount: Mapped[decimal.Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    posted_at: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False, server_default=text('now()'))
    posted_sim: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False)
    correlation_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    created_by: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'sim'::text"))
    operation_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    counterpart: Mapped[Optional[str]] = mapped_column(Text)
    refund_of_entry_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    rule_id: Mapped[Optional[str]] = mapped_column(Text)
    agent_run_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    public_id: Mapped[Optional[str]] = mapped_column(Text, Computed("('LED-'::text || lpad((id)::text, 6, '0'::text))", persisted=True))

    account: Mapped['Accounts'] = relationship('Accounts', back_populates='ledger_entries')
    agent_run: Mapped[Optional['AgentRuns']] = relationship('AgentRuns', back_populates='ledger_entries')
    operation: Mapped[Optional['Operations']] = relationship('Operations', back_populates='ledger_entries')
    refund_of_entry: Mapped[Optional['LedgerEntries']] = relationship('LedgerEntries', remote_side=[id], back_populates='refund_of_entry_reverse')
    refund_of_entry_reverse: Mapped[list['LedgerEntries']] = relationship('LedgerEntries', remote_side=[refund_of_entry_id], back_populates='refund_of_entry')
    run: Mapped['SimRuns'] = relationship('SimRuns', back_populates='ledger_entries')


class FinancialEvidence(Base):
    __tablename__ = 'financial_evidence'
    __table_args__ = (
        CheckConstraint('length(deal_ref) >= 1 AND length(deal_ref) <= 120', name='financial_evidence_deal_ref_check'),
        CheckConstraint('length(evidence_ref) >= 1 AND length(evidence_ref) <= 500', name='financial_evidence_evidence_ref_check'),
        CheckConstraint('length(idempotency_key) >= 1 AND length(idempotency_key) <= 120', name='financial_evidence_idempotency_key_check'),
        CheckConstraint('length(recorded_by) >= 1 AND length(recorded_by) <= 120', name='financial_evidence_recorded_by_check'),
        CheckConstraint("outcome = ANY (ARRAY['prevented'::text, 'completed'::text, 'unknown'::text])", name='financial_evidence_outcome_check'),
        CheckConstraint("payload_sha256 ~ '^[0-9a-f]{64}$'::text", name='financial_evidence_payload_sha256_check'),
        CheckConstraint("policy_sha256 ~ '^[0-9a-f]{64}$'::text", name='financial_evidence_policy_sha256_check'),
        CheckConstraint("scope = ANY (ARRAY['demo'::text, 'observed'::text])", name='financial_evidence_scope_check'),
        ForeignKeyConstraint(['alert_id'], ['compliance_alerts.id'], name='financial_evidence_alert_id_fkey'),
        ForeignKeyConstraint(['incident_id'], ['incidents.id'], ondelete='CASCADE', name='financial_evidence_incident_id_fkey'),
        ForeignKeyConstraint(['run_id'], ['sim_runs.id'], ondelete='CASCADE', name='financial_evidence_run_id_fkey'),
        PrimaryKeyConstraint('id', name='financial_evidence_pkey'),
        UniqueConstraint('run_id', 'scope', 'idempotency_key', name='financial_evidence_run_id_scope_idempotency_key_key')
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True, start=1, increment=1, minvalue=1, maxvalue=9223372036854775807, cycle=False, cache=1), primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    incident_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    alert_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    scope: Mapped[str] = mapped_column(Text, nullable=False)
    deal_ref: Mapped[str] = mapped_column(Text, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)
    payload_sha256: Mapped[str] = mapped_column(Text, nullable=False)
    intervention_sim: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False)
    deal_closed_sim: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False)
    outcome: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_ref: Mapped[str] = mapped_column(Text, nullable=False)
    recorded_by: Mapped[str] = mapped_column(Text, nullable=False)
    policy: Mapped[dict] = mapped_column(JSONB, nullable=False)
    policy_sha256: Mapped[str] = mapped_column(Text, nullable=False)
    recorded_at: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False, server_default=text('now()'))

    alert: Mapped['ComplianceAlerts'] = relationship('ComplianceAlerts', back_populates='financial_evidence')
    incident: Mapped['Incidents'] = relationship('Incidents', back_populates='financial_evidence')
    run: Mapped['SimRuns'] = relationship('SimRuns', back_populates='financial_evidence')


class HitlFeedbackProcessing(Base):
    __tablename__ = 'hitl_feedback_processing'
    __table_args__ = (
        CheckConstraint("status = ANY (ARRAY['pending'::text, 'applied'::text, 'failed'::text])", name='hitl_feedback_processing_status_check'),
        ForeignKeyConstraint(['agent_run_id'], ['agent_runs.id'], name='hitl_feedback_processing_agent_run_id_fkey'),
        ForeignKeyConstraint(['feedback_id'], ['hitl_feedback.id'], ondelete='CASCADE', name='hitl_feedback_processing_feedback_id_fkey'),
        PrimaryKeyConstraint('feedback_id', name='hitl_feedback_processing_pkey')
    )

    feedback_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'pending'::text"))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text('0'))
    retry_at: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False, server_default=text('now()'))
    agent_run_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    review: Mapped[Optional[dict]] = mapped_column(JSONB)
    applied_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(True))
    error: Mapped[Optional[str]] = mapped_column(Text)

    agent_run: Mapped[Optional['AgentRuns']] = relationship('AgentRuns', back_populates='hitl_feedback_processing')
    feedback: Mapped['HitlFeedback'] = relationship('HitlFeedback', back_populates='hitl_feedback_processing')
