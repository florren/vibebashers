import { expect, test } from '@playwright/test'

for (const lang of ['ru','en'] as const) for (const theme of ['light','dark'] as const) {
  test(`actual jury creation and links ${lang}/${theme}`, async ({page,request},info)=>{
    const oldUi=(await(await request.get('/api/settings')).json()).ui??null
    const cityRows=await(await request.get('/api/refs/cities')).json(),city=cityRows[0]
    const clients=await(await request.get('/api/clients',{params:{limit:30}})).json(),client=clients[0]
    const external:string[]=[],unexpectedWrites:string[]=[],errors:string[]=[]
    let mediaCalls=0
    try{
      expect((await request.patch('/api/settings',{data:{ui:{layout:'v2',lang,mode:theme,theme_pack:'brand',attention:'calm'}}})).status()).toBe(200)
      await page.addInitScript(({lang,theme})=>{
        for(const[k,v]of Object.entries({'cx.lang':lang,'cx.ui.mode':theme,'cx.ui.layout':'v2','cx.ui.theme_pack':'brand','cx.ui.attention':'calm'}))localStorage.setItem(k,v)
      },{lang,theme})
      await page.exposeFunction('__unexpectedMic',()=>{mediaCalls++;throw new Error('Real media is forbidden in this proof')})
      await page.addInitScript(()=>{if(navigator.mediaDevices)Object.defineProperty(navigator.mediaDevices,'getUserMedia',{value:()=>((window as unknown as {__unexpectedMic:()=>Promise<never>}).__unexpectedMic())})})
      page.on('pageerror',error=>errors.push(error.message))
      await page.route('**/*',route=>{
        const req=route.request(),url=new URL(req.url())
        if(url.origin!==new URL(info.project.use.baseURL as string).origin){external.push(url.origin);return route.abort()}
        if(!['GET','HEAD'].includes(req.method())&&!(req.method()==='POST'&&url.pathname==='/api/signals')){unexpectedWrites.push(req.method()+' '+url.pathname);return route.abort()}
        return route.continue()
      })
      await page.goto('/overview')
      await page.getByRole('button',{name:lang==='ru'?'Новый сигнал':'New signal',exact:true}).click()
      const dialog=page.getByRole('dialog',{name:lang==='ru'?'Новый сигнал':'New signal'})
      await expect(dialog).toBeVisible()
      const input=dialog.getByRole('textbox',{name:lang==='ru'?'Текст обращения клиента':'Client request text',exact:true})
      await input.focus();await expect(input).toBeFocused()
      expect(await input.getAttribute('aria-describedby')).toBeTruthy()
      await expect(dialog.getByText(lang==='ru'?/Не вводите реальные персональные данные/:/Do not enter real personal data/)).toBeVisible()
      const send=dialog.getByRole('button',{name:lang==='ru'?'Отправить агенту':'Send to the agent',exact:true})
      await input.fill('😀😀');await expect(send).toBeDisabled()
      await input.fill('😀'.repeat(5001));await expect(send).toBeDisabled();expect([...await input.inputValue()]).toHaveLength(5001)
      const known=theme==='dark',manual=known&&lang==='en'
      const selector=dialog.getByRole('combobox',{name:lang==='ru'?'Клиент':'Client',exact:true})
      if(known){await expect(selector.locator(`option[value="${client.id}"]`)).toBeAttached();await selector.selectOption(manual?'manual':String(client.id));if(manual)await dialog.getByRole('textbox',{name:'Client ID',exact:true}).fill(String(client.id))}
      const citySelector=dialog.getByRole('combobox',{name:lang==='ru'?'Город':'City',exact:true})
      await expect(citySelector.locator(`option[value="${city.id}"]`)).toBeAttached();await citySelector.selectOption(String(city.id))
      const text=lang==='ru'?'Учебный вопрос: где узнать расписание отделения?':'Training question: where can I find branch opening hours?'
      await input.fill(text)
      const accepted=page.waitForResponse(res=>new URL(res.url()).pathname==='/api/signals'&&res.request().method()==='POST')
      await send.click();const response=await accepted
      expect(response.status()).toBe(202)
      const payload=response.request().postDataJSON(),result=await response.json()
      expect(payload).toEqual({channel_code:'chat',text,client_id:known?client.id:null,external_contact:{city_id:city.id,region_code:city.region_code}})
      expect(result.signal_id).toBeGreaterThan(0);expect(result.agent_run_id).toBeGreaterThan(0)
      await expect(dialog.getByRole('status')).toContainText(String(result.signal_id))
      const signal=await(await request.get(`/api/signals/${result.signal_id}`)).json()
      expect(signal.origin).toBe('jury');expect(signal.geo.city_id).toBe(city.id)
      const reference=signal.public_id
      expect(reference).toMatch(/^SIG-/)
      const journey=dialog.getByRole('link',{name:lang==='ru'?'Показать путь':'Show journey',exact:true})
      const trace=dialog.getByRole('link',{name:lang==='ru'?'Показать след':'Show trace',exact:true})
      await expect(journey).toHaveAttribute('href','/journey/'+reference)
      await expect(trace).toHaveAttribute('href','/trace/signal/'+result.signal_id)
      await page.screenshot({path:info.outputPath(`new-signal-${lang}-${theme}-desktop.png`)})
      await page.setViewportSize({width:360,height:800})
      await expect(dialog.getByRole('status')).toContainText(String(result.signal_id))
      await expect(input).toHaveValue(text)
      await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(360)
      await dialog.evaluate(node=>{node.scrollTop=0})
      await page.screenshot({path:info.outputPath(`new-signal-${lang}-${theme}-mobile-top.png`)})
      await trace.scrollIntoViewIfNeeded()
      await expect.poll(()=>dialog.evaluate(node=>node.scrollWidth-node.clientWidth)).toBeLessThanOrEqual(1)
      await page.screenshot({path:info.outputPath(`new-signal-${lang}-${theme}-mobile-result.png`)})
      const traceResponse=page.waitForResponse(res=>new URL(res.url()).pathname===`/api/trace/signal/${result.signal_id}`)
      await trace.click();expect((await traceResponse).status()).toBe(200)
      await expect(page).toHaveURL(new RegExp('/trace/signal/'+result.signal_id+'$'))
      const journeyResponse=await request.get('/api/journey/'+reference)
      expect(journeyResponse.status()).toBe(200)
      const journeyData=await journeyResponse.json()
      expect(journeyData.subject).toMatchObject({kind:'signal',ref:reference})
      expect(journeyData.stages).toHaveLength(8)
      const agent=await(await request.get(`/api/agent/runs/${result.agent_run_id}`)).json()
      const models=(agent.steps??[]).map((step:{model?:string|null})=>step.model).filter(Boolean)
      expect(models.length).toBeGreaterThan(0);expect(models.every((model:string)=>model.startsWith('mock'))).toBe(true)
      await info.attach('native-source.json',{body:JSON.stringify({lang,theme,signalId:result.signal_id,agentRunId:result.agent_run_id,selectedKnownClient:known,manual,cityId:city.id,origin:signal.origin,models,traceStatus:200,journeyStatus:200,mediaCalls,externalRequests:external.length,unexpectedWrites}),contentType:'application/json'})
      expect(mediaCalls).toBe(0);expect(external).toEqual([]);expect(unexpectedWrites).toEqual([]);expect(errors).toEqual([])
    }finally{expect((await request.post('/api/settings/import',{data:{settings:{ui:oldUi}}})).status()).toBe(200)}
  })
}

test('insecure local origin hides microphone without disabling text input',async({playwright,request},info)=>{
  const browser=await playwright.chromium.launch({args:['--host-resolver-rules=MAP cx-insecure.test 127.0.0.1','--no-proxy-server']})
  const page=await browser.newPage({viewport:{width:1440,height:1000}})
  const oldUi=(await(await request.get('/api/settings')).json()).ui??null
  try{
    expect((await request.patch('/api/settings',{data:{ui:{layout:'v2',lang:'en',mode:'light'}}})).status()).toBe(200)
    const local=new URL(info.project.use.baseURL as string);local.hostname='cx-insecure.test'
    // Только тестовый resolver Chromium направляет origin в loopback; native secureContext остаётся false.
    await page.addInitScript(()=>{localStorage.setItem('cx.lang','en');localStorage.setItem('cx.ui.layout','v2')})
    const writes:string[]=[],external:string[]=[]
    await page.route('**/*',route=>{const req=route.request(),url=new URL(req.url());if(url.origin!==local.origin){external.push(url.origin);return route.abort()}if(!['GET','HEAD'].includes(req.method())){writes.push(req.method()+' '+url.pathname);return route.abort()}return route.continue()})
    await page.goto(local.origin+'/overview')
    expect(await page.evaluate(()=>window.isSecureContext)).toBe(false)
    await page.getByRole('button',{name:'New signal',exact:true}).click()
    const dialog=page.getByRole('dialog',{name:'New signal'})
    await expect(dialog.getByText(/secure HTTPS or localhost/)).toBeVisible()
    await expect(dialog.getByRole('button',{name:'Dictate',exact:true})).toHaveCount(0)
    const text=dialog.getByRole('textbox',{name:'Client request text',exact:true})
    await text.fill('Training text remains available without microphone input')
    await expect(dialog.getByRole('button',{name:'Send to the agent',exact:true})).toBeEnabled()
    await page.screenshot({path:info.outputPath('new-signal-insecure-origin.png')})
    expect(writes).toEqual([]);expect(external).toEqual([])
  }finally{await browser.close();expect((await request.post('/api/settings/import',{data:{settings:{ui:oldUi}}})).status()).toBe(200)}
})
