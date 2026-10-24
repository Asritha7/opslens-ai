const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
class Element {
  constructor(tag='div') { this.tag=tag; this.children=[]; this.listeners={}; this.value=''; this.textContent=''; this.hidden=false; this.disabled=false; }
  addEventListener(name, callback) { this.listeners[name]=callback; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children=nodes; }
  set innerHTML(value) { throw Error('Unsafe HTML insertion'); }
  focus() {} scrollIntoView() {}
  fire(name) { return this.listeners[name]({preventDefault(){}}); }
}
function harness(mode='demo') {
  const elements={}, pending=[], events={};
  const get=id=>elements[id] ||= new Element();
  get('service').value='identity-service'; get('version').value='2.4.0'; get('environment').value='production'; get('rotation').value='unknown';
  const context={document:{getElementById:get,createElement:tag=>new Element(tag)},window:{addEventListener:(name,fn)=>events[name]=fn},
    fetch:(url,options)=>url === '/auth/config' ? Promise.resolve({ok:true,json:async()=>({mode})}) : new Promise(resolve=>pending.push({url,options,resolve}))};
  vm.runInNewContext(fs.readFileSync('runreviq/web/app.js','utf8'),context);
  const respond=(index,data,status=200)=>pending[index].resolve({ok:status===200,status,json:async()=>data});
  const login=async()=>{ get('key').value='test-key'; const done=get('access-form').fire('submit'); respond(pending.length-1,{subject:'test',role:'platform'}); await done; };
  return {get,pending,respond,login,events};
}
const result={status:'selected',message:'Guidance',next_steps:[],questions:[],review_items:[],conflict_details:[],evidence:[{document_id:'RB-042',revision:1}]};
function find(root,text) { if(root.tag==='button' && root.textContent===text) return root; for(const child of root.children){ const found=find(child,text); if(found)return found; } }
const tick=()=>new Promise(resolve=>setImmediate(resolve));
test('key is cleared from input and only sent in headers; pagehide clears evidence',async()=>{
  const h=harness(); await h.login(); assert.equal(h.get('key').value,'');
  const done=h.get('query-form').fire('submit');
  assert.equal(h.pending[1].options.headers.Authorization,'Bearer test-key');
  assert.equal(h.pending[1].options.credentials,'omit'); assert.equal(h.pending[1].options.redirect,'error');
  assert.equal(h.pending[1].url,'/v1/select');
  h.respond(1,result); await tick(); assert.ok(h.get('result').children.length);
  h.events.pagehide(); assert.equal(h.get('result').children.length,0); assert.equal(h.get('query-fields').disabled,true);
});
test('late query response cannot repopulate results after disconnect',async()=>{
  const h=harness(); await h.login(); h.get('query-form').fire('submit'); h.get('disconnect').fire('click');
  h.respond(1,result); await tick(); assert.equal(h.get('result').children.length,0); assert.equal(h.get('viewer').hidden,true);
});
test('a newer query wins even if the older one finishes later',async()=>{
  const h=harness(); await h.login(); h.get('query-form').fire('submit'); h.get('version').value='2.5.0'; h.get('query-form').fire('submit');
  h.respond(2,{...result,message:'New result'}); await tick(); h.respond(1,{...result,message:'Old result'}); await tick();
  assert.equal(h.get('result').children[0].children[1].textContent,'New result');
});
test('source HTML is plain text; document failures clear previously displayed content',async()=>{
  const h=harness(); await h.login(); h.get('query-form').fire('submit'); h.respond(1,result); await tick();
  find(h.get('result'),'Read stored revision').fire('click');
  h.respond(2,{document_id:'RB-042',revision:1,title:'<img onerror=evil()>',content:'<script>evil()</script>',checksum:'abc',current_revision:2,is_current:false,revision_status:'approved'}); await tick();
  assert.equal(h.get('document-lines').children[0].textContent,'<script>evil()</script>');
  assert.match(h.get('viewer-meta').textContent,/Historical revision/);
  find(h.get('result'),'Read stored revision').fire('click'); h.respond(3,{},404); await tick();
  assert.equal(h.get('document-lines').children.length,0); assert.match(h.get('viewer-meta').textContent,/unavailable/);
});
test('401 clears identity and all visible evidence',async()=>{
  const h=harness(); await h.login(); h.get('query-form').fire('submit'); h.respond(1,result); await tick();
  find(h.get('result'),'Read stored revision').fire('click'); h.respond(2,{},401); await tick();
  assert.equal(h.get('result').children.length,0); assert.equal(h.get('viewer').hidden,true); assert.equal(h.get('query-fields').disabled,true);
});

test('Google session uses cookies without a bearer and logout clears evidence',async()=>{
  const h=harness('google'); await tick();
  assert.equal(h.pending[0].url,'/auth/session');
  h.respond(0,{subject:'google-user',role:'platform'}); await tick();
  assert.equal(h.get('query-fields').disabled,false);
  h.get('query-form').fire('submit');
  assert.equal(h.pending[1].options.credentials,'same-origin');
  assert.equal(h.pending[1].options.headers.Authorization,undefined);
  assert.equal(h.pending[1].options.headers['X-Runreviq-Request'],'1');
  h.respond(1,result); await tick();
  const done=h.get('disconnect').fire('click');
  assert.equal(h.get('result').children.length,0);
  assert.equal(h.pending[2].url,'/auth/logout');
  h.pending[2].resolve({ok:true,status:204}); await done;
});
test('unassigned Google account cannot query and sees its assignment identifier',async()=>{
  const h=harness('google'); h.get('query-fields').disabled=true; await tick();
  h.respond(0,{subject:'unassigned-user',role:null}); await tick();
  assert.equal(h.get('query-fields').disabled,true);
  assert.match(h.get('access-status').textContent,/unassigned-user/);
  h.get('query-form').fire('submit'); assert.equal(h.pending.length,1);
});
test('a denied Google query clears displayed evidence',async()=>{
  const h=harness('google'); await tick(); h.respond(0,{subject:'user',role:'platform'}); await tick();
  h.get('query-form').fire('submit'); h.respond(1,result); await tick();
  h.get('query-form').fire('submit'); h.respond(2,{},403); await tick();
  assert.equal(h.get('result').children.length,0); assert.equal(h.get('query-fields').disabled,true);
});
const draftFixture={id:'draft-id',filename:'example.md',content:'<script>untrusted()</script>',proposal:{proposed_metadata:{title:'Example'},provenance:{title:[{line:1,quote:'# Example'}]},issues:[],review_required:true}};
test('draft upload sends raw Markdown and clears preview on disconnect',async()=>{
  const h=harness(); await h.login();
  const data=new Uint8Array([35,32,65]).buffer;
  h.get('draft-file').files=[{name:'example.md',size:3,arrayBuffer:async()=>data}];
  h.get('draft-form').fire('submit'); await tick();
  assert.equal(h.pending[1].url,'/v1/drafts?filename=example.md');
  assert.equal(h.pending[1].options.headers['Content-Type'],'text/markdown');
  assert.equal(h.pending[1].options.body,data);
  h.respond(1,draftFixture); await tick();
  assert.ok(h.get('draft-preview').children.length);
  h.get('disconnect').fire('click'); assert.equal(h.get('draft-preview').children.length,0);
  assert.equal(h.get('draft-fields').disabled,true);
});
test('late draft upload cannot restore another session preview',async()=>{
  const h=harness(); await h.login();
  h.get('draft-file').files=[{name:'example.md',size:3,arrayBuffer:async()=>new ArrayBuffer(3)}];
  h.get('draft-form').fire('submit'); await tick(); h.get('disconnect').fire('click');
  h.respond(1,draftFixture); await tick();
  assert.equal(h.get('draft-preview').children.length,0); assert.equal(h.get('draft-list').children.length,0);
});
test('saved drafts can be listed and source content remains plain text',async()=>{
  const h=harness(); await h.login(); h.get('load-drafts').fire('click');
  h.respond(1,{drafts:[{id:'draft-id',filename:'example.md'}]}); await tick();
  find(h.get('draft-list'),'example.md').fire('click');
  assert.equal(h.pending[2].url,'/v1/drafts/draft-id');
  h.respond(2,draftFixture); await tick();
  const source=h.get('draft-preview').children.find(e=>e.tag==='details' && e.children.some(c=>c.tag==='pre'));
  assert.equal(source.children.find(e=>e.tag==='pre').textContent,'<script>untrusted()</script>');
});
function descendants(root) { return [root,...root.children.flatMap(descendants)]; }
async function reviewHarness() {
  const h=harness(); await h.login(); h.get('load-drafts').fire('click');
  h.respond(1,{drafts:[{id:'draft-id',filename:'example.md'}]}); await tick();
  find(h.get('draft-list'),'example.md').fire('click'); h.respond(2,draftFixture); await tick();
  const editor=descendants(h.get('draft-preview')).find(e=>e.tag==='form');
  return {h,editor,inputs:descendants(editor).filter(e=>e.tag==='input')};
}
test('review saves corrected values with revision and retains original extraction',async()=>{
  const {h,editor,inputs}=await reviewHarness(); inputs[0].value='Corrected';
  editor.fire('submit');
  const body=JSON.parse(h.pending[3].options.body);
  assert.equal(body.expected_revision,0); assert.equal(body.metadata.title,'Corrected');
  assert.equal(h.pending[3].url,'/v1/drafts/draft-id/review');
  h.respond(3,{revision:1,metadata:body.metadata,issues:[{field:'service',reason:'missing'}]}); await tick();
  const all=descendants(h.get('draft-preview'));
  assert.ok(all.some(e=>e.textContent==='Example'));
  assert.ok(all.some(e=>e.textContent==='service: missing' || e.textContent==='Service: missing'));
  assert.equal(all.find(e=>e.id==='review-title').value,'Corrected');
});
test('review conflict preserves unsaved input and permits loading latest',async()=>{
  const {h,editor,inputs}=await reviewHarness(); inputs[0].value='Keep this';
  editor.fire('submit'); h.respond(3,{},409); await tick();
  assert.equal(inputs[0].value,'Keep this'); assert.match(h.get('draft-status').textContent,/another tab/);
  assert.equal(h.get('draft-fields').disabled,false);
});
test('review response after logout cannot restore private content',async()=>{
  const {h,editor}=await reviewHarness(); editor.fire('submit'); h.get('disconnect').fire('click');
  h.respond(3,{revision:1,metadata:{},issues:[]}); await tick();
  assert.equal(h.get('draft-preview').children.length,0); assert.equal(h.get('draft-fields').disabled,true);
});
test('reading access does not automatically load the reviewer queue',async()=>{
  const h=harness(); await h.login(); h.get('load-review-queue').fire('click');
  assert.equal(h.pending[1].url,'/v1/reviewer-access'); h.respond(1,{can_review:false}); await tick();
  assert.equal(h.pending.length,2); assert.match(h.get('review-status').textContent,/not been assigned/);
});
test('reviewer decision carries only decision and comment and stays unpublished',async()=>{
  const h=harness(); await h.login(); h.get('load-review-queue').fire('click');
  h.respond(1,{can_review:true}); await tick(); h.respond(2,{submissions:[{id:'sub-id',filename:'source.md',revision:1}]}); await tick();
  find(h.get('review-queue'),'source.md · revision 1').fire('click');
  h.respond(3,{id:'sub-id',filename:'source.md',revision:1,status:'pending',content:'<script>no()</script>',proposal:{},review:{metadata:{title:'Example'}}}); await tick();
  const elements=descendants(h.get('submission-preview'));
  assert.equal(elements.find(e=>e.tag==='pre'&&e.textContent.includes('<script>')).textContent,'<script>no()</script>');
  elements.find(e=>e.id==='review-decision').value='changes_requested'; elements.find(e=>e.id==='review-comment').value='Clarify source';
  elements.find(e=>e.tag==='form').fire('submit');
  assert.deepEqual(JSON.parse(h.pending[4].options.body),{decision:'changes_requested',comment:'Clarify source'});
  h.respond(4,{status:'changes_requested',comment:'Clarify source'}); await tick();
  assert.match(h.get('review-status').textContent,/unpublished/);
});
test('review queue response after logout cannot restore submitted source',async()=>{
  const h=harness(); await h.login(); h.get('load-review-queue').fire('click');
  h.respond(1,{can_review:true}); await tick(); h.get('disconnect').fire('click');
  h.respond(2,{submissions:[{id:'s',filename:'private.md',revision:1}]}); await tick();
  assert.equal(h.get('review-queue').children.length,0); assert.equal(h.get('submission-preview').children.length,0);
});
test('submission sends the displayed saved revision and shows owner feedback',async()=>{
  const {h,editor}=await reviewHarness(); editor.fire('submit');
  const metadata=JSON.parse(h.pending[3].options.body).metadata;
  h.respond(3,{revision:2,metadata,issues:[]}); await tick();
  find(h.get('draft-preview'),'Submit saved revision 2').fire('click');
  assert.equal(h.pending[4].url,'/v1/drafts/draft-id/submit'); assert.deepEqual(JSON.parse(h.pending[4].options.body),{revision:2});
  h.respond(4,{id:'s',revision:2,published:false}); await tick();
  h.respond(5,{submissions:[{revision:2,status:'changes_requested',comment:'Clarify it'}]}); await tick();
  assert.ok(descendants(h.get('draft-preview')).some(e=>e.textContent==='Revision 2 · changes requested · Clarify it · Unpublished'));
});

test('publisher access is separate and denied access does not load documents',async()=>{
  const h=harness();await h.login();h.get('load-publish-queue').fire('click');
  assert.equal(h.pending[1].url,'/v1/publisher-access');h.respond(1,{can_publish:false});await tick();
  assert.equal(h.pending.length,2);assert.match(h.get('publish-status').textContent,/has not been assigned/);
});
test('publication uses explicit roles, verification and source ranges; clears on logout',async()=>{
  const h=harness();await h.login();h.get('load-publish-queue').fire('click');h.respond(1,{can_publish:true});await tick();
  h.respond(2,{submissions:[{id:'s1',filename:'guide.md',revision:1}]});await tick();
  find(h.get('publish-queue'),'guide.md · approved revision 1').fire('click');
  h.respond(3,{id:'s1',filename:'guide.md',revision:1,metadata:{title:'Guide'},review_comment:'Checked',content:'# Guide\n<script>text</script>'});await tick();
  const nodes=descendants(h.get('publish-preview'));
  assert.ok(nodes.some(n=>n.tag==='li'&&n.textContent==='<script>text</script>'));
  const boxes=nodes.filter(n=>n.type==='checkbox');boxes[0].checked=true;boxes[1].checked=true;
  nodes.find(n=>n.pattern).value='rotate_keys';for(const n of nodes.filter(n=>n.type==='number'))n.value='2';
  nodes.find(n=>n.tag==='form').fire('submit');
  assert.equal(h.pending[4].url,'/v1/publications/s1');
  assert.deepEqual(JSON.parse(h.pending[4].options.body),{metadata_verified:true,allowed_roles:['platform'],claims:[{action:'rotate_keys',rule:'must',start_line:2,end_line:2}]});
  h.get('disconnect').fire('click');h.respond(4,{document_id:'UPLOAD-1',revision:1,published_at:'now'});await tick();
  assert.equal(h.get('publish-preview').children.length,0);assert.equal(h.get('load-publish-queue').disabled,true);
});
test('publication rejection preserves form and explains invalid claims',async()=>{
  const h=harness();await h.login();h.get('load-publish-queue').fire('click');h.respond(1,{can_publish:true});await tick();
  h.respond(2,{submissions:[{id:'s1',filename:'guide.md',revision:1}]});await tick();find(h.get('publish-queue'),'guide.md · approved revision 1').fire('click');
  h.respond(3,{id:'s1',filename:'guide.md',revision:1,metadata:{},review_comment:'Checked',content:'text'});await tick();
  const form=descendants(h.get('publish-preview')).find(n=>n.tag==='form');form.fire('submit');h.respond(4,{},422);await tick();
  assert.match(h.get('publish-status').textContent,/source line ranges/);assert.equal(form.children[0].disabled,false);
});

const managedDoc={document_id:'RB-001',current_revision:2,allowed_roles:['platform'],revisions:[{revision:2,title:'Guide',status:'active',is_current:true,published_at:'today',withdrawal:null},{revision:1,title:'Older',status:'superseded',is_current:false,superseded_by:2,published_at:'yesterday',withdrawal:null}]};
async function managementHarness(){
  const h=harness();await h.login();h.get('load-managed').fire('click');
  h.respond(1,{documents:[{document_id:'RB-001',title:'Guide',current_revision:2,status:'active',allowed_roles:['platform'],published_at:'today'}],next_after:null});await tick();
  find(h.get('managed-list'),'Inspect RB-001').fire('click');h.respond(2,managedDoc);await tick();return h;
}
test('withdrawal sends current revision and reason, clears old recommendations and preserves history',async()=>{
  const h=await managementHarness();const nodes=descendants(h.get('managed-history'));
  assert.ok(nodes.some(e=>e.textContent==='Replaced by current revision 2.'));
  nodes.find(e=>e.tag==='textarea').value='Unsafe <script>text</script>';nodes.find(e=>e.type==='checkbox').checked=true;
  h.get('result').append(new Element());nodes.find(e=>e.tag==='form').fire('submit');
  assert.equal(h.pending[3].url,'/v1/publication-management/documents/RB-001/withdraw');
  assert.deepEqual(JSON.parse(h.pending[3].options.body),{expected_revision:2,reason:'Unsafe <script>text</script>'});
  h.respond(3,{revision:2,status:'withdrawn',reason:'Unsafe <script>text</script>',withdrawn_at:'now'});await tick();
  assert.equal(h.get('result').children.length,0);assert.match(h.get('manage-status').textContent,/New queries exclude/);
  assert.ok(descendants(h.get('managed-history')).some(e=>e.textContent.includes('Unsafe <script>text</script>')));
  assert.equal(find(h.get('managed-history'),'Withdraw revision 2'),undefined);
});
test('withdrawal conflict preserves reason and logout discards late source',async()=>{
  const h=await managementHarness();const nodes=descendants(h.get('managed-history'));const reason=nodes.find(e=>e.tag==='textarea');reason.value='Keep this reason';nodes.find(e=>e.type==='checkbox').checked=true;
  nodes.find(e=>e.tag==='form').fire('submit');h.respond(3,{},409);await tick();
  assert.equal(reason.value,'Keep this reason');assert.match(h.get('manage-status').textContent,/Reload/);
  find(h.get('managed-history'),'Inspect source revision 1').fire('click');h.get('disconnect').fire('click');
  h.respond(4,{revision:1,status:'superseded',content:'private'});await tick();
  assert.equal(h.get('managed-source').children.length,0);assert.equal(h.get('managed-history').children.length,0);
});
test('source viewer explicitly warns when formerly recommended evidence is withdrawn',async()=>{
  const h=harness();await h.login();h.get('query-form').fire('submit');h.respond(1,result);await tick();
  find(h.get('result'),'Read stored revision').fire('click');
  h.respond(2,{document_id:'RB-042',revision:1,title:'Guide',content:'source',checksum:'abc',current_revision:1,is_current:true,revision_status:'approved',guidance_status:'withdrawn',withdrawal:{reason:'Outdated'}});await tick();
  assert.match(h.get('viewer-meta').textContent,/WITHDRAWN — do not use as guidance/);
});
