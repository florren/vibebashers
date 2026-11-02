import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import i18n from '@/shared/i18n'
import { JuryModal } from '../JuryModal'

const state = vi.hoisted(() => ({ mutate: vi.fn(), reset: vi.fn(), data: undefined as undefined | {signal_id:number;agent_run_id:number}, pending:false }))
vi.mock('@/shared/api/hooks',()=>({
  useRefs:(name:string)=>({data:name==='cities'?[{id:7,name_ru:'Казань',region_code:'16'}]:name==='channels'?[{code:'chat',name_ru:'Чат',name_en:'Chat'},{code:'social',name_ru:'Соцсети',name_en:'Social media'}]:[{code:'mass',name_ru:'Массовый',name_en:'Mass market'}]}),
  useClients:()=>({data:[{id:42,display_name:'Учебный клиент',city_name:'Казань',public_id:'CL-000042'}]}),
  useJury:()=>({mutate:state.mutate,reset:state.reset,data:state.data,isPending:state.pending,isError:false}),
}))
vi.mock('@/shared/audio/VoiceInput',()=>({VoiceInput:({onText,onVoice}:{onText:(text:string)=>void;onVoice:(meta:unknown)=>void})=><button type="button" onClick={()=>{onText('Voice training transcript');onVoice({stt_provider:'vosk',transcript_raw:'Voice training transcript',duration_ms:2000,latency_ms:10})}}>Voice fixture</button>}))
const close=vi.fn()
function mount(onSignal?: (id:number)=>void){return render(<MemoryRouter><JuryModal open onClose={close} onSignal={onSignal}/></MemoryRouter>)}
beforeEach(async()=>{await i18n.changeLanguage('en');state.data=undefined;state.pending=false;state.mutate.mockReset();state.reset.mockReset();close.mockReset()})
afterEach(cleanup)

it('preserves the typed POST payload, explicit unknown and city; no extra policy values',()=>{
  mount();fireEvent.change(screen.getByRole('combobox',{name:'City'}),{target:{value:'7'}})
  fireEvent.change(screen.getByRole('textbox',{name:/Client request text/}),{target:{value:'  Training complaint  '}})
  fireEvent.click(screen.getByRole('button',{name:'Send to the agent'}))
  expect(state.mutate).toHaveBeenCalledOnce();expect(state.mutate).toHaveBeenCalledWith({channel_code:'chat',text:'Training complaint',client_id:null,external_contact:{city_id:7,region_code:'16'}})
  expect(screen.getByText(/Do not enter real personal data/)).toBeVisible()
  expect(screen.getByText(/determine the message sentiment/)).toBeVisible()
})
it('chooses a real client; unknown explicitly clears a prior binding',()=>{
  mount();const client=screen.getByRole('combobox',{name:'Client'})
  fireEvent.change(client,{target:{value:'42'}});fireEvent.change(screen.getByRole('textbox',{name:/Client request text/}),{target:{value:'Training client message'}})
  fireEvent.click(screen.getByRole('button',{name:'Send to the agent'}));expect(state.mutate.mock.calls[0]![0].client_id).toBe(42)
  fireEvent.change(client,{target:{value:''}});fireEvent.click(screen.getByRole('button',{name:'Send to the agent'}));expect(state.mutate.mock.calls[1]![0].client_id).toBeNull()
})
it.each(['0','-1','1.5','1e2','²','9007199254740992'])('rejects invalid manual client %s without a request',value=>{
  mount();fireEvent.change(screen.getByRole('combobox',{name:'Client'}),{target:{value:'manual'}})
  fireEvent.change(screen.getByRole('textbox',{name:'Client ID'}),{target:{value}})
  fireEvent.change(screen.getByRole('textbox',{name:/Client request text/}),{target:{value:'Training message'}})
  expect(screen.getByRole('button',{name:'Send to the agent'})).toBeDisabled();expect(state.mutate).not.toHaveBeenCalled()
})
it.each([[2,false],[3,true],[5000,true],[5001,false]])('matches Python code-point text boundary %i without truncation',(count,valid)=>{
  mount();const field=screen.getByRole('textbox',{name:/Client request text/}),value='😀'.repeat(count)
  fireEvent.change(field,{target:{value}});expect(field).toHaveValue(value)
  const submit=screen.getByRole('button',{name:'Send to the agent'});if(valid)expect(submit).toBeEnabled();else expect(submit).toBeDisabled()
  fireEvent.click(submit);if(valid)expect(state.mutate.mock.calls[0]![0].text).toBe(value);else expect(state.mutate).not.toHaveBeenCalled()
})
it('submits voice provenance from VoiceInput only after its explicit gesture',()=>{
  mount();expect(state.mutate).not.toHaveBeenCalled();fireEvent.click(screen.getByRole('button',{name:'Voice fixture'}))
  fireEvent.click(screen.getByRole('button',{name:'Send to the agent'}))
  expect(state.mutate.mock.calls[0]![0].voice_meta).toEqual({stt_provider:'vosk',transcript_raw:'Voice training transcript',duration_ms:2000,latency_ms:10})
})
it('shows actual result Journey/Trace/Engine links and retains optional signal action',()=>{
  state.data={signal_id:123,agent_run_id:44};const signal=vi.fn();mount(signal)
  expect(screen.getByRole('link',{name:i18n.t('journeyModes.open')})).toHaveAttribute('href','/journey/SIG-000123')
  expect(screen.getByRole('link',{name:'Show trace'})).toHaveAttribute('href','/trace/signal/123')
  expect(screen.getByRole('link',{name:'Open under the hood'})).toHaveAttribute('href','/engine/44')
  fireEvent.click(screen.getByRole('button',{name:'Open signal'}));expect(signal).toHaveBeenCalledWith(123);expect(close).toHaveBeenCalledOnce()
})
it('renders Russian labels and blocks repeated pending submit',async()=>{
  await i18n.changeLanguage('ru');state.pending=true;mount()
  expect(screen.getByRole('dialog',{name:'Новый сигнал'})).toBeVisible();expect(screen.getByRole('combobox',{name:'Город'})).toBeDisabled()
  expect(screen.getByRole('button',{name:'Агент думает…'})).toBeDisabled();expect(state.mutate).not.toHaveBeenCalled()
})

it('accepts a leading-zero manual ID without silently choosing anonymous',()=>{
 mount();fireEvent.change(screen.getByRole('combobox',{name:'Client'}),{target:{value:'manual'}})
 fireEvent.change(screen.getByRole('textbox',{name:'Client ID'}),{target:{value:' 00042 '}})
 fireEvent.change(screen.getByRole('textbox',{name:/Client request text/}),{target:{value:'Training client request'}})
 fireEvent.click(screen.getByRole('button',{name:'Send to the agent'}))
 expect(state.mutate.mock.calls[0]![0].client_id).toBe(42)
})
it('includes anonymous handle only for its selected channel, preserving city separately',()=>{
 mount();fireEvent.change(screen.getByRole('combobox',{name:'Channel'}),{target:{value:'social'}})
 fireEvent.click(screen.getByText('Refine client and source'))
 fireEvent.change(screen.getByRole('textbox',{name:/Handle \/ contact/}),{target:{value:'@training_handle'}})
 fireEvent.change(screen.getByRole('textbox',{name:/Client request text/}),{target:{value:'Training source request'}})
 fireEvent.click(screen.getByRole('button',{name:'Send to the agent'}))
 expect(state.mutate.mock.calls[0]![0].external_contact).toEqual({nick:'@training_handle'})
 fireEvent.change(screen.getByRole('combobox',{name:'Channel'}),{target:{value:'chat'}})
 fireEvent.click(screen.getByRole('button',{name:'Send to the agent'}))
 expect(state.mutate.mock.calls[1]![0]).not.toHaveProperty('external_contact')
})
