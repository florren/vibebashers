import type { Schemas } from '@/shared/api/client'
export const overview: Schemas['MetricsOverview'] = {
  as_of_sim:'2026-11-09T09:00:00Z',scope:{requested_run_id:'current',resolved_run_id:27,all_runs:false,current_missing:false},window:{starts_sim:'2026-11-08T09:00:00Z',ends_sim:'2026-11-09T09:00:00Z'},today_starts_sim:'2026-11-08T21:00:00Z',
  kpi:{signals_today:5,critical_today:1,autonomous_share:50,agent_response_p50_ms:145,sla_risk_incidents:1,saved_rub_exact:'10999999999999.67'},coverage:{signals_today:5,criticality_known_today:5,agent_runs:2,outcome_known:2,latency_known:2,incidents:11,economics_known:11,sla_known:2,sla_open:2},economics_basis:'saved_incident_economics_only',oldest_computed_at:null,sla_basis:'registered_sla_risk',sla_forecast_complete:false,response_basis:'recorded_agent_run_latency_ms',pressure:[{status:'in_progress',criticality:'high',incidents:2}],signals_24h:5,
  shift:{basis:'saved_classification_compendium',new_llm_call:false,limit:8,total:1,truncated:false,items:[{agent_run_id:12,signal_id:101,public_id:'SIG-000101',started_sim:'2026-11-09T08:00:00Z',node:'classify',mode:'mock',text:'Сохранённая учебная сводка'}]},
}
export const weights = {negativity:.4,criticality:.25,sla:.2,churn:.15}
const components: Schemas['CxComponents'] = {
  negativity:{value:80,observed_value:80,known:5,total:5,numerator:400,status:'complete',unit:'percent',basis:'recorded_classification'},
  criticality:{value:20,observed_value:20,known:5,total:5,numerator:1,status:'complete',unit:'percent',basis:'recorded_classification'},
  sla:{value:50,observed_value:50,known:2,total:2,numerator:1,status:'complete',unit:'percent',basis:'registered_sla_risk'},
  churn:{value:40,observed_value:40,known:5,total:5,numerator:2,status:'complete',unit:'percent',basis:'recorded_classification'},
}
export const cx: Schemas['CxIndex'] = {
  demonstration:true,index:47,previous_index:null,delta_hour:null,as_of_sim:overview.as_of_sim,scope:overview.scope,window:overview.window,previous_window:{starts_sim:'2026-11-08T08:00:00Z',ends_sim:'2026-11-09T08:00:00Z'},weights,weights_source:'tz_default',weights_error:null,default_weights:weights,comparison_basis:'current_weights_on_observed_states',components,previous_components:Object.fromEntries(Object.entries(components).map(([key,c])=>[key,{...c,value:null,known:0,status:'unknown'}])) as Schemas['CxComponents'],sla_basis:'registered_sla_risk',sla_forecast_complete:false,historical_sla_reason:'historical_sla_evidence_unavailable',signals:5,previous_signals:5,channel_mix:[{channel_code:'chat',signals:5}],flow:Array.from({length:24},(_,bucket)=>({bucket,starts_sim:new Date(Date.parse(overview.window.starts_sim)+bucket*3600000).toISOString(),ends_sim:new Date(Date.parse(overview.window.starts_sim)+(bucket+1)*3600000).toISOString(),signals:bucket===23?5:0})),
}
export const signal: Schemas['Signal'] = {id:101,public_id:'SIG-000101',run_id:27,received_sim:'2026-11-09T08:30:00Z',channel_code:'chat',status:'classified',origin:'jury',text:'private@example.test +7 999 123-45-67',classification:{negativity:80,criticality:'high',signal_type:'service_quality',flags:['sarcasm']} as NonNullable<Schemas['Signal']['classification']>}
