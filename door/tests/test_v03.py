import base64
import copy
import http.client
import json
import os
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock
import subprocess

from door.cloud import Cloud, UNKNOWN
from door.common import now, sha256_text, ulid
from door.envelope import generate, encode
from door.host import Host
from door.policy import validate, PolicyError, PolicyHolder, DEFAULTS, cloud_summary
from door.proxy import EgressProxy, Ctx
from door.sandbox import RunResult, ContainerRuntime
from door.exporter import build_export
from door.outfilter import filter_reply
from door.plow import PlowAPI, LatchRelay
from door.service import panel_command


def repo(path, files):
    path.mkdir()
    subprocess.run(['git','init','-q',str(path)],check=True)
    for name, text in files.items():
        p=path/name; p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text)
    subprocess.run(['git','-C',str(path),'add','.'],check=True)
    subprocess.run(['git','-C',str(path),'-c','user.name=Door Test','-c','user.email=test@example.invalid',
                    'commit','-qm','fixture'],check=True)
    return path


class Runtime:
    def __init__(self, answer='O projeto contém um README.', block=False):
        self.answer=answer;self.calls=[];self.block=block;self.started=threading.Event();self.end=threading.Event()
    def available(self):return True
    def cleanup_stale(self):pass
    def kill(self,name):self.end.set()
    def run(self,spec,timeout):
        self.calls.append(spec);self.started.set()
        if self.block:self.end.wait(5)
        (Path(spec['outbox_dir'])/'answer.md').write_text(self.answer)
        return RunResult(0)


class HostTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.repo=repo(self.root/'repo',{'README.md':'Código público','nested/.env':'password=secret'})
        (self.repo/'.env.local').write_text('UNTRACKED_SECRET')
        self.policy_path=self.root/'config'/'door.json';self.policy_path.parent.mkdir()
        self.policy={'version':1,'agent':{'alias':'desk','backend':'claude','max_capability':'ask','model':'m',
                      'exports':[{'name':'repo','repo':str(self.repo)}]}}
        self.policy_path.write_text(json.dumps(self.policy))
        self.runtime=Runtime();self.host=Host(self.policy_path,self.root/'state',self.runtime,'REAL_TEST_CREDENTIAL')
        self.host.proxy.start()
        self.private,self.public=generate();self.code=self.host.pair_start()['code']
        self.assertTrue(self.host.pair_confirm(self.code,self.public)['ok'])
        rid=ulid();text='Como funciona o projeto?'
        self.req={'request_id':rid,'guest_id':ulid(),'agent_alias':'desk','capability':'ask','text':text,
                  'text_hash':sha256_text(text),'deadline_at':now()+100,
                  'approval':{'request_id':rid,'text_hash':sha256_text(text),'decision':'approve'}}
    def tearDown(self):
        for rid in list(self.host._running):self.host.cancel(rid);self.host.wait(rid)
        self.host.proxy.stop();self.tmp.cleanup()
    def ask(self,req=None):return self.host.ask(*encode(self.private,req or self.req))
    def test_valid_and_duplicate_concurrent_executes_once(self):
        with ThreadPoolExecutor(max_workers=8) as pool:results=list(pool.map(lambda _:self.ask(),range(8)))
        self.assertTrue(all(r['ok'] for r in results));r=self.host.wait(self.req['request_id'])
        self.assertEqual(r['state'],'completed');self.assertEqual(len(self.runtime.calls),1)
    def test_pair_code_one_use_and_no_host_key_in_cloud(self):
        self.assertFalse(self.host.pair_confirm(self.code,self.public)['ok'])
        self.assertNotIn('secret',self.host._kv('host.json'))
    def test_tampered_payload_signature_rejected(self):
        payload,sig=encode(self.private,self.req);raw=json.loads(base64.b64decode(payload));raw['text']='alterada'
        self.assertEqual(self.host.ask(base64.b64encode(json.dumps(raw).encode()).decode(),sig)['reason'],'bad_signature')
    def test_text_hash_mismatch_rejected(self):
        self.req['text']='alterada';self.assertEqual(self.ask()['reason'],'text_hash')
    def test_approval_mismatch_rejected(self):
        self.req['approval']['text_hash']='wrong';self.assertEqual(self.ask()['reason'],'approval')
    def test_capability_rejected(self):
        self.req['capability']='pr';self.assertEqual(self.ask()['reason'],'capability')
    def test_paused_host_rejects(self):
        self.host.set_paused(True);self.assertEqual(self.ask()['reason'],'paused')
    def test_expired_rejected(self):
        self.req['deadline_at']=now()-1;self.assertEqual(self.ask()['reason'],'expired')
    def test_local_budget_rejects_approved(self):
        self.host.audit.write('usage',detail={'cost':50});self.assertEqual(self.ask()['reason'],'monthly_budget')
    def test_local_guest_request_limit_rejects(self):
        for _ in range(10):self.host.audit.write('recheck',ulid(),self.req['guest_id'],detail={'ok':True})
        self.assertEqual(self.ask()['reason'],'guest_daily_requests')
    def test_cancel_kills_and_cleans(self):
        self.runtime.block=True;self.ask();self.assertTrue(self.runtime.started.wait(2))
        self.host.cancel(self.req['request_id'],'guest_canceled');r=self.host.wait(self.req['request_id'])
        self.assertEqual(r['state'],'canceled');self.assertEqual(r['reason'],'guest_canceled')
        self.assertFalse(list((self.root/'state'/'exports').iterdir()));self.assertFalse(list((self.root/'state'/'outboxes').iterdir()))
    def test_hold_obvious_secret(self):
        self.runtime.answer='sk-ant-'+('abcdef123456XYZ'*4);self.ask();r=self.host.wait(self.req['request_id'])
        self.assertTrue(r['reply']['held']);self.assertNotIn('sk-ant',r['reply']['text'])
    def test_outbox_symlink_rejected(self):
        out=self.root/'out';out.mkdir();(out/'answer.md').symlink_to(self.policy_path)
        self.assertIsNone(self.host._read_answer(out))
    def test_export_never_includes_checkout_env(self):
        dest=self.root/'export';self.assertEqual(build_export(self.policy['agent']['exports'],dest),[])
        self.assertTrue((dest/'repo'/'README.md').exists());self.assertFalse((dest/'repo'/'.env.local').exists())
        self.assertFalse((dest/'repo'/'nested'/'.env').exists())
    def test_audit_keeps_question_and_reply(self):
        self.ask();self.host.wait(self.req['request_id']);rows=list(self.host.audit.rows())
        self.assertEqual(next(r for r in rows if r['event']=='request_received')['detail']['text'],self.req['text'])
        self.assertIn('text',next(r for r in rows if r['event']=='reply_filtered')['detail'])


class CloudTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.t=now();self.path=Path(self.tmp.name)/'cloud.db'
        self.summary={'alias':'desk','description':'Código exportado','max_capability':'ask','limits':copy.deepcopy(DEFAULTS['limits'])}
        self.c=Cloud(self.path,'owner',self.summary,'https://panel.example',lambda:self.t,approval='each')
        self.c.receive('activation','+5511999999999','owner-thread','Door Activate: '+self.c.s['activation'])
        self.c.set_plan('active',self.t+86400)
        self.gid=self.c.add_guest('+5511888888888','Ana')
    def tearDown(self):self.c.db.close();self.tmp.cleanup()
    def send(self,text='Como funciona?',phone='+5511888888888',thread='guest-thread',group=False):
        return self.c.receive(ulid(),phone,thread,text,group)
    def approve(self,rid):
        self.send('YES '+self.c.s['requests'][rid]['approval_code'],'+5511999999999','owner-thread')
    def test_unknown_one_reply_in_rolling_24h_no_text(self):
        self.send('UNKNOWN_SECRET',phone='+5511777777777');self.send('MORE_UNKNOWN',phone='+5511777777777')
        out=self.c.pending_sms();self.assertEqual(sum(x['text']==UNKNOWN for x in out),1)
        self.assertNotIn('UNKNOWN_SECRET',json.dumps(self.c.s));self.assertNotIn('MORE_UNKNOWN',json.dumps(self.c.s))
        self.t+=86401;self.send('third',phone='+5511777777777');self.assertEqual(sum(x['text']==UNKNOWN for x in self.c.pending_sms()),2)
    def test_group_never_creates_request(self):self.assertIsNone(self.send(group=True));self.assertFalse(self.c.s['requests'])
    def test_owner_wrong_thread_cannot_approve(self):
        rid=self.send();self.send('YES '+self.c.s['requests'][rid]['approval_code'],'+5511999999999','wrong-thread')
        self.assertEqual(self.c.s['requests'][rid]['state'],'waitingApproval')
    def test_guest_cannot_approve(self):
        rid=self.send();self.send('YES '+self.c.s['requests'][rid]['approval_code']);self.assertEqual(self.c.s['requests'][rid]['state'],'waitingApproval')
    def test_missing_code_and_wrong_code(self):
        rid=self.send();self.send('YES','+5511999999999','owner-thread');self.send('YES 99999','+5511999999999','owner-thread')
        self.assertEqual(self.c.s['requests'][rid]['state'],'waitingApproval')
    def test_code_one_use_and_bound_to_request(self):
        rid=self.send();other=self.send('Outra pergunta');self.approve(rid);self.approve(rid)
        self.assertEqual(self.c.s['requests'][rid]['state'],'queued');self.assertEqual(self.c.s['requests'][other]['state'],'waitingApproval')
    def test_sms_never_adds_guest_or_limits(self):
        self.send('DOOR ADICIONAR +5511222222222','+5511999999999','owner-thread');self.assertEqual(len(self.c.s['guests']),1)
    def test_immutable_hash_dispatch(self):
        rid=self.send();self.approve(rid);self.c.s['requests'][rid]['text']='forged';relay=Mock();self.c.dispatch(relay)
        relay.ask.assert_not_called();self.assertEqual(self.c.s['requests'][rid]['terminal_reason'],'rejected_host')
    def test_daily_requests_eleventh_denied(self):
        for _ in range(10):
            rid=self.send();self.c.decide(rid,'deny','session',self.c.s['requests'][rid]['text_hash'])
        self.assertIsNone(self.send());self.assertEqual(len(self.c.s['requests']),10)
    def test_open_request_limit(self):self.send();self.send();self.assertIsNone(self.send())
    def test_expiry_and_no_retry_after_acceptance(self):
        rid=self.send();self.t+=43201;self.c.tick();self.assertEqual(self.c.s['requests'][rid]['terminal_reason'],'expired')
    def test_retry_before_acceptance_and_persistence(self):
        rid=self.send();self.approve(rid);relay=Mock();relay.ask.side_effect=TimeoutError;self.c.dispatch(relay)
        self.assertEqual(self.c.s['requests'][rid]['state'],'queued');self.assertGreater(self.c.s['requests'][rid]['retry_at'],self.t)
        other=Cloud(self.path,'owner',self.summary,clock=lambda:self.t,approval='each');self.assertEqual(other.s['requests'][rid]['state'],'queued');other.db.close()
    def test_pause_only_owner(self):
        self.send('DOOR PAUSE');self.assertFalse(self.c.s['paused'])
        self.send('DOOR PAUSE','+5511999999999','owner-thread');self.assertTrue(self.c.s['paused'])
    def test_cancellation_running_enqueues_host_kill(self):
        rid=self.send();self.approve(rid);relay=Mock();relay.ask.return_value={'ok':True,'state':'running'};self.c.dispatch(relay)
        self.send('CANCEL');self.assertEqual(self.c.s['requests'][rid]['state'],'canceled')
        self.assertTrue(any(c['op']=='cancel' for c in self.c.s['commands'].values()))
    def test_revoked_after_approval_not_dispatched(self):
        rid=self.send();self.approve(rid);self.c.set_guest_status(self.gid,'revoked');relay=Mock();self.c.dispatch(relay);relay.ask.assert_not_called()
    def test_retention_purges_content_keeps_metadata(self):
        rid=self.send();self.c.decide(rid,'deny','s',self.c.s['requests'][rid]['text_hash']);self.t+=31*86400;self.c.tick()
        self.assertNotIn('text',self.c.s['requests'][rid]);self.assertIn('text_hash',self.c.s['requests'][rid])
    def test_guest_expiry_maximum(self):
        with self.assertRaises(ValueError):self.c.add_guest('+5511222222222',days=91)
    def test_panel_hash_required(self):
        rid=self.send()
        with self.assertRaises(ValueError):panel_command(self.c,{'op':'decide','request_id':rid,'decision':'approve','text_hash':'bad','owner_session':'server'})
    def test_month_budget_and_owner_single_alert(self):
        self.c.s['usage']['u']={'guest_id':self.gid,'input_tokens':1,'output_tokens':1,'cost':50,'recorded_at':self.t}
        self.assertIsNone(self.send());self.c.tick();self.c.tick()
        self.assertEqual(sum('monthly budget used up' in x['text'] for x in self.c.pending_sms()),1)


class Provider:
    def __init__(self, tokens=20, output=5, stream=False):
        self.calls=[];self.tokens=tokens;self.output=output;self.stream=stream;provider=self
        class H(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                body=json.loads(self.rfile.read(int(self.headers['content-length'])));provider.calls.append((self.path,body,self.headers.get('x-api-key')))
                if self.path.endswith('count_tokens'):data=json.dumps({'input_tokens':provider.tokens}).encode();ctype='application/json'
                elif body.get('stream'):
                    ev=[{'type':'message_start','message':{'model':'m','usage':{'input_tokens':provider.tokens,'output_tokens':0}}},
                        {'type':'message_delta','usage':{'output_tokens':provider.output}}]
                    data=''.join('data: '+json.dumps(x)+'\n\n' for x in ev).encode();ctype='text/event-stream'
                else:data=json.dumps({'model':'m','usage':{'input_tokens':provider.tokens,'output_tokens':provider.output}}).encode();ctype='application/json'
                self.send_response(200);self.send_header('content-type',ctype);self.send_header('content-length',str(len(data)));self.end_headers();self.wfile.write(data)
        self.server=ThreadingHTTPServer(('127.0.0.1',0),H);threading.Thread(target=self.server.serve_forever,daemon=True).start()
    def close(self):self.server.shutdown();self.server.server_close()


class ProxyTests(unittest.TestCase):
    def setUp(self):
        self.up=Provider();self.p=EgressProxy(['127.0.0.1:'+str(self.up.server.server_port)],'REAL_SECRET',
                                             {'input_per_mtok':3,'output_per_mtok':15},scheme='http').start()
        self.ctx=Ctx(ulid(),ulid(),100,10,.01,'m');self.token=self.p.bind(self.ctx)
    def tearDown(self):self.p.stop();self.up.close()
    def call(self,path='/v1/messages',body=None,key=None):
        conn=http.client.HTTPConnection('127.0.0.1',self.p.port)
        conn.request('POST',path,json.dumps(body or {'model':'m','max_tokens':1000,'messages':[]}),
                     {'x-api-key':key or self.token,'content-type':'application/json'})
        r=conn.getresponse();data=r.read();code=r.status;conn.close();return code,data
    def test_credential_injection_and_max_tokens(self):
        self.assertEqual(self.call()[0],200);self.assertEqual(self.up.calls[-1][1]['max_tokens'],10)
        self.assertEqual(self.up.calls[-1][2],'REAL_SECRET');self.assertEqual(self.ctx.tokens,25)
        self.assertEqual(self.ctx.samples[0]['source'],'exact');self.assertIn('id',self.ctx.samples[0])
    def test_stream_usage_exact(self):
        self.call(body={'model':'m','max_tokens':10,'messages':[],'stream':True});self.assertEqual(self.ctx.tokens,25)
    def test_unknown_key_rejected(self):self.assertEqual(self.call(key='wrong')[0],401);self.assertFalse(self.up.calls)
    def test_absolute_url_and_other_paths_denied(self):
        self.assertEqual(self.call('https://attacker.example/v1/messages')[0],403)
        self.assertEqual(self.call('/v1/files')[0],403);self.assertFalse(self.up.calls)
    def test_model_cannot_be_changed(self):self.assertEqual(self.call(body={'model':'expensive','max_tokens':1})[0],403)
    def test_budget_preflight_blocks_before_billable_call(self):
        self.ctx.budget_left_usd=.000001;self.assertEqual(self.call()[0],429)
        self.assertTrue(self.ctx.budget_hit);self.assertTrue(all(p.endswith('count_tokens') for p,_,_ in self.up.calls))
    def test_input_count_prevents_token_overshoot(self):
        self.ctx.max_turn_tokens=20;self.assertEqual(self.call()[0],429);self.assertTrue(self.ctx.budget_hit)
    def test_remote_url_and_server_tools_blocked(self):
        self.assertEqual(self.call(body={'model':'m','max_tokens':1,'messages':[{'source':{'type':'url','url':'https://attacker'}}]})[0],403)
        self.assertEqual(self.call(body={'model':'m','max_tokens':1,'tools':[{'type':'web_search_20250305'}]})[0],403)
    def test_concurrent_calls_serialize_budget(self):
        self.ctx.max_turn_tokens=30
        with ThreadPoolExecutor(max_workers=2) as pool:codes=list(pool.map(lambda _:self.call()[0],range(2)))
        self.assertEqual(sorted(codes),[200,429]);self.assertEqual(self.ctx.tokens,25)


class BoundaryTests(unittest.TestCase):
    def test_policy_outside_exports(self):
        p={'version':1,'agent':{'alias':'desk','exports':[{'name':'repo','repo':'/tmp/r'}]}}
        with self.assertRaises(PolicyError):validate(p,Path('/tmp/r/door.json'),Path('/tmp/state'))
    def test_negative_nan_or_unsupported_policy_fail_closed(self):
        base={'version':1,'agent':{'alias':'desk','exports':[{'name':'repo','repo':'/tmp/r'}]}}
        for extra in [{'limits':{'monthly_budget':float('nan')}},{'sandbox':{'kind':'user'}},{'egress':{'allow_hosts':['attacker.example']}}, {'limits':{'max_output_tokens':-1}}]:
            with self.subTest(extra=extra),self.assertRaises(PolicyError):validate(dict(base,**extra),Path('/tmp/config/door.json'),Path('/tmp/state'))
    def test_last_valid_reload_retained(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'door.json';p.write_text(json.dumps({'version':1,'agent':{'alias':'desk','exports':[{'name':'r','repo':'/tmp/r'}]}}))
            holder=PolicyHolder(p,Path(d)/'state');old=holder.policy;p.write_text('{bad')
            self.assertEqual(holder.refresh(),old);self.assertTrue(holder.error)
    def test_filter_absolute_paths_hostnames_controls(self):
        out=filter_reply('\x1b[31m /opt/company/code\x00 mymac',hostnames=['mymac'])
        self.assertGreaterEqual(out['redactions'],2);self.assertNotIn('/opt',out['text']);self.assertNotIn('\x00',out['text'])
    def test_container_no_home_or_socket_and_tools_only(self):
        cmd=ContainerRuntime().build_command({'name':'door-run-test','cpus':2,'memory_mb':512,'export_dir':'/tmp/export',
             'outbox_dir':'/tmp/outbox','placeholder_key':'FAKE','prompt':'Q','model':'m'})
        self.assertIn('--read-only',cmd);self.assertIn('--cap-drop=ALL',cmd);self.assertIn('door-internal',cmd)
        self.assertIn('--tools',cmd);self.assertNotIn('/var/run/docker.sock',' '.join(cmd));self.assertNotIn(str(Path.home())+':',' '.join(cmd))
    def test_plow_sender_roster_identity(self):
        chat={'uid':'cht_x','participants':[{'type':'agent','relationship':'self','line':{'uid':'ln_x','provider_type':'imessage'}},
              {'type':'member','uid':'p','provider_key':'+5511888888888'}]}
        msg={'uid':'msg_x','direction':'inbound','body':'Q','sender':{'type':'member','uid':'p','provider_key':'+5511888888888'}}
        self.assertFalse(PlowAPI.normalize(chat,msg,'ln_x')['is_group'])
        chat['participants'].append({'type':'member','uid':'other'});self.assertTrue(PlowAPI.normalize(chat,msg,'ln_x')['is_group'])
        self.assertIsNone(PlowAPI.normalize(chat,msg,'ln_wrong'))


if __name__=='__main__':unittest.main()
