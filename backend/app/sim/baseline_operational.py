"""Рабочая конфигурация и журналы доставки не являются банковским baseline."""

import re

TABLES = {"llm_profiles", "llm_api_keys", "llm_cassettes"}
SEQUENCES = {f"{table}_id_seq" for table in TABLES}


def bank_toc(toc: str) -> str:
    """Не исполняем DDL/DATA рабочих объектов даже из старого полного архива."""
    lines = []
    for line in toc.splitlines():
        protected = False
        if line and not line.startswith(";") and "; " in line:
            description = line.split("; ", 1)[1]
            protected = bool(re.search(r"(?:^|\s)(llm_runtime|channel_runtime)(?:\s|$)", description))
            protected |= bool(re.search(r"\bSCHEMA - public(?:\s|$)", description))
            if " public " in description:
                fields = description.split(" public ", 1)[1].split()
                if fields and fields[0] in {"TABLE", "COLUMN", "SEQUENCE"}:
                    fields = fields[1:]
                if fields:
                    name = fields[0].split(".", 1)[0]
                    protected |= name in TABLES | SEQUENCES
        lines.append(";" + line if protected else line)
    return "\n".join(lines) + "\n"


# Временные объекты создаются самим restore, живут в той же транзакции и не требуют seed/DDL.
PRELUDE = """
LOCK TABLE public.llm_profiles, public.llm_api_keys, public.llm_cassettes IN SHARE ROW EXCLUSIVE MODE;
CREATE TEMP TABLE cx_restore_llm_state ON COMMIT DROP AS
 SELECT 'profiles'::text AS kind, coalesce(jsonb_agg(to_jsonb(p) ORDER BY p.id),'[]'::jsonb) AS value FROM public.llm_profiles p
 UNION ALL SELECT 'keys',coalesce(jsonb_agg(to_jsonb(k) ORDER BY k.id),'[]'::jsonb) FROM public.llm_api_keys k
 UNION ALL SELECT 'sequences',jsonb_build_array(
   (SELECT jsonb_build_array(last_value,is_called) FROM public.llm_profiles_id_seq),
   (SELECT jsonb_build_array(last_value,is_called) FROM public.llm_api_keys_id_seq),
   (SELECT jsonb_build_array(last_value,is_called) FROM public.llm_cassettes_id_seq));
CREATE TEMP TABLE cx_restore_llm_settings ON COMMIT DROP AS
 SELECT key,value,updated_at FROM public.settings WHERE key IN ('llm','llm_keys','setup_payload');
"""

EPILOGUE = """
DELETE FROM public.settings WHERE key IN ('llm','llm_keys');
INSERT INTO public.settings(key,value,updated_at)
 SELECT key,value,updated_at FROM pg_temp.cx_restore_llm_settings WHERE key IN ('llm','llm_keys');
UPDATE public.settings SET value=value-'llm' WHERE key='setup_payload';
INSERT INTO public.settings(key,value,updated_at)
 SELECT key,jsonb_build_object('llm',value->'llm'),updated_at FROM pg_temp.cx_restore_llm_settings
 WHERE key='setup_payload' AND value ? 'llm'
 ON CONFLICT(key) DO UPDATE SET value=jsonb_set(public.settings.value,'{llm}',excluded.value->'llm'),updated_at=excluded.updated_at;
DO $cx_preserve$
BEGIN
 IF (SELECT value FROM pg_temp.cx_restore_llm_state WHERE kind='profiles') IS DISTINCT FROM
    (SELECT coalesce(jsonb_agg(to_jsonb(p) ORDER BY p.id),'[]'::jsonb) FROM public.llm_profiles p)
 OR (SELECT value FROM pg_temp.cx_restore_llm_state WHERE kind='keys') IS DISTINCT FROM
    (SELECT coalesce(jsonb_agg(to_jsonb(k) ORDER BY k.id),'[]'::jsonb) FROM public.llm_api_keys k)
 OR (SELECT value FROM pg_temp.cx_restore_llm_state WHERE kind='sequences') IS DISTINCT FROM jsonb_build_array(
   (SELECT jsonb_build_array(last_value,is_called) FROM public.llm_profiles_id_seq),
   (SELECT jsonb_build_array(last_value,is_called) FROM public.llm_api_keys_id_seq),
   (SELECT jsonb_build_array(last_value,is_called) FROM public.llm_cassettes_id_seq))
 THEN RAISE EXCEPTION 'Restore попытался изменить рабочую LLM-конфигурацию'; END IF;
 IF (SELECT coalesce(jsonb_agg(jsonb_build_array(key,value) ORDER BY key),'[]'::jsonb) FROM public.settings WHERE key IN ('llm','llm_keys'))
 IS DISTINCT FROM (SELECT coalesce(jsonb_agg(jsonb_build_array(key,value) ORDER BY key),'[]'::jsonb) FROM pg_temp.cx_restore_llm_settings WHERE key IN ('llm','llm_keys'))
 OR (SELECT value->'llm' FROM public.settings WHERE key='setup_payload')
 IS DISTINCT FROM (SELECT value->'llm' FROM pg_temp.cx_restore_llm_settings WHERE key='setup_payload')
 THEN RAISE EXCEPTION 'Restore попытался изменить рабочие настройки LLM'; END IF;
END
$cx_preserve$;
"""
