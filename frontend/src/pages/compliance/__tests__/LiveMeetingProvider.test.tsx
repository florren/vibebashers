import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import i18n from '@/shared/i18n'
import type { SttProvider } from '@/shared/api/client'
import { LiveMeeting } from '../LiveMeeting'

const source=vi.hoisted(()=>({rows:[] as SttProvider[],error:false,start:vi.fn()}))
vi.mock('@/shared/api/hooks',()=>({
 useSttProviders:()=>({data:source.rows,isError:source.error,error:source.error?new Error('Fixture protocol failure'):null}),
 useComplianceBranches:()=>({data:[{id:1,code:'BR-MSK-01',city_name:'Учебный город',employees:[{id:7,display_name:'Учебный сотрудник',position:'Менеджер',is_active:true}]}]}),
 useRefs:()=>({data:[]}),useStartMicSession:()=>({mutateAsync:source.start,isPending:false}),
}))
vi.mock('@/shared/audio/mic',async original=>({...await original<typeof import('@/shared/audio/mic')>(),micSupported:()=>true,startMic:vi.fn()}))
beforeEach(async()=>{await i18n.changeLanguage('en');source.rows=[{code:'browser',available:true,is_default:false,external_service:true}];source.error=false;source.start.mockReset();vi.stubGlobal('isSecureContext',true);vi.stubGlobal('SpeechRecognition',vi.fn())})
afterEach(()=>{cleanup();vi.unstubAllGlobals()})
function mount(){return render(<LiveMeeting onClose={vi.fn()}/>)}
it('does not auto-select browser merely because it is available',()=>{
 mount();expect(screen.getByRole('combobox',{name:i18n.t('live.provider')})).toHaveValue('')
 expect(screen.getByRole('button',{name:i18n.t('live.start')})).toBeDisabled();expect(source.start).not.toHaveBeenCalled()
})
it('selects only the authoritative available offline default',()=>{
 source.rows.push({code:'vosk',available:true,is_default:true})
 mount();expect(screen.getByRole('combobox',{name:i18n.t('live.provider')})).toHaveValue('vosk')
 expect(source.start).not.toHaveBeenCalled()
})
it('preserves explicit browser opt-in across refetch, but disables unavailable/error starts',()=>{
 const view=mount(),select=screen.getByRole('combobox',{name:i18n.t('live.provider')})
 fireEvent.change(select,{target:{value:'browser'}})
 expect(screen.getByText(/audio is sent to the browser/)).toBeVisible()
 source.rows=[{code:'browser',available:true,is_default:false,external_service:true},{code:'vosk',available:true,is_default:true}]
 view.rerender(<LiveMeeting onClose={vi.fn()}/>);expect(select).toHaveValue('browser')
 source.error=true;view.rerender(<LiveMeeting onClose={vi.fn()}/>)
 expect(select).toHaveValue('browser');expect(screen.getByRole('button',{name:i18n.t('live.start')})).toBeDisabled()
 expect(source.start).not.toHaveBeenCalled()
})
