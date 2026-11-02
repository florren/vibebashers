import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import i18n from '@/shared/i18n'
import { VoiceInput } from '../VoiceInput'

vi.mock('@/shared/api/hooks',()=>({useSttProviders:()=>({data:[]})}))
const instances: FakeRecognition[] = []
class FakeRecognition {
  lang='';continuous=false;interimResults=false
  onresult:((event:unknown)=>void)|null=null
  onend:(()=>void)|null=null
  start=vi.fn();stop=vi.fn();abort=vi.fn()
  constructor(){instances.push(this)}
  emit(text:string,final:boolean){this.onresult?.({resultIndex:0,results:[{isFinal:final,0:{transcript:text,confidence:.9}}]})}
}
beforeEach(async()=>{instances.length=0;await i18n.changeLanguage('en');vi.stubGlobal('isSecureContext',true);vi.stubGlobal('SpeechRecognition',FakeRecognition);vi.stubGlobal('fetch',vi.fn())})
afterEach(()=>{cleanup();vi.unstubAllGlobals()})
it('emits only known native final browser transcript metadata after explicit gesture',()=>{
 const text=vi.fn(),interim=vi.fn(),voice=vi.fn()
 render(<VoiceInput onText={text} onInterim={interim} onVoice={voice}/>)
 expect(instances).toHaveLength(0);expect(voice).not.toHaveBeenCalled()
 fireEvent.click(screen.getByRole('button',{name:i18n.t('voice.start')}))
 expect(instances).toHaveLength(1)
 const recognition=instances[0]!
 expect(recognition.start).toHaveBeenCalledOnce()
 recognition!.emit('Draft transcript',false)
 expect(interim).toHaveBeenCalledWith('Draft transcript');expect(text).not.toHaveBeenCalled();expect(voice).not.toHaveBeenCalled()
 recognition!.emit('First training phrase',true)
 expect(voice).toHaveBeenLastCalledWith({stt_provider:'browser',transcript_raw:'First training phrase'})
 recognition!.emit('Second training phrase',true)
 expect(text).toHaveBeenLastCalledWith('Second training phrase')
 expect(voice).toHaveBeenLastCalledWith({stt_provider:'browser',transcript_raw:'First training phrase Second training phrase'})
 const meta=voice.mock.calls.at(-1)![0]
 for(const key of ['duration_ms','latency_ms','avg_confidence','stt_model'])expect(meta).not.toHaveProperty(key)
 expect(fetch).not.toHaveBeenCalled()
})
