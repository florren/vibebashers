import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import i18n from '@/shared/i18n'
import { api, ApiError } from '@/shared/api/client'
import { assertBlockBudget } from '@/shared/ui/motion'
import { useUiTheme } from '@/shared/theming/store'
import { useWs } from '@/shared/ws/client'
import { OverviewPage } from '../OverviewPage'
import { cx, overview, signal } from './fixtures'

vi.mock('@/shared/api/client',async original=>({...await original<typeof import('@/shared/api/client')>(),api:vi.fn()}))
vi.mock('../OverviewChart',()=>({OverviewChart:({kind}:{kind:string})=><div data-testid={`chart-${kind}`} />}))
let current=structuredClone(overview), index=structuredClone(cx), failure=false
let client:QueryClient
beforeEach(async()=>{
  current=structuredClone(overview);index=structuredClone(cx);failure=false
  await i18n.changeLanguage('ru');useUiTheme.setState({attention:'calm',theme_pack:'brand'});useWs.setState({status:'open'})
  client=new QueryClient({defaultOptions:{queries:{retry:false}}})
  vi.mocked(api).mockReset().mockImplementation(async(path,options)=>{
    if(path==='/api/metrics/overview'){if(failure)throw new ApiError(422,{title:'Invalid scope'},'422');return current}
    if(path==='/api/metrics/cx-index')return index
    if(path==='/api/sim/runs')return {items:[{id:27,kind:'free',label:'Mock fixture'}]}
    if(path==='/api/signals')return {items:[signal],next_cursor:null}
    if(path==='/api/agent/runs')return {items:[{id:12,signal_id:101,outcome:'completed'}]}
    if(path==='/api/agent/runs/12/decision-chain')return {agent_run_id:12,signal_id:101,router_action:'create',llm_source:'mock',steps:[{step:1,node:'classify',why_ru:'Скрыть private@example.test, +7 999 123-45-67'}]}
    if(path==='/api/hitl/queue')return {items:[1,2,3,4].map(id=>({id,public_id:`HD-${id}`,reason:'low_confidence',waiting_minutes:id,signal:{id:101,public_id:signal.public_id}}))}
    throw new Error(`Unmocked endpoint ${path} ${JSON.stringify(options?.query)}`)
  })
})
afterEach(()=>{cleanup();client.clear();document.documentElement.removeAttribute('data-circadian');document.documentElement.removeAttribute('data-phase')})
function mount(path='/overview'){return render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[path]}><OverviewPage /></MemoryRouter></QueryClientProvider>)}

it('renders exactly9blocks with API index/exact money, 3HITL and actual links; no monetary producer',async()=>{
  const {container}=mount()
  await waitFor(()=>expect(container.querySelector('[data-cx-index]')).toHaveTextContent('47'))
  expect(container.querySelectorAll('[data-block]')).toHaveLength(9)
  expect(()=>assertBlockBudget(container)).not.toThrow()
  expect(container.querySelector('[data-kpi="signalsToday"]')).toHaveTextContent('5')
  expect(screen.getByText('10 999 999 999 999,67 ₽',{exact:false})).toBeTruthy()
  expect(screen.getAllByText(/^HD-/)).toHaveLength(3)
  expect(screen.queryByText('HD-4')).not.toBeInTheDocument()
  expect(screen.getByRole('link',{name:'Показать след'})).toHaveAttribute('href','/trace/signal/101?run_id=27')
  expect(screen.getAllByRole('link',{name:'Показать путь'})[0]).toHaveAttribute('href','/journey/101?run_id=27')
  expect(container).not.toHaveTextContent('private@example.test')
  expect(vi.mocked(api).mock.calls.every(([path])=>!['/api/metrics/dashboard','/api/metrics/economics','/api/metrics/economics/live'].includes(path))).toBe(true)
  for(const [path,options] of vi.mocked(api).mock.calls){if(['/api/signals','/api/agent/runs','/api/hitl/queue','/api/metrics/cx-index'].includes(path))expect(options?.query?.run_id).toBe('27')}
})
it('missing current disables all full links and never fetches a global child',async()=>{
  current.scope={requested_run_id:'current',resolved_run_id:null,all_runs:false,current_missing:true}
  const {container}=mount()
  await screen.findByText(/Текущий запуск не выбран/)
  expect(container.querySelectorAll('[data-block] a')).toHaveLength(0)
  expect(vi.mocked(api).mock.calls.some(([path])=>['/api/signals','/api/agent/runs','/api/hitl/queue','/api/metrics/cx-index'].includes(path))).toBe(false)
})
it('invalid scope/error is explicit and does not reuse another run children',async()=>{
  failure=true;const {container}=mount('/overview?run_id=404')
  await screen.findByText('Invalid scope')
  expect(container.querySelectorAll('[data-block] a')).toHaveLength(0)
  expect(vi.mocked(api).mock.calls.some(([path])=>path==='/api/signals')).toBe(false)
})
it('unknown components remain a dash and do not use observed partial numbers',async()=>{
  index.index=null;index.delta_hour=null;index.components.negativity={...index.components.negativity,value:null,observed_value:80,known:1,total:5,status:'partial'}
  current.kpi.saved_rub_exact=null
  const {container}=mount()
  await waitFor(()=>expect(container.querySelector('[data-cx-index]')).toHaveTextContent('—'))
  await waitFor(()=>expect(container.querySelector('[data-kpi="saved"]')).toHaveTextContent('—'))
})
it('English copy and saved summary preserve honest mode/source text',async()=>{
  await i18n.changeLanguage('en');mount()
  await screen.findByRole('heading',{name:'Customer tension'})
  expect(screen.getByText('Demonstration CX Index')).toBeInTheDocument()
  fireEvent.click(screen.getByText('Expand saved agent text'))
  expect(await screen.findByText('Сохранённая учебная сводка')).toBeInTheDocument()
  expect(screen.getByText(/no new model call/)).toBeInTheDocument()
})
it('night digest is inside feed block and uses the resolved run scope',async()=>{
  document.documentElement.dataset.circadian='true';document.documentElement.dataset.phase='night'
  const {container}=mount()
  const digest=await screen.findByTestId('overview-night-digest')
  expect(digest.closest('[data-block]')).toHaveAttribute('data-block','overview-feed')
  await waitFor(()=>expect(vi.mocked(api).mock.calls.some(([path,options])=>path==='/api/signals'&&options?.query?.criticality==='high'&&options.query.run_id==='27')).toBe(true))
  expect(()=>assertBlockBudget(container)).not.toThrow()
})

it('control room remains nine finite blocks and preserves explicit mode override',async()=>{
  useUiTheme.setState({attention:'control_room',theme_pack:'brand'})
  const {container}=mount()
  await waitFor(()=>expect(container.querySelector('[data-kpi="signalsToday"]')).toHaveTextContent('5'))
  expect(container.querySelector('[data-overview]')).toHaveAttribute('data-attention','control_room')
  expect(container.querySelectorAll('[data-block]')).toHaveLength(9)
  expect(()=>assertBlockBudget(container)).not.toThrow()
})

it('explicit numeric run outside the first options page never displays current/all instead',async()=>{
  mount('/overview?run_id=456')
  const selector=screen.getByLabelText('Запуск')
  expect(selector).toHaveValue('456')
  expect(screen.getByRole('option',{name:'#456'})).toBeInTheDocument()
})
