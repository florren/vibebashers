import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import i18n from '@/shared/i18n'
import { PersonalChat } from './PersonalChat'

vi.mock('@/shared/audio/VoiceInput', () => ({ VoiceInput: ({onText}:{onText:(text:string)=>void}) => <button type="button" onClick={()=>onText('Надиктованное обращение')}>Надиктовать</button> }))
const boot={form_token:'a'.repeat(64),tag:'ui_pers_demo',minimum_form_ms:2000,products:[{code:'debit_card',name_ru:'Дебетовая карта',name_en:'Debit card'}],regions:[{code:'77',name_ru:'Москва'},{code:'78',name_ru:'Санкт-Петербург'}],cities:[{id:1,name_ru:'Москва',region_code:'77'},{id:2,name_ru:'Санкт-Петербург',region_code:'78'}]}
let history={messages:[] as {public_id:string;text:string;status:string;received_at:string}[],answers:[] as {id:number;text:string;at:string}[]}
const fetcher=vi.fn<typeof fetch>()
beforeEach(async()=>{
 await i18n.changeLanguage('ru')
 history={messages:[],answers:[]}
 vi.stubGlobal('crypto',{randomUUID:()=> 'e701596b-393e-4d50-8f7a-e4937df31231'})
 fetcher.mockImplementation(async(input,options)=>{
  const path=String(input)
  if(path==='/api/personal/session')return new Response(JSON.stringify(boot),{status:200})
  if(path==='/api/personal/messages'&&!options?.method)return new Response(JSON.stringify(history),{status:200})
  if(path==='/api/personal/messages'){
   const body=JSON.parse(String(options?.body))
   history={messages:[{public_id:'SIG-000001',text:body.text,status:'answered',received_at:'2026-10-30T12:00:00Z'}],answers:[{id:1,text:'Агент получил сообщение и проверил условия.',at:'2026-10-30T12:00:01Z'}]}
   return new Response(JSON.stringify({accepted:true,public_id:'SIG-000001'}),{status:202})
  }
  throw new Error(`Unexpected public request: ${path}`)
 })
 vi.stubGlobal('fetch',fetcher)
})
afterEach(()=>{cleanup();vi.unstubAllGlobals();vi.clearAllMocks()})
function mount(){const qc=new QueryClient({defaultOptions:{queries:{retry:false},mutations:{retry:false}}});render(<QueryClientProvider client={qc}><PersonalChat/></QueryClientProvider>);return qc}

it('отправляет анонимное обращение и показывает реальный ответ собственного API без операторской навигации',async()=>{
 mount()
 expect(await screen.findByRole('option',{name:'Дебетовая карта'})).toBeInTheDocument()
 expect(screen.queryByText('Рабочее место')).not.toBeInTheDocument()
 fireEvent.change(screen.getByLabelText('Продукт'),{target:{value:'debit_card'}})
 fireEvent.change(screen.getByLabelText('Регион'),{target:{value:'77'}})
 expect(screen.queryByRole('option',{name:'Санкт-Петербург'})).toBeInTheDocument() // регион есть, чужой город не добавлен
 expect(screen.getByLabelText('Город').querySelectorAll('option')).toHaveLength(2)
 fireEvent.change(screen.getByLabelText('Город'),{target:{value:'1'}})
 fireEvent.change(screen.getByLabelText('Ваше сообщение'),{target:{value:'Расскажите про условия карты'}})
 fireEvent.click(screen.getByRole('button',{name:/^Отправить$/}))
 expect(await screen.findByText('Агент получил сообщение и проверил условия.')).toBeInTheDocument()
 const call=fetcher.mock.calls.find(([,options])=>options?.method==='POST')
 expect(JSON.parse(String(call?.[1]?.body))).toMatchObject({text:'Расскажите про условия карты',product_code:'debit_card',region_code:'77',city_id:1,form_token:boot.form_token,website:'',voice:false})
 expect(JSON.parse(String(call?.[1]?.body))).not.toHaveProperty('client_id')
 expect(fetcher.mock.calls.every(([path])=>String(path).startsWith('/api/personal/'))).toBe(true)
})

it('добавляет диктовку в текст и не теряет его при ошибке отправки',async()=>{
 mount();await screen.findByRole('option',{name:'Дебетовая карта'})
 fireEvent.click(screen.getByRole('button',{name:'Надиктовать'}))
 expect(screen.getByLabelText('Ваше сообщение')).toHaveValue('Надиктованное обращение')
 const original=fetcher.getMockImplementation()!
 fetcher.mockImplementation(async(input,options)=>options?.method==='POST'?new Response(JSON.stringify({title:'Сервис временно недоступен'}),{status:503}):original(input,options))
 fireEvent.click(screen.getByRole('button',{name:/^Отправить$/}))
 expect(await screen.findByRole('alert')).toHaveTextContent('Сервис временно недоступен')
 expect(screen.getByLabelText('Ваше сообщение')).toHaveValue('Надиктованное обращение')
 await waitFor(()=>expect(fetcher.mock.calls.some(([,options])=>options?.method==='POST'&&JSON.parse(String(options.body)).voice===true)).toBe(true))
})
