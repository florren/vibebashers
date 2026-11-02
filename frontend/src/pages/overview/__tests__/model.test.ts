import { expect, it } from 'vitest'
import { projectSignal, projectionPoint, signalAngle, customerWindow } from '../model'
import { maskBusinessText } from '@/shared/lib/privacy'
import { validateMetricsRun } from '@/shared/api/overview'
import { signal, overview } from './fixtures'

it('stable ID angle and negativity radius are independent of ordering/geography',()=>{
  const a=projectionPoint('SIG-000101',80), b=projectionPoint('SIG-000101',20)
  expect(Math.hypot(a.x-160,a.y-160)).toBeCloseTo(100)
  expect(Math.hypot(b.x-160,b.y-160)).toBeCloseTo(25)
  expect(Math.atan2(a.y-160,a.x-160)).toBeCloseTo(Math.atan2(b.y-160,b.x-160))
  expect(signalAngle('SIG-000101')).toBe(signalAngle('SIG-000101'))
  expect(signalAngle('SIG-000102')).not.toBe(signalAngle('SIG-000101'))
})
it('cache projection excludes raw text/contacts; unknown negativity never becomes0',()=>{
  const projected=projectSignal(signal)
  expect(projected).not.toHaveProperty('text');expect(projected).not.toHaveProperty('client');expect(projected).not.toHaveProperty('external_contact')
  expect(projectSignal({...signal,classification:null}).negativity).toBeNull()
  expect(projectSignal({...signal,classification:{...signal.classification!,negativity:NaN}}).negativity).toBeNull()
})
it('customer window excludes service anchors/future/start boundary, includes end',()=>{
  const row=projectSignal(signal), start=overview.window.starts_sim,end=overview.window.ends_sim
  expect(customerWindow([row,{...row,id:2,origin:'proactive'},{...row,id:3,received_sim:start},{...row,id:4,received_sim:'2026-11-09T09:00:01Z'},{...row,id:5,received_sim:end}],start,end).map(x=>x.id)).toEqual([101,5])
})
it('business text masks contacts before truncation',()=>{
  const text=maskBusinessText('Почта private@example.test, телефон +7 999 123-45-67, @someone')
  expect(text).not.toContain('private@example.test');expect(text).not.toContain('999 123');expect(text).not.toContain('@someone')
})
it.each(['',' ','\tcurrent','²','١','0','-1','9223372036854775808','1'.repeat(200)])('invalid explicit scope %s is rejected before qs can drop it',run=>expect(()=>validateMetricsRun(run)).toThrow())
it.each(['current','all','1','9223372036854775807'])('valid scope %s stays explicit',run=>expect(()=>validateMetricsRun(run)).not.toThrow())

it('Unicode contacts cannot bypass masking',()=>{
  const result=maskBusinessText('иван@пример.ru @никнейм +٧٩٩٩١٢٣٤٥٦٧')
  expect(result).not.toContain('иван@пример.ru');expect(result).not.toContain('@никнейм');expect(result).not.toContain('٧٩٩٩١٢٣٤٥٦٧')
})
