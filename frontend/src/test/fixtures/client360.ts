import type { Schemas } from '@/shared/api/client'

export const client360Fixture = {
  id: 17, public_id: 'CL-000017', display_name: 'Ирина Т.', segment_code: 'premium', region_code: '77', city_name: 'Москва', churn_risk: 78, is_active: false, clv_estimate_rub: 1_200_000,
  contacts: { phone_masked: '+7 900 ***-**-**', email_masked: 'i***@example.com', preferred: 'chat' },
  psychotype: { code: 'anxious', name_ru: 'Нуждается в регулярном информировании', name_en: 'Needs regular updates', communication_hint_ru: 'Подтвердите, что проблема замечена, объясните следующий шаг и регулярно сообщайте о ходе работы.' },
  current_state: { state: 'churned', since_sim: '2026-10-20T11:00:00Z', care_score: 0.25, hazard: 0.16 },
  products: [{ id: 1, product_code: 'debit_card', status: 'closed', card_last4: '4512' }],
  operations: [{ id: 501, run_id: 42, run_public_id: 'RUN-000042', product_code: 'debit_card', op_type: 'card_payment', status: 'failed', amount_rub: 450.5, error_code: 'PROC-ERROR', fault_id: 9, started_sim: '2026-10-20T09:00:00Z' }],
  signals: [{ id: 7, public_id: 'SIG-000007', run_id: 42, run_public_id: 'RUN-000042', text: 'Не прошла оплата картой', channel_code: 'chat', status: 'answered', received_sim: '2026-10-20T09:05:00Z' }],
  incidents: [{ id: 11, public_id: 'INC-000011', title: 'Закрытие счёта клиента', incident_type: 'account_closure', status: 'closed', created_sim: '2026-10-20T11:00:00Z' }],
  state_history: [{ id: 2, run_id: 42, run_public_id: 'RUN-000042', state: 'churned', trigger: 'closure', care_score: 0.25, since_sim: '2026-10-20T11:00:00Z', incident_public_id: 'INC-000011' }, { id: 1, run_id: 42, run_public_id: 'RUN-000042', state: 'waiting', trigger: 'signal_sent', care_score: 0.3, since_sim: '2026-10-20T09:05:00Z' }],
  gifts: [{ id: 14, kind: 'gift', run_id: 42, status: 'done', requires_hitl: false, created_sim: '2026-10-20T10:00:00Z', resolved_sim: '2026-10-20T10:05:00Z', incident_public_id: 'INC-000011', gift_name: 'Бонусные баллы', payload: { gift: { gift_code: 'bonus_points', points: 300 }, when: 'now' } }],
} satisfies Schemas['Client360']

export const client360Refs: Record<string, unknown> = {
  segments: [{ code: 'premium', name_ru: 'Премиальный', name_en: 'Premium' }],
  products: [{ code: 'debit_card', name_ru: 'Дебетовая карта', name_en: 'Debit card' }],
  gift_catalog: [{ code: 'bonus_points', name_ru: 'Бонусные баллы', name_en: 'Bonus points' }],
}
