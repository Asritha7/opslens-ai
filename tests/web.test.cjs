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
  vm.runInNewContext(fs.readFileSync('opslens/web/app.js','utf8'),context);
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
  assert.equal(h.pending[1].options.headers['X-OpsLens-Request'],'1');
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
