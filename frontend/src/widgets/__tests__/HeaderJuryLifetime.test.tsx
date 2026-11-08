import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import i18n from '@/shared/i18n'
import { Header } from '../Header'

const layout=vi.hoisted(()=>({mobile:false}))
vi.mock('@/shared/layout/device-store',async original=>({...await original<typeof import('@/shared/layout/device-store')>(),useMobileLayout:()=>layout.mobile}))
vi.mock('@/shared/theme',()=>({ThemeSelector:()=>null}))
vi.mock('@/shared/layout/device',()=>({DeviceSelector:()=>null}))
vi.mock('@/shared/layout/RoleSelector',()=>({RoleSelector:()=>null}))
vi.mock('@/shared/components/GlobalSearch',()=>({GlobalSearch:()=>null}))
vi.mock('@/shared/api/hooks',()=>({useBaselineRestore:()=>({reset:vi.fn(),isPending:false}),useSimState:()=>({data:undefined}),useSimControl:()=>({mutate:vi.fn(),isPending:false}),useDemoStatus:()=>({data:undefined})}))
vi.mock('../JuryModal',async()=>{
 const{useState}=await import('react')
 return{JuryModal:({open}:{open:boolean})=>{
  const[draft,setDraft]=useState(''),[accepted,setAccepted]=useState(false)
  return open?<div role="dialog"><label>Fixture draft<input value={draft} onChange={event=>setDraft(event.target.value)}/></label><button onClick={()=>setAccepted(true)}>Fixture accept</button>{accepted&&<a href="/trace/signal/123">Fixture result</a>}</div>:null
 }}
})
beforeEach(async()=>{layout.mobile=false;await i18n.changeLanguage('en')})
afterEach(cleanup)
it.each([false,true])('keeps draft and accepted result through desktop/mobile changes v2=%s',v2=>{
 const client=new QueryClient({defaultOptions:{queries:{retry:false}}})
 const tree=()=> <QueryClientProvider client={client}><MemoryRouter><Header v2={v2}/></MemoryRouter></QueryClientProvider>
 const ui=render(tree())
 fireEvent.click(screen.getByRole('button',{name:v2?'New signal':'Jury mode'}))
 const field=screen.getByRole('textbox',{name:'Fixture draft'})
 fireEvent.change(field,{target:{value:'Training draft must survive resize'}})
 fireEvent.click(screen.getByRole('button',{name:'Fixture accept'}))
 for(const mobile of [true,false]){
  layout.mobile=mobile;ui.rerender(tree())
  expect(screen.getByRole('textbox',{name:'Fixture draft'})).toBe(field)
  expect(field).toHaveValue('Training draft must survive resize')
  expect(screen.getByRole('link',{name:'Fixture result'})).toHaveAttribute('href','/trace/signal/123')
 }
 client.clear()
})
