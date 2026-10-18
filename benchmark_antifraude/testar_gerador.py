"""Verifica o gerador com HTTP local simulado; nao testa o motor ou PostgreSQL."""
import datetime as dt
import io
import json
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import rodar


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        case = body.get('case','approved')
        if case == 'slow':
            time.sleep(.15)
        status = 500 if case == '500' else 201
        data = {'key':'synthetic-key','status':case if case in rodar.VALID_STATUSES else 'approved',
            'metadata':{'decision_latency_ms':2.5,'rules_triggered':[
                {'effect':'FAILSAFE_REJECT'}] if case=='fallback' else []}}
        raw = b'not json' if case == 'malformed' else json.dumps(data).encode()
        self.send_response(status)
        self.send_header('Content-Type','application/json')
        self.send_header('Content-Length',str(len(raw)))
        self.end_headers()
        try:
            self.wfile.write(raw)
        except (BrokenPipeError,ConnectionResetError):
            pass


class Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1',0),Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever,daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def setUp(self):
        self.client = rodar.Client(self.server.server_port,1)

    def tearDown(self):
        self.client.close()

    def test_business_decisions_are_not_errors(self):
        for case in rodar.VALID_STATUSES:
            result = self.client.send({'case':case})
            self.assertEqual(result['error'],'')
            self.assertEqual(result['business'],case)

    def test_http_error(self):
        self.assertEqual(self.client.send({'case':'500'})['error'],'http_500')

    def test_invalid_response(self):
        self.assertEqual(self.client.send({'case':'malformed'})['error'],'json_ou_contrato_invalido')

    def test_fallback_separate_from_http_error(self):
        result = self.client.send({'case':'fallback'})
        self.assertTrue(result['fallback'])
        self.assertFalse(result['error'])

    def test_timeout_and_next_connection(self):
        client = rodar.Client(self.server.server_port,.03)
        try:
            result = client.send({'case':'slow'})
            self.assertIn(result['error'],{'TimeoutError','timeout'})
            self.assertEqual(client.send({'case':'approved'})['error'],'')
        finally:
            client.close()

    def test_saturation_accounting(self):
        raw = io.StringIO()
        result = rodar.run_stage(self.client,40,1,2,lambda i:{'case':'slow'},raw)
        self.assertEqual(result['planejadas'],40)
        self.assertEqual(result['enviadas']+sum(result['nao_enviadas'].values()),40)
        self.assertGreater(result['nao_enviadas'].get('limite_concorrencia',0),0)
        self.assertEqual(result['erros_pct'],0)
        self.assertGreater(result['http_ms']['p95'],100)

    def test_payload_matches_seed_identifiers_and_hot_profiles(self):
        base = dt.datetime(2026,10,17,14,tzinfo=dt.timezone(dt.timedelta(hours=-3)))
        for profile in ['distribuido','mesmo_destino','mesmo_pagador']:
            seen = set()
            for i in range(50):
                body = rodar.payload(i,profile,base,10,'test',10000,10000)
                self.assertNotIn(body['id'],seen)
                seen.add(body['id'])
                self.assertLessEqual(len(body['id']),64)
                self.assertGreater(body['amount'],0)
                self.assertEqual(dt.datetime.fromisoformat(body['transaction_date']),base+dt.timedelta(seconds=10))
                if profile == 'mesmo_destino':
                    self.assertEqual(body['destination_account']['account_number'],'3000000001')
                if profile == 'mesmo_pagador':
                    self.assertEqual(body['source_account']['owner']['document_number'],'80000000001')

    def test_report_records_incomplete_run(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'report.txt'
            rodar.report({'project':'test','args':{'linhas':1000},'cleanup':'cleanup',
                'error':'interrompido'},path)
            self.assertIn('EXECUCAO INCOMPLETA',path.read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
