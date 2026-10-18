#!/usr/bin/env python3
"""Benchmark local isolado; Python 3.10+ e Docker Compose v2, sem pip no host."""
import argparse
import collections
import concurrent.futures
import csv
import datetime as dt
import hashlib
import http.client
import json
import math
import os
from pathlib import Path
import subprocess
import threading
import time
import uuid

HERE = Path(__file__).resolve().parent
VALID_STATUSES = {'approved', 'rejected', 'two_factor_required'}
SQL_MONITOR = """SELECT json_build_object(
 'at',now(),'connections',(SELECT count(*) FROM pg_stat_activity WHERE datname=current_database()),
 'waits',(SELECT coalesce(json_agg(x),'[]'::json) FROM
   (SELECT state,wait_event_type,wait_event,count(*) n FROM pg_stat_activity
    WHERE datname=current_database() AND pid<>pg_backend_pid()
    GROUP BY state,wait_event_type,wait_event) x),
 'blocked',(SELECT count(*) FROM pg_stat_activity WHERE datname=current_database()
    AND cardinality(pg_blocking_pids(pid))>0));"""
SQL_TOP = """SELECT coalesce(json_agg(x),'[]'::json) FROM
 (SELECT calls,round(total_exec_time::numeric,2) total_exec_ms,
 round(mean_exec_time::numeric,2) mean_exec_ms,round(max_exec_time::numeric,2) max_exec_ms,
 shared_blks_hit,shared_blks_read,temp_blks_written,left(query,1800) query
 FROM pg_stat_statements WHERE dbid=(SELECT oid FROM pg_database WHERE datname=current_database())
 ORDER BY total_exec_time DESC LIMIT 15) x;"""


def write_json(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')


def percentile(values, q):
    if not values:
        return None
    vals = sorted(values)
    p = (len(vals)-1)*q
    lo, hi = math.floor(p), math.ceil(p)
    return round(vals[lo]+(vals[hi]-vals[lo])*(p-lo), 3)


def source_doc(p):
    return str((60000000000000 if p % 5 == 0 else 80000000000)+p)


def dest_doc(d):
    return str((90000000000 if d % 5 == 0 else 70000000000000)+d)


def payload(sequence, profile, base_time, wall_elapsed, prefix, payers, destinations):
    p = 1 if profile == 'mesmo_pagador' else 1+sequence % payers
    d = 1 if profile == 'mesmo_destino' else 1+(sequence*17) % destinations
    event_time = base_time+dt.timedelta(seconds=wall_elapsed)
    opening = (base_time-dt.timedelta(days=3)).isoformat() if d % 10 == 0 else '2020-01-01T00:00:00-03:00'
    return {
        'id': f'bench-{prefix}-{sequence}',
        'amount': [5000,15000,19900,50000,100000,150000,300000][sequence % 7],
        'transaction_date': event_time.isoformat(),
        'source_account': {'branch':'0001','account_number':str(2000000000+p),
            'opening_date':'2020-01-01T00:00:00-03:00','owner':{'document_number':source_doc(p)}},
        'destination_account': {'participant':'60701190','branch':'0001',
            'account_number':str(3000000000+d),'opening_date':opening,
            'owner':{'document_number':dest_doc(d)}},
        'source': {'device_id':f'bench-device-{p}' if sequence % 10 else f'bench-new-{prefix}-{p}',
            'channel':'app','ip':'198.51.100.23',
            'geolocation':{'latitude':-23.5505,'longitude':-46.6333}}}


class Client:
    def __init__(self, port, timeout):
        self.port, self.timeout = port, timeout
        self.local = threading.local()
        self.connections = []
        self.lock = threading.Lock()

    def send(self, body):
        start = time.perf_counter()
        status, business, error, engine, fallback = 0, '', '', None, False
        conn = getattr(self.local, 'conn', None)
        if conn is None:
            conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=self.timeout)
            self.local.conn = conn
            with self.lock:
                self.connections.append(conn)
        try:
            conn.request('POST','/pix/transaction',json.dumps(body).encode(),
                {'INTERNAL-TOKEN':'benchmark_local','Content-Type':'application/json'})
            response = conn.getresponse()
            status = response.status
            raw = response.read()
            if status != 201:
                error = f'http_{status}'
            else:
                try:
                    data = json.loads(raw)
                    business = data.get('status','')
                    if business not in VALID_STATUSES or not data.get('key'):
                        error = 'contrato_invalido'
                    meta = data.get('metadata',{})
                    value = meta.get('decision_latency_ms')
                    if isinstance(value, (int,float)) and math.isfinite(value) and value >= 0:
                        engine = value
                    fallback = any(str(hit.get('effect','')).startswith('FAILSAFE')
                        for hit in meta.get('rules_triggered',[]))
                except (ValueError,TypeError,AttributeError):
                    error = 'json_ou_contrato_invalido'
        except Exception as exc:
            # Sem retry: repetir ocultaria falhas e alteraria a carga oferecida.
            error = type(exc).__name__
            conn.close()
            self.local.conn = None
        return {'http':status,'business':business,'error':error,'fallback':fallback,
            'http_ms':round((time.perf_counter()-start)*1000,3),'decision_ms':engine}

    def close(self):
        for conn in self.connections:
            conn.close()


def run_stage(client, rate, seconds, workers, make_body, raw_file):
    """Taxa de chegada fixa; sem fila ilimitada e sem compensar atrasos com rajadas."""
    samples, lock = [], threading.Lock()
    slots = threading.BoundedSemaphore(workers)
    missed = collections.Counter()
    started = time.perf_counter()
    total = int(rate*seconds)
    fields = ['http','business','error','fallback','http_ms','decision_ms','start_s','schedule_lag_ms']
    writer = csv.DictWriter(raw_file, fieldnames=fields)
    writer.writeheader()

    def work(body, due):
        actual = time.perf_counter()
        try:
            result = client.send(body)
            result.update(start_s=round(actual-started,6),schedule_lag_ms=round((actual-due)*1000,3))
            with lock:
                samples.append(result)
                writer.writerow(result)
        finally:
            slots.release()

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        for i in range(total):
            due = started+i/rate
            remaining = due-time.perf_counter()
            if remaining > 0:
                time.sleep(remaining)
            # Se o agendador atrasar um intervalo inteiro, nao produz rajada para recuperar.
            if time.perf_counter()-due >= 1/rate:
                missed['atraso_gerador'] += 1
                continue
            if not slots.acquire(blocking=False):
                missed['limite_concorrencia'] += 1
                continue
            try:
                pool.submit(work, make_body(i), due)
            except BaseException:
                slots.release()
                raise
        remaining = started+seconds-time.perf_counter()
        if remaining > 0:
            time.sleep(remaining)
    elapsed = time.perf_counter()-started
    errors = collections.Counter(s['error'] for s in samples if s['error'])
    lat = [s['http_ms'] for s in samples]
    decisions = [s['decision_ms'] for s in samples if s['decision_ms'] is not None]
    started_in_window = sum(s['start_s'] < seconds for s in samples)
    completed_in_window = sum(s['start_s']+s['http_ms']/1000 <= seconds for s in samples)
    return {'ofertada_rps':rate,'duracao_programada_s':seconds,'duracao_com_drenagem_s':round(elapsed,3),
        'planejadas':total,'enviadas':len(samples),'nao_enviadas':dict(missed),
        'rps_iniciadas_na_janela':round(started_in_window/seconds,3),
        'rps_concluidas_na_janela':round(completed_in_window/seconds,3),
        'rps_incluindo_drenagem':round(len(samples)/elapsed,3),
        'erros':dict(errors),'erros_pct':round(100*sum(errors.values())/max(1,len(samples)),3),
        'fallbacks':sum(s['fallback'] for s in samples),
        'decisoes':dict(collections.Counter(s['business'] for s in samples if s['business'])),
        'http_ms':{'p50':percentile(lat,.5),'p95':percentile(lat,.95),'p99':percentile(lat,.99),'max':max(lat,default=None)},
        'decision_ms':{'amostras':len(decisions),'p95':percentile(decisions,.95),'p99':percentile(decisions,.99)},
        'atraso_agendamento_p99_ms':percentile([s['schedule_lag_ms'] for s in samples],.99)}


class Docker:
    def __init__(self, project, port):
        self.base = ['docker','compose','-p',project,'-f',str(HERE/'compose.benchmark.yml')]
        self.env = dict(os.environ, BENCH_PORT=str(port))

    def call(self, *args, input=None, capture=True, check=True, timeout=120):
        return subprocess.run(self.base+list(args),input=input,text=True,encoding='utf-8',
            errors='replace',env=self.env,capture_output=capture,check=check,timeout=timeout)

    def sql(self, query):
        return self.call('exec','-T','db','psql','-X','-qAt','-U','benchmark','-d','benchmark',
            '-v','ON_ERROR_STOP=1',input=query,timeout=60).stdout.strip()


def monitor(docker, output, stop):
    with output.open('w',encoding='utf-8') as f:
        while not stop.is_set():
            row = {'utc':dt.datetime.now(dt.timezone.utc).isoformat()}
            try:
                row['db'] = json.loads(docker.sql(SQL_MONITOR))
                stats = docker.call('stats','--no-stream','--format','json','api','db',timeout=20)
                row['containers'] = stats.stdout.strip()
            except Exception as exc:
                row['monitor_error'] = str(exc)
            f.write(json.dumps(row, ensure_ascii=False)+'\n')
            f.flush()
            stop.wait(5)


def fingerprints(root):
    paths = list((root/'services'/'antifraud-service'/'src').rglob('*.py'))
    paths += [root/'services'/'antifraud-service'/'database'/'database.sql',
              root/'services'/'antifraud-service'/'requirements.txt',
              root/'services'/'antifraud-service'/'Dockerfile']
    hashes = {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(paths) if p.is_file() and '__pycache__' not in p.parts}
    git = {}
    for label, args in [('commit',['rev-parse','HEAD']),('alteracoes',['status','--porcelain'])]:
        try:
            r = subprocess.run(['git','-C',str(root)]+args,capture_output=True,text=True,timeout=10)
            git[label] = r.stdout.strip() if r.returncode == 0 else 'indisponivel'
        except (OSError,subprocess.TimeoutExpired):
            git[label] = 'indisponivel'
    return {'git':git,'sha256':hashes}


def report(data, output):
    lines = ['BENCHMARK ANTIFRAUDE PIX',f"Projeto Docker: {data['project']}",
        f"Historico solicitado: {data['args']['linhas']} Pix sinteticos",
        'Decisoes de negocio rejected/2FA nao sao erros HTTP.',
        'p95/p99 HTTP incluem transporte local, API e persistencia; decision_ms e apenas a janela informada pela API.',
        'Nao ha medicao direta da espera pelo pool SQLAlchemy nem do CPU puro do motor.',
        'Gerador, API e banco compartilham o computador. Nao extrapolar estes resultados para producao.', '']
    for profile in data.get('profiles',[]):
        lines.append(f"PERFIL: {profile['name']}")
        if profile.get('stopped_early'):
            lines.append('  PERFIL INTERROMPIDO: '+profile['stopped_early'])
        for s in profile['stages']:
            lines.append(f"Ofertada={s['ofertada_rps']} rps; iniciadas={s['rps_iniciadas_na_janela']} rps; "
                f"concluidas na janela={s['rps_concluidas_na_janela']} rps; "
                f"p95={s['http_ms']['p95']} ms; p99={s['http_ms']['p99']} ms; erros={s['erros_pct']}%; "
                f"nao enviadas={sum(s['nao_enviadas'].values())}; fallbacks={s['fallbacks']}")
            lines.append(f"  Decisoes: {s['decisoes']}; erros: {s['erros']}; "
                f"decision_ms={s['decision_ms']}; motivos de nao envio={s['nao_enviadas']}")
            reasons = []
            if sum(s['nao_enviadas'].values()):
                reasons.append('carga alvo nao sustentada; distinguir limite do gerador e saturacao do servico')
            if s['http_ms']['p95'] is None or s['http_ms']['p95'] > data['args']['p95_ms']:
                reasons.append('meta experimental de p95 nao atendida')
            if s['erros_pct'] > data['args']['erro_pct'] or s['fallbacks']:
                reasons.append('falhas tecnicas acima da meta ou fallback')
            lines.append('  Avaliacao: '+('; '.join(reasons) if reasons else 'patamar atendeu as metas experimentais escolhidas'))
        lines.append('  Consultas com maior tempo TOTAL (nao confundir com media por chamada):')
        for q in profile.get('sql_top',[])[:5]:
            lines.append(f"    chamadas={q['calls']}; total={q['total_exec_ms']} ms; media={q['mean_exec_ms']} ms; "
                + ' '.join(q['query'].split())[:240])
        lines.append('')
    if data.get('error'):
        lines += ['EXECUCAO INCOMPLETA: '+data['error']]
    lines += ['Artefatos: resultado.json, amostras CSV, monitoramento JSONL e logs por perfil.',
        'O monitor amostra a cada ~5 s; bloqueios curtos podem nao aparecer. O proprio monitor tem custo.',
        'Os perfis compartilham o historico e acumulam as novas transacoes; ordem importa.',
        'Para comparacao rigorosa: repetir perfil individual em banco novo, mesma maquina/configuracao e ordem de cargas.',
        'Dados sinteticos servem ao desempenho, nao medem deteccao de fraude ou falsos positivos.',
        'Porta e containers sao exclusivos deste benchmark; o volume e preservado para inspecao.',
        'Remover SOMENTE este ambiente: '+data['cleanup']]
    output.write_text('\n'.join(lines)+'\n',encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--linhas',type=int,default=100000)
    parser.add_argument('--taxas',default='10,25,50,100,200')
    parser.add_argument('--segundos',type=int,default=30,help='duracao de cada patamar por perfil')
    parser.add_argument('--perfis',default='distribuido,mesmo_destino,mesmo_pagador')
    parser.add_argument('--concorrencia',type=int,default=100)
    parser.add_argument('--timeout',type=float,default=5)
    parser.add_argument('--porta',type=int,default=18005)
    parser.add_argument('--p95-ms',type=float,default=1000)
    parser.add_argument('--erro-pct',type=float,default=2)
    parser.add_argument('--manter-ligado',action='store_true')
    args = parser.parse_args()
    try:
        rates = [int(x) for x in args.taxas.split(',')]
        profiles = args.perfis.split(',')
        if not rates or min(rates)<1 or max(rates)>5000:
            raise ValueError('taxas devem estar entre 1 e 5000')
        if not profiles or set(profiles)-{'distribuido','mesmo_destino','mesmo_pagador'}:
            raise ValueError('perfil desconhecido')
        if len(set(profiles)) != len(profiles):
            raise ValueError('nao repita perfis na mesma execucao')
        if not 1000<=args.linhas<=10000000 or not 1<=args.segundos<=3600:
            raise ValueError('linhas: 1000..10000000; segundos: 1..3600')
        if not 1<=args.concorrencia<=500 or not 0<args.timeout<=60 or not 1024<=args.porta<=65535:
            raise ValueError('concorrencia: 1..500; timeout: >0..60; porta: 1024..65535')
    except ValueError as exc:
        parser.error(str(exc))
    root = HERE.parent
    if not (root/'services'/'antifraud-service'/'Dockerfile').is_file():
        parser.error('Extraia benchmark_antifraude na raiz do projeto, ao lado de services.')
    project = 'afbench-'+dt.datetime.now().strftime('%Y%m%d%H%M%S')+'-'+uuid.uuid4().hex[:6]
    folder = HERE/'resultados'/project
    folder.mkdir(parents=True)
    docker = Docker(project,args.porta)
    cleanup = subprocess.list2cmdline(docker.base+['down','-v'])
    data = {'project':project,'args':vars(args),'source':fingerprints(root),'profiles':[],
        'cleanup':cleanup,'started_utc':dt.datetime.now(dt.timezone.utc).isoformat()}
    client, stop, watcher = None, None, None
    try:
        print('Construindo sua API e subindo banco exclusivo...',flush=True)
        docker.call('up','-d','--build','--wait','db','api',capture=False,timeout=1800)
        data['images'] = docker.call('images','--format','json').stdout
        info = subprocess.run(['docker','info','--format','{{json .}}'],capture_output=True,text=True,timeout=30)
        # Registrar apenas capacidade; nao salvar o ambiente ou credenciais do host.
        try:
            di = json.loads(info.stdout)
            data['docker_resources'] = {k:di.get(k) for k in ['NCPU','MemTotal','ServerVersion','OperatingSystem','Architecture']}
        except ValueError:
            data['docker_resources'] = 'indisponivel'
        print(f'Inserindo {args.linhas:,} Pix historicos diretamente no Postgres...',flush=True)
        seeded = docker.call('exec','-T','db','psql','-X','-q','-U','benchmark','-d','benchmark',
            '-v','ON_ERROR_STOP=1','-v',f'n={args.linhas}','-v','payers=10000','-v','destinations=10000',
            input=(HERE/'seed.sql').read_text(encoding='utf-8'),timeout=3600)
        (folder/'seed.log').write_text(seeded.stdout+seeded.stderr,encoding='utf-8')
        data['db_initial'] = json.loads(docker.sql("SELECT json_build_object('version',version(),'bytes',pg_database_size(current_database()),'transactions',(SELECT count(*) FROM pix_transactions),'analyses',(SELECT count(*) FROM pix_analyses),'rule_hits',(SELECT count(*) FROM rule_hits));"))
        base_time = dt.datetime.fromisoformat(docker.sql('SELECT base_time FROM benchmark_meta;')).astimezone(
            dt.timezone(dt.timedelta(hours=-3)))
        wall_start = time.perf_counter()
        client = Client(args.porta,args.timeout)
        # Aquecimento excluido das estatisticas; usa IDs unicos e e registrado.
        for i in range(10):
            warm = client.send(payload(i,'distribuido',base_time,time.perf_counter()-wall_start,'warm-'+project,10000,10000))
            if warm['error'] or warm['fallback']:
                raise RuntimeError('Aquecimento falhou: '+str(warm))
        data['warmup_requests'] = 10
        sequence = 10
        for profile in profiles:
            current = {'name':profile,'stages':[]}
            data['profiles'].append(current)
            docker.sql('SELECT pg_stat_statements_reset();')
            stop = threading.Event()
            watcher = threading.Thread(target=monitor,args=(docker,folder/(profile+'-monitor.jsonl'),stop),daemon=True)
            watcher.start()
            for rate in rates:
                print(f'{profile}: alvo {rate} rps por {args.segundos}s; limite {args.concorrencia} em voo',flush=True)
                offset = sequence
                def make_body(i):
                    return payload(offset+i,profile,base_time,time.perf_counter()-wall_start,project,10000,10000)
                with (folder/f'{profile}-{len(current["stages"])}-{rate}rps.csv').open('w',newline='',encoding='utf-8') as raw:
                    stage = run_stage(client,rate,args.segundos,args.concorrencia,make_body,raw)
                sequence += int(rate*args.segundos)
                current['stages'].append(stage)
                write_json(folder/'resultado.json',data)
                report(data,folder/'RELATORIO_CARGA.txt')
                print(f"  p95={stage['http_ms']['p95']}ms; erros={stage['erros_pct']}%; nao enviadas={sum(stage['nao_enviadas'].values())}",flush=True)
                # Interromper este perfil se mais de 20% das chamadas falharem tecnicamente.
                if stage['erros_pct']>20 or stage['fallbacks']>stage['enviadas']*.2:
                    current['stopped_early'] = 'falhas tecnicas elevadas; patamares seguintes nao executados'
                    break
            stop.set()
            watcher.join(timeout=90)
            stop, watcher = None, None
            current['sql_top'] = json.loads(docker.sql(SQL_TOP))
            (folder/(profile+'-api.log')).write_text(docker.call('logs','--no-color','--tail','2000','api').stdout,encoding='utf-8')
        data['db_final'] = json.loads(docker.sql("SELECT json_build_object('transactions',count(*),'bytes',pg_database_size(current_database())) FROM pix_transactions;"))
    except KeyboardInterrupt:
        data['error'] = 'Interrompido pelo usuario; ultimo patamar pode estar incompleto.'
    except Exception as exc:
        data['error'] = f'{type(exc).__name__}: {exc}'
        if isinstance(exc,subprocess.CalledProcessError):
            data['error'] += '\n'+(exc.stderr or '')[-4000:]
    finally:
        if stop:
            stop.set()
        if watcher:
            watcher.join(timeout=90)
        if client:
            client.close()
        if not args.manter_ligado:
            try:
                docker.call('stop',timeout=120)
            except Exception as exc:
                data['stop_error'] = str(exc)
        data['finished_utc'] = dt.datetime.now(dt.timezone.utc).isoformat()
        write_json(folder/'resultado.json',data)
        report(data,folder/'RELATORIO_CARGA.txt')
        print('\nRelatorio: '+str(folder/'RELATORIO_CARGA.txt'),flush=True)
        print('Limpeza deste teste: '+cleanup,flush=True)
    return 1 if data.get('error') else 0


if __name__ == '__main__':
    raise SystemExit(main())
