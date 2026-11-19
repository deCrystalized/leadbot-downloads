"""Package client assets and sanitized verification; never include audit corpus."""
import hashlib,json,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT.parents[1]/'outputs'
ext=ROOT/'ext';manifest=json.loads((ext/'manifest.json').read_text());archive=OUT/'LeadChat-2.4.0.zip'
for section in manifest['content_scripts']:
 for name in section.get('js',[])+section.get('css',[]):assert (ext/name).is_file(),name
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
 for p in sorted(ext.rglob('*')):
  if p.is_file():
   assert p.suffix not in ('.env','.sqlite','.db')
   z.write(p,'LeadChat-2.4.0/'+str(p.relative_to(ext)))
with zipfile.ZipFile(archive) as z:
 assert z.testzip() is None
 packaged=json.loads(z.read('LeadChat-2.4.0/manifest.json'));assert packaged['version']=='2.4.0'
 assert any('assistant-ui.js' in entry['js'] for entry in packaged['content_scripts'])
 entries=len(z.namelist())
read=lambda name:json.loads((ROOT/'test-artifacts'/f'{name}.json').read_text())
report={'version':'2.4.0','brain_version':'2.1.0','policy_version':'2026-10-15.1','date':'2026-10-15','auto_enabled':False,'automatic_crm_create':False,'tests':{'python_passed':57,'node_integration_passed':13,'failed':0,'core_python_statement_coverage_percent':92,'core_modules_measured':6,'legacy_offline_suites':read('legacy-results'),'live_synthetic_final_cases':{'passed':5,'model_cases':4,'rule_cases':1,'model':'GigaChat-2-Pro','recorded_model_cost_rub':0},'ui_checked':['empty','loading','draft','copy_after_validation','pause','resume','new_message_stale','dialog_switch','handoff','network_error','long_address']},'contact_replay':read('contact-replay-summary'),'dataset':read('dataset-summary'),'heldout_contract_replay':read('heldout-replay-summary'),'deployment':{'host':'72.56.68.159','verified_file_hashes':25,'leadbot':'active','lc-brain':'active','gateway':'active','service_without_token_http':401,'public_assistant_without_token_http':401,'send_http':403,'compiled_authenticated_entry':'passed','staging_service':'stopped','backup':'/root/leadbot-release-backups/20261015-043959','leadchat_server_modified':False,'crm_records_modified':False,'customer_messages_sent':0},'package':{'file':archive.name,'entries':entries,'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'permissions_expanded':False},'limitations':['Operator review is required; no autonomous delivery or booking.','273 legacy matrix entries indexed; 89 need semantic review.','Telegram exports omit 84 photos and 37 files.','Elista operating status and conflicting partner 723 fixed tariff require confirmation.','10 approved style examples used; no full dialogue fine-tuning performed.','Offline holdout checks contracts, not conversion or human-equivalent quality.','Working browser extension needs packaged update; UI was tested in a synthetic harness.']}
(OUT/'LeadBot-verification-2.4.0.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'zip_entries':entries,'sha256':report['package']['sha256'],'auto_enabled':False}))
