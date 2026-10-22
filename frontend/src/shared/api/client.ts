import type { components, paths } from './types'

export type Schemas = components['schemas']
export type Signal = Schemas['Signal']
export type SignalDetail = Schemas['SignalDetail']
export type IncidentBrief = Schemas['IncidentBrief']
export type IncidentDetail = Schemas['IncidentDetail']
export type HitlItem = Schemas['HitlItem']
export type AgentRunBrief = Schemas['AgentRunBrief']
export type AgentRunDetail = Schemas['AgentRunDetail']
export type AgentStep = Schemas['AgentStep']
export type AgentGraph = Schemas['AgentGraph']
export type SimState = Schemas['SimState']
export type SimRun = Schemas['SimRun']
export type Notification = Schemas['Notification']
export type StatusHistoryItem = Schemas['StatusHistoryItem']
export type Decision = Schemas['decision.schema']
export type Classification = Schemas['classification.schema']
export type DecisionChain = Schemas['decision_chain.schema']
export type Task = Schemas['Task']
export type Followup = Schemas['Followup']
export type Problem = { type?: string; title?: string; status?: number; detail?: string; card?: string }

export type SimControl = NonNullable<paths['/api/sim/control']['post']['requestBody']>['content']['application/json']
export type HitlDecision = NonNullable<paths['/api/hitl/{id}']['post']['requestBody']>['content']['application/json']
export type JuryPayload = NonNullable<paths['/api/signals']['post']['requestBody']>['content']['application/json']
export type JuryResult = paths['/api/signals']['post']['responses'][202]['content']['application/json']

export class ApiError extends Error {
  status: number
  problem: Problem | null
  constructor(status: number, problem: Problem | null, fallback: string) {
    super(problem?.detail ?? problem?.title ?? fallback)
    this.status = status
    this.problem = problem
  }
  /** 501 — эндпоинт описан в OpenAPI, но карточка ещё не реализована (ответ Problem содержит card). */
  get notImplemented(): boolean {
    return this.status === 501
  }
}

export type Query = Record<string, string | number | boolean | string[] | null | undefined>

export function qs(params?: Query): string {
  if (!params) return ''
  const u = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === '') continue
    if (Array.isArray(v)) v.forEach((x) => u.append(k, x))
    else u.set(k, String(v))
  }
  const s = u.toString()
  return s ? `?${s}` : ''
}

export async function api<T>(path: string, init?: RequestInit & { query?: Query }): Promise<T> {
  const { query, ...rest } = init ?? {}
  const res = await fetch(`${path}${qs(query)}`, {
    ...rest,
    headers: { Accept: 'application/json, text/markdown', ...(rest.body ? { 'Content-Type': 'application/json' } : {}), ...rest.headers },
  })
  if (!res.ok) {
    let problem: Problem | null = null
    try {
      problem = (await res.json()) as Problem
    } catch {
      problem = null
    }
    throw new ApiError(res.status, problem, `${res.status} ${res.statusText}`)
  }
  if (res.status === 204) return undefined as T
  const ct = res.headers.get('content-type') ?? ''
  if (ct.includes('json')) return (await res.json()) as T
  return (await res.text()) as unknown as T
}

export const post = <T>(path: string, body: unknown, query?: Query) => api<T>(path, { method: 'POST', body: JSON.stringify(body), query })
