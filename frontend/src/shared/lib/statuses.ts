/** Статусы инцидента, считающиеся «открытыми» (FSM ТЗ 8.3). */
export const OPEN_STATUSES = [
  'new',
  'classified',
  'routed',
  'in_progress',
  'fix_proposed',
  'fix_deployed',
  'verifying',
  'awaiting_human',
  'awaiting_client',
  'escalated',
]
