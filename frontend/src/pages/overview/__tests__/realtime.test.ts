import { QueryClient } from '@tanstack/react-query'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { connectWs } from '@/shared/ws/client'

class Socket {
  static OPEN=1
  static current:Socket
  readyState=1
  onopen:(()=>void)|null=null
  onmessage:((event:{data:string})=>void)|null=null
  onclose:(()=>void)|null=null
  onerror:(()=>void)|null=null
  send=vi.fn();close=vi.fn()
  constructor(){Socket.current=this}
}
let client:QueryClient,stop:()=>void
beforeEach(()=>{
  vi.useFakeTimers();vi.stubGlobal('WebSocket',Socket)
  client=new QueryClient()
  client.setQueryData(['metrics','overview','27'],{})
  client.setQueryData(['metrics','cx-index','27'],{})
  client.setQueryData(['metrics','dashboard','run'],{})
  stop=connectWs(client)
})
afterEach(()=>{stop();client.clear();vi.unstubAllGlobals();vi.useRealTimers()})
it.each([['sim','sim.tick'],['signals','signal.classified'],['agent','run_finished']])('native %s refreshes readonly Overview/CX without invalidating legacy monetary dashboard',async(topic,type)=>{
  Socket.current.onmessage?.({data:JSON.stringify({topic,type,ts:'2026-11-09T09:00:00Z',run_id:27,data:{sim_time:'2026-11-09T09:00:00Z'}})})
  expect(client.getQueryState(['metrics','overview','27'])?.isInvalidated).toBe(false)
  await vi.advanceTimersByTimeAsync(250)
  expect(client.getQueryState(['metrics','overview','27'])?.isInvalidated).toBe(true)
  expect(client.getQueryState(['metrics','cx-index','27'])?.isInvalidated).toBe(true)
  expect(client.getQueryState(['metrics','dashboard','run'])?.isInvalidated).toBe(false)
})
