import { chromium } from '../../../frontend/node_modules/playwright/index.mjs'
import fs from 'node:fs/promises'
import assert from 'node:assert/strict'
const base = process.env.CX_BASE_URL ?? 'http://localhost:8000'
const dir = process.env.CX_SCREENSHOT_DIR ?? '/tmp/finance-products-visual'
await fs.mkdir(dir,{recursive:true})
const browser=await chromium.launch({headless:true,...(process.env.CHROME_EXECUTABLE?{executablePath:process.env.CHROME_EXECUTABLE}:{})})
const report=[]
for(const lang of ['ru','en']) for(const theme of ['light','dark']) {
 const ctx=await browser.newContext({viewport:{width:1440,height:1100},reducedMotion:'reduce'})
 await ctx.addInitScript(({lang,theme})=>{localStorage.setItem('cx.lang',lang);localStorage.setItem('cx.ui.mode',theme);localStorage.setItem('cx.ui.pending',JSON.stringify({mode:theme}))},{lang,theme})
 const page=await ctx.newPage(); const errors=[];page.on('pageerror',e=>errors.push(e.message))
 const dict=JSON.parse(await fs.readFile(new URL(`../../../frontend/src/shared/i18n/${lang}.json`,import.meta.url),'utf8'))
 await page.goto(`${base}/finance`)
 await page.getByText(dict.finance.model,{exact:true}).waitFor()
 const filter=page.locator('details').filter({has:page.locator('summary').filter({hasText:dict.financeProducts.title})})
 await filter.locator('summary').click()
 await filter.getByRole('checkbox').first().waitFor()
 const catalog=await(await ctx.request.get(`${base}/api/refs/products`)).json()
 const all=await(await ctx.request.get(`${base}/api/v1/finance/impact/total?limit=100`)).json()
 const code=all.items.find(i=>i.product_code)?.product_code ?? catalog[0].code
 const product=catalog.find(p=>p.code===code); assert.ok(product)
 const name=lang==='en'?(product.name_en??product.name_ru):product.name_ru
 const check=async(mode,codes=[])=>{
  const params=new URLSearchParams({product_mode:mode,run_id:String(all.run_id),limit:'100'})
  for(const c of codes)params.append('product_codes',c)
  const total=await(await ctx.request.get(`${base}/api/v1/finance/impact/total?${params}`)).json()
  const assessed=await(await ctx.request.get(`${base}/api/v1/finance/impact/assessment?${params}`)).json()
  const money=value=>new Intl.NumberFormat(lang==='en'?'en-US':'ru-RU',{style:'currency',currency:'RUB',minimumFractionDigits:2,maximumFractionDigits:2}).format(value)
  const model=page.getByRole('region',{name:dict.finance.model,exact:true})
  await model.getByText(money(total.total_saved_rub),{exact:true}).first().waitFor()
  const panel=page.getByRole('region',{name:dict.financeProof.title,exact:true})
  for(const contour of assessed.contours){
   const card=panel.getByRole('heading',{name:dict.financeProof.scope[contour.scope],exact:true}).locator('..')
   await card.getByText(contour.risk_total_rub===null?dict.financeProof.unknown:money(contour.risk_total_rub),{exact:true}).first().waitFor()
   assert.equal(contour.case_count,total.incidents_resolved)
  }
  assert.equal(assessed.contours[1].risk_total_rub,null)
  assert.equal(assessed.contours[1].fine_rub,null)
  return {mode,codes,count:total.incidents_resolved,saved:total.total_saved_rub,refund:total.refund_rub,demo_risk:assessed.contours[0].risk_total_rub,observed_risk:assessed.contours[1].risk_total_rub}
 }
 const changes=async(action,mode,codes=[])=>{
  const response=page.waitForResponse(r=>r.url().includes('/finance/impact/total?')&&new URL(r.url()).searchParams.get('product_mode')===mode&&JSON.stringify(new URL(r.url()).searchParams.getAll('product_codes'))===JSON.stringify(codes)&&r.status()===200)
  await action();await response;return await check(mode,codes)
 }
 const checks=[]
 checks.push(await changes(()=>filter.getByRole('button',{name:dict.financeProducts.clear,exact:true}).click(),'include'))
 assert.equal(checks.at(-1).count,0)
 checks.push(await changes(()=>filter.getByRole('checkbox',{name,exact:true}).check(),'include',[code]))
 await filter.evaluate(el=>el.scrollIntoView({block:'start'}))
 await page.screenshot({path:`${dir}/${lang}-${theme}-filter.png`})
 checks.push(await changes(()=>filter.getByLabel(dict.financeProducts.mode).selectOption('exclude'),'exclude',[code]))
 checks.push(await changes(()=>filter.getByRole('button',{name:dict.financeProducts.clear,exact:true}).click(),'exclude'))
 assert.equal(checks.at(-1).count,all.incidents_resolved)
 checks.push(await changes(()=>filter.getByRole('button',{name:dict.financeProducts.all,exact:true}).click(),'all'))
 assert.equal(await filter.getByRole('checkbox',{checked:true}).count(),catalog.length)
 const panel=page.getByRole('region',{name:dict.financeProof.title,exact:true});await panel.evaluate(el=>el.scrollIntoView({block:'start'}))
 await page.screenshot({path:`${dir}/${lang}-${theme}-contours.png`})
 await page.setViewportSize({width:390,height:844});await filter.evaluate(el=>el.scrollIntoView({block:'start'}))
 const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)
 if(lang==='ru'&&theme==='light')await page.screenshot({path:`${dir}/ru-light-mobile.png`})
 report.push({lang,theme,run_id:all.run_id,errors,overflow,checks});await ctx.close()
}
await browser.close();await fs.writeFile(`${dir}/report.json`,JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify(report))
assert.ok(report.every(r=>!r.errors.length&&!r.overflow))
