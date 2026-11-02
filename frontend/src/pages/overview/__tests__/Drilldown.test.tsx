import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import i18n from '@/shared/i18n'
import { api, ApiError } from '@/shared/api/client'
import { WorkspacePage } from '@/pages/workspace/WorkspacePage'
import { EconomicsPage } from '@/pages/finance/EconomicsPage'
import { EnginePage } from '@/pages/engine/EnginePage'
import { scopedAgentMembership } from '@/pages/engine/scoped'
import { overview, signal } from './fixtures'

vi.mock('@/shared/api/client',async original=>({...await original<typeof import('@/shared/api/client')>(),api:vi.fn()}))
vi.mock('@/widgets/LogPanel',()=>({LogPanel:({runId}:{runId:number|null})=><div data-testid="scoped-log">{runId}</div>}))
let queryClient:QueryClient, foreign=false, missing=false
beforeEach(async()=>{
  await i18n.changeLanguage('ru');foreign=false;missing=false
  queryClient=new QueryClient({defaultOptions:{queries:{retry:false,staleTime:Infinity}}})
  vi.mocked(api).mockReset().mockImplementation(async(path,options)=>{
    const requested=String(options?.query?.run_id??'current')
    if(path==='/api/metrics/overview'){
      if(requested==='404')throw new ApiError(404,{title:'Run not found'},'404')
      return {...overview,scope:{requested_run_id:requested,resolved_run_id:missing||requested==='all'?null:27,all_runs:requested==='all',current_missing:missing}}
    }
    if(path==='/api/sim/state')return {current_run_id:99,sim_time:overview.as_of_sim}
    if(path.startsWith('/api/refs/'))return []
    if(path==='/api/signals')return {items:[{...signal,text:'Учебный сигнал выбранного запуска'}],next_cursor:null}
    if(path==='/api/hitl/queue')return {items:[],next_cursor:null,total:0}
    if(path==='/api/metrics/dashboard')return {}
    if(path==='/api/agent/graph')return {version:'1',nodes:[],edges:[]}
    if(path==='/api/agent/runs')return {items:foreign?[]:[{id:12,signal_id:101,outcome:'completed'}],next_cursor:null}
    if(path==='/api/agent/runs/12')return {id:12,signal_id:101,steps:[]}
    if(path==='/api/agent/runs/12/decision-chain')return {agent_run_id:12,signal_id:101,router_action:'create',steps:[]}
    throw new Error(`Unexpected scoped endpoint: ${path}`)
  })
})
afterEach(()=>{cleanup();queryClient.clear()})
function mount(path:string){return render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={[path]}><Routes><Route path="/workspace" element={<WorkspacePage/>}/><Route path="/economics" element={<EconomicsPage/>}/><Route path="/engine/:runId?" element={<EnginePage/>}/></Routes></MemoryRouter></QueryClientProvider>)}
function noGlobalMoney(){expect(vi.mocked(api).mock.calls.some(([path])=>['/api/metrics/dashboard','/api/metrics/economics','/api/metrics/economics/fact','/api/metrics/economics/live','/api/metrics/economics/preview'].includes(path))).toBe(false)}

it('signals explicit27 uses27 and does not mount global KPI; all requires a selection',async()=>{
  mount('/workspace?tab=signals&run_id=27')
  await screen.findByText('Учебный сигнал выбранного запуска')
  const calls=vi.mocked(api).mock.calls.filter(([path])=>['/api/signals','/api/hitl/queue'].includes(path))
  expect(calls.length).toBeGreaterThan(0);for(const [,options]of calls)expect(options?.query?.run_id).toBe('27')
  noGlobalMoney()
  fireEvent.change(screen.getByLabelText(i18n.t('continuity.scope')),{target:{value:'all'}})
  await waitFor(()=>expect(vi.mocked(api).mock.calls.some(([path,options])=>path==='/api/signals'&&options?.query?.run_id==='all')).toBe(true))
})
it('legacy absent parameter keeps prior all feed and prior KPI',async()=>{
  mount('/workspace?tab=signals')
  await screen.findByText('Учебный сигнал выбранного запуска')
  expect(vi.mocked(api).mock.calls.some(([path,options])=>path==='/api/signals'&&options?.query?.run_id==='all')).toBe(true)
  expect(vi.mocked(api).mock.calls.some(([path])=>path==='/api/metrics/dashboard')).toBe(true)
})
it.each(['hitl','dashboard'])('workspace %s does not fall back to background global KPI/economy',async tab=>{
  mount(`/workspace?tab=${tab}&run_id=27`)
  await waitFor(()=>expect(vi.mocked(api).mock.calls.some(([path])=>path==='/api/metrics/overview')).toBe(true))
  if(tab==='hitl')await screen.findByText(i18n.t('hitl.empty'))
  else await screen.findByText('Метрики выбранного запуска')
  noGlobalMoney()
  for(const [path,options]of vi.mocked(api).mock.calls)if(path==='/api/hitl/queue')expect(options?.query?.run_id).toBe('27')
})
it('economics explicit27 displays exact saved amount and never mounts global assumptions',async()=>{
  mount('/economics?run_id=27')
  await screen.findByText('Метрики выбранного запуска')
  expect(screen.getByText('10 999 999 999 999,67 ₽')).toBeInTheDocument()
  noGlobalMoney();expect(vi.mocked(api).mock.calls.some(([path])=>path==='/api/settings/economics')).toBe(false)
})
it.each(['','²','404'])('invalid/unknown explicit scope %s never starts child queries',async scope=>{
  mount('/workspace?tab=signals&run_id='+encodeURIComponent(scope))
  await waitFor(()=>expect(screen.getByText(i18n.t('care.errors.request'))).toBeInTheDocument())
  expect(vi.mocked(api).mock.calls.some(([path])=>['/api/signals','/api/hitl/queue','/api/metrics/dashboard'].includes(path))).toBe(false)
})
it('missing current does not mount legacy workspace or global fallback',async()=>{
  missing=true;mount('/workspace?run_id=current')
  await screen.findByText(/Текущий запуск не выбран/)
  expect(vi.mocked(api).mock.calls.every(([path])=>path==='/api/metrics/overview')).toBe(true)
})
it('foreign agent ID never requests detail/chain/log; own agent does',async()=>{
  foreign=true;mount('/engine/12?run_id=27')
  await screen.findByText('Этот запуск агента не найден в выбранном срезе')
  expect(vi.mocked(api).mock.calls.some(([path])=>path==='/api/agent/runs/12'||path==='/api/agent/runs/12/decision-chain')).toBe(false)
  expect(screen.queryByTestId('scoped-log')).not.toBeInTheDocument()
})
it('membership walks subsequent scoped keyset pages rather than rejecting an older run',async()=>{
  vi.mocked(api).mockResolvedValueOnce({items:[{id:11}],next_cursor:'11'}).mockResolvedValueOnce({items:[{id:12}],next_cursor:null})
  await expect(scopedAgentMembership(12,'27')).resolves.toBe(true)
  expect(vi.mocked(api).mock.calls.map(([,options])=>options?.query)).toEqual([{run_id:'27',q:'AR-12',kind:'agent',limit:100,cursor:undefined},{run_id:'27',q:'AR-12',kind:'agent',limit:100,cursor:'11'}])
})
it('repeated cursor is an explicit protocol error, not endless loading',async()=>{
  vi.mocked(api).mockResolvedValue({items:[],next_cursor:'same'})
  await expect(scopedAgentMembership(12,'27')).rejects.toThrow('Invalid agent pagination cursor')
})
