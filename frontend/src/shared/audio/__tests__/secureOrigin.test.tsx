import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import i18n from '@/shared/i18n'
import { microphoneOriginAllowed } from '../mic'
import { VoiceInput } from '../VoiceInput'
import { webSpeechSupported } from '../webSpeech'

vi.mock('@/shared/api/hooks',()=>({useSttProviders:()=>({data:[{code:'vosk',available:true}]})}))
beforeEach(async()=>{await i18n.changeLanguage('en')})
afterEach(()=>{cleanup();vi.unstubAllGlobals()})
it.each([
 ['https:','bank.example',true,true],['https:','bank.example',false,false],
 ['http:','localhost',true,true],['http:','localhost',false,false],
 ['http:','127.0.0.1',true,true],['http:','[::1]',true,true],
 ['http:','bank.example',false,false],['http:','bank.example',true,false],
 ['http:','localhost.evil.example',true,false],['file:','',true,false],
])('honors native secureContext for %s//%s (%s)',(protocol,hostname,secure,allowed)=>{
 expect(microphoneOriginAllowed({protocol,hostname},secure)).toBe(allowed)
})
it('does not expose a browser SpeechRecognition bypass in an insecure native context',()=>{
 const recognition=vi.fn(),media=vi.fn()
 vi.stubGlobal('isSecureContext',false);vi.stubGlobal('SpeechRecognition',recognition)
 vi.stubGlobal('navigator',{mediaDevices:{getUserMedia:media}})
 expect(webSpeechSupported()).toBe(true)
 render(<VoiceInput onText={vi.fn()}/>)
 expect(screen.queryByRole('button')).not.toBeInTheDocument();expect(screen.getByText(/secure HTTPS or localhost/)).toBeVisible()
 expect(recognition).not.toHaveBeenCalled();expect(media).not.toHaveBeenCalled()
})
