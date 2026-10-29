import asyncio,json,pathlib
from app.bench.service import BenchService
from app.api.common import db,fetch_all
from app.config import get_settings
async def main():
    out=pathlib.Path('/reports'); service=BenchService()
    assert get_settings().gigachat_verify_ssl
    datasets=await service.datasets()
    assert next(x for x in datasets if x['id']==3)['cases']==40
    async with db() as conn:
        cases=await fetch_all(conn,'select id,channel_code,text,gold from bench_cases where dataset_id=%s order by id',(3,))
        profiles=await fetch_all(conn,'select id,code,model,temperature,extra from llm_profiles where id=any(%s) order by id',([1,2,3],))
    (out/'db-cases.json').write_text(json.dumps(cases,ensure_ascii=False,indent=2,default=str))
    (out/'profiles.json').write_text(json.dumps(profiles,ensure_ascii=False,indent=2,default=str))
    forecast=await service.start(3,[1,3,2],1,True)
    assert all(x['fits_limits'] for x in forecast['forecast'])
    (out/'forecast.json').write_text(json.dumps(forecast,ensure_ascii=False,indent=2))
    for label,profile in [('Ultra',1),('Lightning',3),('Pro',2)]:
        started=await service.start(3,[profile],1,False)
        run_id=started['run_ids'][0]; task=service.tasks[run_id]
        print(label,'run',run_id,flush=True)
        while not task.done():
            detail=await service.detail(run_id)
            print(label,detail['status'],len(detail['results']),flush=True)
            await asyncio.sleep(10)
        await task
        detail=await service.detail(run_id)
        (out/f'{label.lower()}.json').write_text(json.dumps(detail,ensure_ascii=False,indent=2,default=str))
        assert detail['status']=='done',(label,detail.get('error'))
        assert len(detail['results'])==40
        metrics=detail['metrics']
        assert metrics['complete'] and metrics['sources']==['live'] and metrics['fallback_rate']==0 and metrics['temperature']==0
        print(label,json.dumps(metrics,ensure_ascii=False),flush=True)
    print('ALL COMPLETE',flush=True)
asyncio.run(main())
