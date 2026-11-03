import { expect, test } from '@playwright/test'
import { formatExactRub } from '../src/shared/lib/exactMoney'

const requested = process.env.E2E_OVERVIEW_RUN_ID ?? 'current'
for (const pack of ['brand','ops'] as const) for (const lang of ['ru','en'] as const) for (const mode of ['light','dark'] as const) {
  test(`overview actual nine blocks ${pack}/${lang}/${mode}`, async ({page,request},info)=>{
    const settings=await(await request.get('/api/settings')).json()
    const oldUi=settings.ui??null, attention=pack==='ops'?'control_room':'calm'
    const writes:string[]=[],external:string[]=[],errors:string[]=[],forbiddenQueries:string[]=[]
    try {
      // Fixture setup идёт ДО readonly browser phase; import восстанавливает весь namespace.
      expect((await request.patch('/api/settings',{data:{ui:{layout:'v2',lang,mode,theme_pack:pack,attention}}})).status()).toBe(200)
      page.on('pageerror',error=>errors.push(error.message))
      page.on('request',req=>{const url=new URL(req.url());if(['/api/metrics/dashboard','/api/metrics/economics','/api/metrics/economics/live','/api/metrics/economics/fact','/api/metrics/economics/preview'].includes(url.pathname))forbiddenQueries.push(url.pathname)})
      await page.route('**/*',route=>{const req=route.request(),url=new URL(req.url());if(url.origin!==new URL(info.project.use.baseURL as string).origin){external.push(url.origin);return route.abort()}if(!['GET','HEAD'].includes(req.method())){writes.push(req.method()+' '+url.pathname);return route.abort()}return route.continue()})
      await page.addInitScript(({lang,mode,pack,attention})=>{localStorage.setItem('cx.lang',lang);localStorage.setItem('cx.ui.mode',mode);localStorage.setItem('cx.ui.theme_pack',pack);localStorage.setItem('cx.ui.layout','v2');localStorage.setItem('cx.ui.attention',attention);localStorage.setItem('cx.ui.role','cx_lead')},{lang,mode,pack,attention})
      await page.emulateMedia({reducedMotion:mode==='dark'?'reduce':'no-preference'})
      const matchesRun=(url:URL)=>requested==='current'?/^[1-9][0-9]*$/.test(url.searchParams.get('run_id')??''):url.searchParams.get('run_id')===requested
      const renderedOverview=page.waitForResponse(response=>{const url=new URL(response.url());return url.pathname==='/api/metrics/overview'&&url.searchParams.get('run_id')===requested})
      const renderedCx=page.waitForResponse(response=>{const url=new URL(response.url());return url.pathname==='/api/metrics/cx-index'&&matchesRun(url)})
      const renderedSignals=page.waitForResponse(response=>{const url=new URL(response.url());return url.pathname==='/api/signals'&&matchesRun(url)&&url.searchParams.get('limit')==='40'&&url.searchParams.has('since_sim')})
      await page.goto('/overview?run_id='+encodeURIComponent(requested))
      const response=await renderedOverview;expect(response.status()).toBe(200)
      const overview=await response.json(), run=overview.scope.all_runs?'all':String(overview.scope.resolved_run_id)
      expect(overview.scope.current_missing).toBe(false)
      const cxResponse=await renderedCx;expect(cxResponse.status()).toBe(200)
      expect(new URL(cxResponse.url()).searchParams.get('run_id')).toBe(run)
      const signalResponse=await renderedSignals;expect(signalResponse.status()).toBe(200)
      expect(new URL(signalResponse.url()).searchParams.get('run_id')).toBe(run)
      const cx=await cxResponse.json(), signalPage=await signalResponse.json()
      const expectedPoints=(signalPage.items??[]).filter((row: {origin?:string;received_sim:string;classification?:{negativity?:number}|null})=>{const n=row.classification?.negativity,at=Date.parse(row.received_sim);return row.origin!=='proactive'&&at>Date.parse(cx.window.starts_sim)&&at<=Date.parse(cx.window.ends_sim)&&typeof n==='number'&&Number.isInteger(n)&&n>=0&&n<=100}).length
      const root=page.locator('[data-overview]')
      await expect(root.locator('[data-block]')).toHaveCount(9)
      await expect(root).toHaveAttribute('data-attention',attention)
      await expect(root.locator('[data-kpi="signalsToday"]')).toHaveText(new Intl.NumberFormat(lang,{maximumFractionDigits:1}).format(overview.kpi.signals_today))
      await expect(root.locator('[data-cx-index]')).toHaveText(cx.index==null?'—':new Intl.NumberFormat(lang,{maximumFractionDigits:1}).format(cx.index))
      await expect(page.locator('html')).toHaveAttribute('data-mode',mode)
      await expect(page.locator('html')).toHaveAttribute('data-pack',pack)
      await expect(root.locator('[data-money-exact]')).toHaveAttribute('title',formatExactRub(overview.kpi.saved_rub_exact,lang).exact)
      expect(await root.innerText()).not.toMatch(/overviewUi\./)
      expect(await root.evaluate(node=>node.scrollWidth-node.clientWidth)).toBeLessThanOrEqual(1)
      const palette=await page.evaluate(()=>{
        const css=getComputedStyle(document.documentElement),rgb=(key:string)=>css.getPropertyValue('--'+key).trim().split(/\s+/).map(Number)
        const lum=(c:number[])=>c.map(v=>{const n=v/255;return n<=.03928?n/12.92:((n+.055)/1.055)**2.4}).reduce((sum,v,i)=>sum+v*[.2126,.7152,.0722][i]!,0)
        const contrast=(a:number[],b:number[])=>{const x=lum(a),y=lum(b);return(Math.max(x,y)+.05)/(Math.min(x,y)+.05)}
        return{text:Math.min(...['bg','surface','raised'].flatMap(bg=>['ink','muted','brand-foreground','ok','warn','danger','info'].map(fg=>contrast(rgb(fg),rgb(bg))))),control:Math.min(...['bg','surface','raised'].flatMap(bg=>['focus-ring','control-line'].map(fg=>contrast(rgb(fg),rgb(bg)))))}
      })
      expect(palette.text).toBeGreaterThanOrEqual(4.5);expect(palette.control).toBeGreaterThanOrEqual(3)
      expect(await root.evaluate(node=>node.getAnimations({subtree:true}).filter(animation=>animation.effect?.getTiming().iterations===Infinity).length)).toBe(0)
      for(const link of await root.locator('[data-block] > div > a').all())await expect(link).toHaveAttribute('href',new RegExp('run_id='+run+'(?:&|$)'))
      await page.screenshot({path:info.outputPath(`overview-${pack}-${lang}-${mode}-top.png`)})
      await root.locator('[data-block="overview-shift"] summary').click()
      await root.locator('[data-block="overview-shift"]').scrollIntoViewIfNeeded()
      await page.screenshot({path:info.outputPath(`overview-${pack}-${lang}-${mode}-bottom.png`)})
      await page.setViewportSize({width:360,height:800})
      expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(360)
      await expect.poll(()=>root.evaluate(node=>node.scrollWidth-node.clientWidth)).toBeLessThanOrEqual(1)
      await root.locator('[data-block="overview-cx"]').scrollIntoViewIfNeeded()
      await root.locator('[data-block="overview-cx"]').screenshot({path:info.outputPath(`overview-${pack}-${lang}-${mode}-mobile.png`)})
      const points=root.locator('svg a')
      await expect(points).toHaveCount(expectedPoints)
      const point=points.first()
      if(expectedPoints){
        await point.focus();await expect(point).toBeFocused();await expect(point.locator('circle')).toHaveAttribute('stroke-width','3')
        const traceResponse=page.waitForResponse(response=>{const url=new URL(response.url());return url.pathname.startsWith('/api/trace/signal/')&&url.searchParams.get('run_id')===run})
        await page.keyboard.press('Enter');expect((await traceResponse).status()).toBe(200);await expect(page).toHaveURL(new RegExp('/trace/signal/[^?]+\\?run_id='+run))
      }
      await info.attach('source-summary.json',{body:JSON.stringify({run,index:cx.index,expectedProjectionPoints:expectedPoints,keyboardTraceActivated:expectedPoints>0,attention,pack,lang,mode,browserWrites:writes.length,externalRequests:external.length,palette}),contentType:'application/json'})
      expect(writes).toEqual([]);expect(external).toEqual([]);expect(errors).toEqual([]);expect(forbiddenQueries).toEqual([])
    } finally {
      expect((await request.post('/api/settings/import',{data:{settings:{ui:oldUi}}})).status()).toBe(200)
    }
  })
}
