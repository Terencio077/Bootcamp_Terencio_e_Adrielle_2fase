\set ON_ERROR_STOP on
BEGIN;
-- Executar somente em banco novo e exclusivo do benchmark.
DO $$ BEGIN
 IF EXISTS (SELECT 1 FROM pix_transactions) THEN
   RAISE EXCEPTION 'O seed exige pix_transactions vazia; nao apaga dados existentes.';
 END IF;
END $$;
CREATE TABLE benchmark_meta AS
SELECT :'n'::bigint AS linhas, :'payers'::int AS pagadores,
       :'destinations'::int AS destinos,
       (date_trunc('day', now() AT TIME ZONE 'America/Sao_Paulo')
         + interval '14 hours') AT TIME ZONE 'America/Sao_Paulo' AS base_time;
CREATE TEMP TABLE fixture AS
SELECT g,
 CASE WHEN g % 10 < 2 THEN 1+(g/10)%100 ELSE 1+g%m.pagadores END AS p,
 CASE WHEN g % 10 < 3 THEN 1+(g/10)%5 ELSE 1+(g*17)%m.destinos END AS d,
 m.base_time
FROM benchmark_meta m CROSS JOIN LATERAL generate_series(1,m.linhas) g;
INSERT INTO pix_transactions
(id,pix_id,request_hash,amount_cents,transaction_date,utc_offset_minutes,
 source_branch,source_account_number,source_opening_date,source_document,
 destination_participant,destination_branch,destination_account_number,
 destination_opening_date,destination_document,device_id,channel,ip,latitude,longitude)
SELECT g, 'bench-hist-'||g, md5(g::text)||md5('seed-'||g),
 (ARRAY[5000,15000,19900,50000,100000,150000,300000])[1+(g%7)::int],
 greatest(base_time - CASE WHEN g%4=0 THEN ((1+g%1800)*interval '1 second')
                         WHEN g%4=1 THEN ((1+g%86400)*interval '1 second')
                         ELSE ((1+g%7776000)*interval '1 second') END,
          CASE WHEN d%10=0 THEN base_time-interval '3 days' ELSE '2020-01-01T00:00:00Z'::timestamptz END),
 -180,'0001',(2000000000+p)::text,'2020-01-01T00:00:00Z'::timestamptz,
 CASE WHEN p%5=0 THEN (60000000000000+p)::text ELSE (80000000000+p)::text END,
 '60701190','0001',(3000000000+d)::text,
 CASE WHEN d%10=0 THEN base_time-interval '3 days' ELSE '2020-01-01T00:00:00Z'::timestamptz END,
 CASE WHEN d%5=0 THEN (90000000000+d)::text ELSE (70000000000000+d)::text END,
 'bench-device-'||p,'app','198.51.100.23',-23.5505,-46.6333
FROM fixture;
INSERT INTO pix_analyses
(id,analysis_key,pix_transaction_id,analysis_status_id,identity_score,transaction_score,
 decision_reason,rules_version,latency_ms,created_at)
SELECT t.id, md5('analysis-'||t.id)::uuid::text,t.id,s.id,
 CASE WHEN t.id%13 BETWEEN 8 AND 10 THEN 30 ELSE 0 END,
 CASE WHEN t.id%13>=11 THEN 100 ELSE 0 END,
 'FIXTURE SINTETICA: nao calculada pelo motor','bench-fixture',0,t.transaction_date
FROM pix_transactions t JOIN analysis_statuses s ON s.enumerator=
 CASE WHEN t.id%13<8 THEN 'APPROVED' WHEN t.id%13<11 THEN 'TWO_FACTOR_REQUIRED' ELSE 'REJECTED' END;
INSERT INTO rule_hits(pix_analysis_id,rule_code,risk_axis_id,effect,points,reason,evidence)
SELECT a.id, CASE WHEN a.identity_score>0 THEN 'BENCH_ID' ELSE 'BENCH_TX' END,
 x.id,'SCORE',CASE WHEN a.identity_score>0 THEN 30 ELSE 40 END,
 'Fixture de volume; nao evidencia real de fraude','{"synthetic":true}'::jsonb
FROM pix_analyses a JOIN risk_axes x ON x.enumerator=
 CASE WHEN a.identity_score>0 THEN 'IDENTITY' ELSE 'TRANSACTION' END
WHERE a.identity_score>0 OR a.transaction_score>0;
INSERT INTO rule_hits(pix_analysis_id,rule_code,risk_axis_id,effect,points,reason,evidence)
SELECT a.id,'BENCH_TX2',x.id,'SCORE',60,'Fixture de volume','{"synthetic":true}'::jsonb
FROM pix_analyses a JOIN risk_axes x ON x.enumerator='TRANSACTION' WHERE a.transaction_score>0;
SELECT setval(pg_get_serial_sequence('pix_transactions','id'),(SELECT max(id) FROM pix_transactions));
SELECT setval(pg_get_serial_sequence('pix_analyses','id'),(SELECT max(id) FROM pix_analyses));
COMMIT;
ANALYZE pix_transactions;
ANALYZE pix_analyses;
ANALYZE rule_hits;
DROP TABLE fixture;
