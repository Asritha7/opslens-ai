'use strict';
(() => {
  const $ = id => document.getElementById(id);
  let authMode = 'loading';
  let token = '', epoch = 0, querySequence = 0, viewSequence = 0, lastQuery = null, draftSequence = 0, reviewSequence = 0;
  const node = (tag, text, className) => {
    const item = document.createElement(tag);
    if (text !== undefined) item.textContent = text;
    if (className) item.className = className;
    return item;
  };
  const button = (text, action) => {
    const item = node('button', text); item.type = 'button'; item.addEventListener('click', action); return item;
  };
  function clearViewer() {
    viewSequence++; $('viewer').hidden = true; $('document-lines').replaceChildren();
    $('viewer-title').textContent = 'Document revision'; $('viewer-meta').textContent = ''; $('checksum').textContent = '';
  }
  function reset(message = 'Disconnected. Enter a key to reconnect.') {
    epoch++; querySequence++; token = ''; lastQuery = null;
    $('key').value = ''; $('query-fields').disabled = true; $('access-form').hidden = authMode !== 'demo'; $('google-access').hidden = authMode !== 'google';
    $('disconnect').hidden = true; $('identity').textContent = authMode === 'google' ? 'Sign in with Google. Access is assigned by Runreviq.' : 'Connect with a local demo key. Your role is assigned by the server.';
    $('access-status').textContent = message; $('result').replaceChildren(); clearViewer();
    $('query-status').textContent = 'Connect and describe your situation to begin.';
    draftSequence++; $('draft-fields').disabled = true; $('draft-file').value = ''; $('draft-list').replaceChildren(); $('draft-preview').replaceChildren(); $('draft-status').textContent = 'Connect to upload or view your drafts.';
    reviewSequence++; $('review-queue').replaceChildren(); $('submission-preview').replaceChildren(); $('load-review-queue').disabled = true; $('review-status').textContent = 'Connect to check reviewer access.';
    $('connect').disabled = false; $('submit-query').disabled = false;
  }
  async function request(path, options = {}, credential = token) {
    const {contentType, ...fetchOptions} = options;
    const response = await fetch(path, {...fetchOptions, cache: 'no-store', credentials: authMode === 'google' ? 'same-origin' : 'omit', redirect: 'error',
      headers: {...(authMode === 'google' ? {'X-Runreviq-Request':'1'} : {'Authorization': `Bearer ${credential}`}), ...(options.body ? {'Content-Type': contentType || 'application/json'} : {})}});
    if (!response.ok) {
      const error = new Error(response.status === 401 ? 'Access expired or credentials missing. Reconnect to continue.' :
        response.status === 403 ? 'Your account has no permitted role, or this request was rejected. Reconnect or contact the operator.' :
        response.status === 404 ? 'This document or draft is unavailable or you no longer have access.' :
        response.status === 409 ? 'This draft was edited in another tab. Your edits remain here; copy them before loading the latest draft.' :
        response.status === 413 ? 'The file exceeds the 1 MB limit.' :
        response.status === 429 ? 'Your account has reached its 20-draft limit. Contact the local operator.' :
        response.status === 422 ? (path.endsWith('/review') ? 'Check the six review fields (at most 200 characters each) and the review revision.' : path.startsWith('/v1/drafts') ? 'Use a nonempty UTF-8 Markdown file with a simple .md filename.' : 'Check the service, version, environment, and key-rotation values.') :
        'The service is unavailable. Check the local server and database, then retry.');
      error.status = response.status; throw error;
    }
    return response.status === 204 ? null : response.json();
  }
  function fail(error, target) {
    if (error.status === 401 || error.status === 403) {
      reset(error.message);
      if (error.status === 403 && authMode === 'google') $('disconnect').hidden = false;
    }
    else $(target).textContent = error.status ? error.message : 'Could not reach the local service. Check that it is running and retry.';
  }
  $('access-form').addEventListener('submit', async event => {
    event.preventDefault(); const credential = $('key').value.trim();
    reset('Checking access…'); const generation = epoch; $('connect').disabled = true;
    try {
      const identity = await request('/v1/me', {}, credential);
      if (generation !== epoch) return;
      token = credential; $('identity').textContent = `${identity.subject} · ${identity.role}`;
      $('access-form').hidden = true; $('disconnect').hidden = false; $('query-fields').disabled = false; $('draft-fields').disabled = false; $('load-review-queue').disabled = false; $('draft-status').textContent = 'Choose a Markdown file or load your saved drafts.';
      $('access-status').textContent = 'Connected. Access is limited to your assigned role.'; $('service').focus();
    } catch (error) { if (generation === epoch) fail(error, 'access-status'); }
    finally { if (generation === epoch) $('connect').disabled = false; }
  });
  $('disconnect').addEventListener('click', async () => {
    const google = authMode === 'google'; reset('Disconnected.');
    if (google) {
      try { await request('/auth/logout', {method:'POST'}); }
      catch (_) { $('access-status').textContent = 'Could not confirm server logout. Your session may still be active; retry Disconnect.'; $('disconnect').hidden = false; }
    }
  });
  window.addEventListener('pagehide', () => reset());
  $('close-viewer').addEventListener('click', clearViewer);

  async function initializeAccess() {
    const generation = epoch;
    try {
      const response = await fetch('/auth/config', {cache:'no-store', credentials:'omit', redirect:'error'});
      if (!response.ok) throw new Error('Configuration unavailable');
      const config = await response.json();
      if (generation !== epoch) return;
      if (!['google', 'demo'].includes(config.mode)) throw new Error('Unknown mode');
      authMode = config.mode;
      $('access-hint').textContent = authMode === 'google' ? 'Your session lasts up to one hour. Disconnect signs out of Runreviq.' : 'Key stays in this page’s memory. Reloading or disconnecting clears access.';
      $('access-form').hidden = authMode !== 'demo'; $('google-access').hidden = authMode !== 'google';
      if (authMode === 'google') {
        $('identity').textContent = 'Sign in with Google. Access is assigned by Runreviq.';
        try {
          const identity = await request('/auth/session');
          if (generation !== epoch) return;
          $('disconnect').hidden = false;
          if (!identity.role) {
            $('access-status').textContent = `Signed in, but no role is assigned. Give the operator your Google subject ID: ${identity.subject}`;
            return;
          }
          token = 'session'; $('google-access').hidden = true; $('query-fields').disabled = false; $('draft-fields').disabled = false; $('load-review-queue').disabled = false; $('draft-status').textContent = 'Choose a Markdown file or load your saved drafts.';
          $('identity').textContent = `Google account · ${identity.role}`;
          $('access-status').textContent = 'Connected with a server session. Disconnect to sign out.';
        } catch (error) {
          if (generation === epoch) {
            if (error.status === 401) error.message = window.location?.search === '?login=failed' ?
              'Google sign-in was cancelled or could not be verified. Please try again.' : 'Continue with Google to access this workspace.';
            fail(error, 'access-status');
          }
        }
      }
    } catch (_) {
      if (generation === epoch) $('access-status').textContent = 'Authentication configuration unavailable. Check the server and reload.';
    }
  }
  initializeAccess();

  async function openDocument(reference, citation) {
    clearViewer(); const sequence = viewSequence, generation = epoch;
    $('viewer').hidden = false; $('viewer-meta').textContent = 'Loading authorized revision…';
    $('viewer').scrollIntoView({behavior: 'smooth', block: 'start'});
    try {
      const doc = await request(`/v1/documents/${encodeURIComponent(reference.document_id)}/revisions/${encodeURIComponent(reference.revision)}`);
      if (generation !== epoch || sequence !== viewSequence) return;
      $('viewer-title').textContent = `${doc.document_id} · ${doc.title}`;
      $('viewer-meta').textContent = `Revision ${doc.revision} · ${doc.is_current ? 'Current revision' : `Historical revision — current is ${doc.current_revision}`} · Recorded status: ${doc.revision_status}`;
      const lines = doc.content.split(/\r\n|\n|\r/); if (lines.at(-1) === '') lines.pop();
      const quoteMatches = citation && citation.document_id === doc.document_id && citation.revision === doc.revision &&
        lines.slice(citation.start_line - 1, citation.end_line).join('\n') === citation.quote;
      lines.forEach((text, index) => $('document-lines').append(node('li', text || ' ', quoteMatches && index + 1 >= citation.start_line && index + 1 <= citation.end_line ? 'cited' : '')));
      $('checksum').textContent = doc.checksum; $('viewer-title').focus();
    } catch (error) { if (generation === epoch && sequence === viewSequence) fail(error, 'viewer-meta'); }
  }
  function evidenceCard(doc) {
    const card = node('article', undefined, 'card');
    card.append(node('h3', doc.title || doc.document_id), node('p', `${doc.document_id} · revision ${doc.revision}`));
    card.append(button('Read stored revision', () => openDocument(doc))); return card;
  }
  function render(result) {
    const root = $('result'); root.replaceChildren();
    const labels = {selected:'Guidance found', conflict:'Conflicting guidance', needs_context_or_review:'More information needed', insufficient_evidence:'Insufficient evidence'};
    const status = Object.hasOwn(labels, result.status) ? result.status : 'insufficient_evidence';
    const banner = node('div', undefined, `banner ${status}`);
    banner.append(node('span', labels[status], 'badge'), node('p', result.message)); root.append(banner);
    const steps = node('ul'); for (const step of result.next_steps) steps.append(node('li', step)); root.append(steps);
    for (const question of result.questions) {
      const box = node('section', undefined, 'question'); box.append(node('h3', question.question));
      if (question.field === 'key_rotation_enabled') for (const value of [true, false]) {
        box.append(button(value ? 'Yes, enabled' : 'No, disabled', () => {
          $('rotation').value = String(value); runQuery({...lastQuery, key_rotation_enabled: value});
        }));
      }
      root.append(box);
    }
    if (result.review_items.length) {
      root.append(node('h3', 'Metadata needs review'));
      const reasons = {metadata_unverified:'Metadata has not been verified', missing_environment:'Environment is missing', missing_version_min:'Minimum software version is missing', missing_version_max_exclusive:'Maximum software version is missing'};
      for (const item of result.review_items) {
        const card = evidenceCard(item); card.append(node('p', item.reasons.map(reason => reasons[reason] || reason).join('; '))); root.append(card);
      }
    }
    for (const conflict of result.conflict_details) {
      root.append(node('h3', `Disagreement: ${conflict.action.replaceAll('_', ' ')}`));
      const cards = node('div', undefined, 'cards');
      for (const doc of conflict.documents) {
        const card = evidenceCard(doc);
        card.append(node('p', `Catalog rules: ${doc.rules.join(', ')}. These rules are manually reviewed.`));
        if (doc.citation_status !== 'available') card.append(node('p', 'Citations are incomplete; review the original document.'));
        for (const cite of doc.citations || []) {
          card.append(node('blockquote', cite.quote), node('p', `Source lines ${cite.start_line}–${cite.end_line} · ${cite.rule}`, 'hint'));
          card.append(button('Open cited passage', () => openDocument(doc, cite)));
        }
        cards.append(card);
      }
      root.append(cards);
    }
    if (!result.conflict_details.length && result.evidence.length) {
      root.append(node('h3', status === 'selected' ? 'Supporting revisions' : 'Applicable evidence — recommendation withheld'));
      const cards = node('div', undefined, 'cards'); for (const doc of result.evidence) cards.append(evidenceCard(doc)); root.append(cards);
    }
  }
  async function runQuery(query) {
    if (!token) return;
    const generation = epoch, sequence = ++querySequence; lastQuery = {...query};
    $('result').replaceChildren(); clearViewer(); $('query-status').textContent = 'Checking authorized evidence…'; $('submit-query').disabled = true;
    try {
      const result = await request('/v1/select', {method:'POST', body:JSON.stringify(query)});
      if (generation !== epoch || sequence !== querySequence) return;
      render(result); $('query-status').textContent = `Evaluated ${query.service} · ${query.software_version} · ${query.environment}`;
    } catch (error) { if (generation === epoch && sequence === querySequence) fail(error, 'query-status'); }
    finally { if (generation === epoch && sequence === querySequence) $('submit-query').disabled = false; }
  }
  const draftLabels = {title:'Title', service:'Service', environment:'Environment', version_min:'Minimum version', version_max_exclusive:'Maximum version (exclusive)', key_rotation_enabled:'Key rotation', version_range:'Version range'};
  function renderDraft(draft) {
    const root = $('draft-preview'); root.replaceChildren();
    root.append(node('h3', draft.filename), node('p', 'Unpublished draft · Review required', 'badge'));
    const table = node('table', undefined, 'metadata-table');
    for (const [field, value] of Object.entries(draft.proposal.proposed_metadata)) {
      const row = node('tr'); row.append(node('th', draftLabels[field] || field), node('td', value === null ? 'No requirement' : String(value))); table.append(row);
    }
    root.append(node('h3', 'Original extraction'), table);
    if (draft.proposal.issues.length) {
      root.append(node('h3', 'Original extraction issues'));
      const issues = node('ul');
      for (const issue of draft.proposal.issues) issues.append(node('li', `${draftLabels[issue.field] || issue.field}: ${issue.reason.replaceAll('_', ' ')}`));
      root.append(issues);
    } else root.append(node('p', 'Fields were extracted. A person still needs to verify them before any future publication.'));
    const provenance = node('details'); provenance.append(node('summary', 'View extraction source lines'));
    for (const [field, entries] of Object.entries(draft.proposal.provenance)) for (const entry of entries) {
      provenance.append(node('p', `${draftLabels[field] || field} · line ${entry.line}`), node('blockquote', entry.quote));
    }
    root.append(provenance);
    const source = node('details'); source.append(node('summary', 'View stored Markdown'), node('pre', draft.content)); root.append(source);
    root.append(node('p', 'Original source and extraction stay unchanged. Your edits are private review progress, not approval or publication.', 'hint'));
    renderReviewEditor(draft, root);
    renderSubmissionControls(draft, root);
  }
  function renderReviewEditor(draft, root) {
    root.append(node('h3', 'Your metadata edits'));
    root.append(node('p', draft.review ? `Saved review ${draft.review.revision} · Still unpublished` : 'No edits saved yet. Fields below start from the extraction.'));
    const issues = draft.review ? draft.review.issues : draft.proposal.issues;
    const issueList = node('ul');
    for (const issue of issues) issueList.append(node('li', `${draftLabels[issue.field] || issue.field}: ${issue.reason.replaceAll('_', ' ')}`));
    root.append(issueList);
    if (!issues.length) root.append(node('p', 'Fields pass format checks. Accuracy and approval still require a person.'));
    const form = node('form'), fields = node('fieldset'), inputs = {};
    for (const field of ['title', 'service', 'environment', 'version_min', 'version_max_exclusive', 'key_rotation_enabled']) {
      const input = node('input'); input.id = `review-${field}`; input.type = 'text'; input.maxLength = 200;
      const extracted = draft.proposal.proposed_metadata[field];
      input.value = draft.review ? draft.review.metadata[field] : extracted === undefined ? '' : extracted === null ? 'none' : String(extracted);
      const label = node('label', draftLabels[field]); label.htmlFor = input.id;
      fields.append(label, input); inputs[field] = input;
    }
    fields.append(node('p', 'Environment: production or staging. Versions: X.Y.Z. Key rotation: true, false, or none (no requirement). Blank means missing; you may save incomplete work.', 'hint'));
    const save = node('button', 'Save review progress'); save.type = 'submit';
    fields.append(save); form.append(fields); root.append(form);
    if (draft.review && draft.review.revision >= 100) {
      fields.disabled = true; root.append(node('p', 'This draft has reached its 100-save limit. Contact the local operator.')); return;
    }
    form.addEventListener('submit', async event => {
      event.preventDefault(); if (!token || fields.disabled) return;
      const generation = epoch, sequence = ++draftSequence;
      const current = () => generation === epoch && sequence === draftSequence;
      fields.disabled = true; $('draft-fields').disabled = true;
      $('draft-status').textContent = 'Saving your review progress…';
      const metadata = Object.fromEntries(Object.entries(inputs).map(([key, input]) => [key, input.value]));
      try {
        const review = await request(`/v1/drafts/${encodeURIComponent(draft.id)}/review`, {method:'POST', body:JSON.stringify({expected_revision:draft.review ? draft.review.revision : 0, metadata})});
        if (!current()) return;
        renderDraft({...draft, review}); $('draft-status').textContent = 'Review progress saved. This draft is still unpublished.';
      } catch (error) { if (current()) fail(error, 'draft-status'); }
      finally { if (current()) { fields.disabled = false; $('draft-fields').disabled = false; } }
    });
  }
  function workflowMessage(error) {
    if (error.status === 409) return 'This revision changed or already has a decision. Reload before continuing.';
    if (error.status === 422) return 'Save complete, valid metadata before submitting. Decisions require a nonempty comment.';
    return error.status ? error.message : 'Could not reach the local review service. Retry when it is available.';
  }
  function renderSubmissionControls(draft, root) {
    root.append(node('h3', 'Submit for independent review'));
    root.append(node('p', 'Submission shares this document’s full source, original extraction, and selected saved metadata revision with designated reviewers. Unsaved edits are excluded. Approval will not publish it.', 'hint'));
    const status = node('p'), history = node('div'); status.role = 'status';
    const generation = epoch, sequence = draftSequence;
    const current = () => generation === epoch && sequence === draftSequence;
    const loadHistory = async () => {
      const result = await request(`/v1/drafts/${encodeURIComponent(draft.id)}/submissions`);
      if (!current()) return;
      history.replaceChildren();
      for (const item of result.submissions) history.append(node('p', `Revision ${item.revision} · ${item.status.replaceAll('_', ' ')}${item.comment ? ' · ' + item.comment : ''}`));
      if (!result.submissions.length) history.append(node('p', 'No submitted revisions yet.'));
    };
    const submit = button(draft.review ? `Submit saved revision ${draft.review.revision}` : 'Save complete metadata before submitting', async () => {
      submit.disabled = true; status.textContent = 'Submitting saved revision…';
      try {
        await request(`/v1/drafts/${encodeURIComponent(draft.id)}/submit`, {method:'POST', body:JSON.stringify({revision:draft.review.revision})});
        if (!current()) return;
        status.textContent = 'Submitted for independent review. Still unpublished.'; await loadHistory();
      } catch (error) { if (current()) { if(error.status===401) fail(error,'draft-status'); else status.textContent=workflowMessage(error); } }
      finally { if(current()) submit.disabled = !draft.review || !!draft.review.issues.length; }
    });
    submit.disabled = !draft.review || !!draft.review.issues.length;
    const load = button('Check submission status', async () => {
      try { await loadHistory(); } catch (error) { if(current()) { if(error.status===401) fail(error,'draft-status'); else status.textContent=workflowMessage(error); } }
    });
    root.append(submit, load, status, history);
  }
  async function reviewerOperation(action) {
    if (!token) return;
    const generation=epoch, sequence=++reviewSequence;
    const current=()=>generation===epoch && sequence===reviewSequence;
    $('load-review-queue').disabled=true; $('submission-preview').replaceChildren(); $('review-queue').replaceChildren();
    $('review-status').textContent='Loading review workspace…';
    try { await action(current); }
    catch(error) { if(current()) { $('review-queue').replaceChildren(); $('submission-preview').replaceChildren(); if(error.status===401) fail(error,'review-status'); else $('review-status').textContent=workflowMessage(error); } }
    finally { if(current()) $('load-review-queue').disabled=false; }
  }
  $('load-review-queue').addEventListener('click',()=>reviewerOperation(async current=>{
    const access=await request('/v1/reviewer-access'); if(!current()) return;
    if(!access.can_review) { $('review-status').textContent='Reviewer permission has not been assigned to your account. Reading roles do not grant it.'; return; }
    const result=await request('/v1/submissions'); if(!current()) return;
    $('review-status').textContent=result.submissions.length ? 'Pending submissions (up to 100, oldest first). Your own documents are excluded.' : 'No pending submissions from other authors.';
    for(const item of result.submissions) $('review-queue').append(button(`${item.filename} · revision ${item.revision}`,()=>reviewerOperation(async active=>{
      const detail=await request(`/v1/submissions/${encodeURIComponent(item.id)}`); if(!active()) return;
      renderSubmitted(detail); $('review-status').textContent='Inspect the source and submitted metadata before recording a decision.';
    })));
  }));
  function renderSubmitted(item) {
    const root=$('submission-preview'); root.append(node('h3', `${item.filename} · submitted revision ${item.revision}`),node('p','Unpublished · '+item.status.replaceAll('_',' ')));
    const table=node('table',undefined,'metadata-table');
    for(const [field,value] of Object.entries(item.review.metadata)) { const row=node('tr'); row.append(node('th',draftLabels[field]||field),node('td',value)); table.append(row); }
    root.append(table);
    const original=node('details'); original.append(node('summary','Original extraction and source lines'));
    for(const [field,value] of Object.entries(item.proposal.proposed_metadata||{})) original.append(node('p',`${draftLabels[field]||field}: ${value===null?'No requirement':String(value)}`));
    for(const issue of item.proposal.issues||[]) original.append(node('p',`${draftLabels[issue.field]||issue.field}: ${issue.reason.replaceAll('_',' ')}`));
    for(const [field,entries] of Object.entries(item.proposal.provenance||{})) for(const entry of entries) original.append(node('p',`${draftLabels[field]||field} · line ${entry.line}`),node('blockquote',entry.quote));
    root.append(original);
    const source=node('details'); source.append(node('summary','Submitted document source'),node('pre',item.content)); root.append(source);
    if(item.status!=='pending') { root.append(node('p',item.comment||'')); return; }
    const form=node('form'), fields=node('fieldset'), choice=node('select'), comment=node('textarea');
    choice.id='review-decision'; choice.required=true;
    for(const [value,label] of [['','Choose a decision'],['changes_requested','Request changes'],['approved','Approve this revision']]) { const option=node('option',label); option.value=value; choice.append(option); }
    comment.id='review-comment'; comment.maxLength=2000; comment.required=true;
    const label=node('label','Decision'); label.htmlFor=choice.id; const commentLabel=node('label','Review comment (required)'); commentLabel.htmlFor=comment.id;
    const save=node('button','Record decision'); save.type='submit';
    fields.append(label,choice,commentLabel,comment,node('p','This decision is final for this submitted revision. Approval does not publish or grant document access.', 'hint'),save);form.append(fields);root.append(form);
    form.addEventListener('submit',async event=>{
      event.preventDefault(); if(!token||fields.disabled) return;
      const generation=epoch, sequence=reviewSequence, current=()=>generation===epoch&&sequence===reviewSequence;
      fields.disabled=true; $('load-review-queue').disabled=true;
      try {
        const result=await request(`/v1/submissions/${encodeURIComponent(item.id)}/decision`,{method:'POST',body:JSON.stringify({decision:choice.value,comment:comment.value})});
        if(!current()) return;
        root.replaceChildren(); renderSubmitted({...item,status:result.status,comment:result.comment}); $('review-status').textContent='Decision recorded. The document remains unpublished.';
      } catch(error) { if(current()) { if(error.status===401) fail(error,'review-status'); else { $('review-status').textContent=workflowMessage(error); if(error.status===403) root.replaceChildren(); } } }
      finally { if(current()) { fields.disabled=false; $('load-review-queue').disabled=false; } }
    });
  }

  async function draftOperation(action) {
    if (!token) return;
    const generation = epoch, sequence = ++draftSequence;
    $('draft-fields').disabled = true; $('draft-preview').replaceChildren(); $('draft-list').replaceChildren();
    $('draft-status').textContent = 'Working on your private draft…';
    const current = () => generation === epoch && sequence === draftSequence;
    try { await action(current); }
    catch (error) { if (current()) fail(error, 'draft-status'); }
    finally { if (current()) $('draft-fields').disabled = false; }
  }
  $('draft-form').addEventListener('submit', event => {
    event.preventDefault();
    const file = $('draft-file').files[0];
    if (!file || file.size > 1000000 || !/\.md$/i.test(file.name)) {
      $('draft-status').textContent = 'Choose a Markdown (.md) file of at most 1 MB.'; return;
    }
    draftOperation(async current => {
      const data = await file.arrayBuffer(); if (!current()) return;
      const draft = await request(`/v1/drafts?filename=${encodeURIComponent(file.name)}`, {method:'POST', body:data, contentType:'text/markdown'});
      if (!current()) return;
      renderDraft(draft); $('draft-file').value = ''; $('draft-status').textContent = 'Saved privately. Review the extraction below; this document is not published.';
    });
  });
  $('load-drafts').addEventListener('click', () => draftOperation(async current => {
    const result = await request('/v1/drafts'); if (!current()) return;
    $('draft-status').textContent = result.drafts.length ? 'Your saved drafts. Choose one to inspect.' : 'You have no saved drafts yet.';
    for (const draft of result.drafts) $('draft-list').append(button(draft.filename, () => draftOperation(async active => {
      const saved = await request(`/v1/drafts/${encodeURIComponent(draft.id)}`); if (!active()) return;
      renderDraft(saved); $('draft-status').textContent = 'Stored draft loaded. Review is still required.';
    })));
  }));

  $('query-form').addEventListener('submit', event => {
    event.preventDefault(); const rotation = $('rotation').value;
    runQuery({service:$('service').value.trim(), software_version:$('version').value.trim(), environment:$('environment').value,
      key_rotation_enabled:rotation === 'unknown' ? null : rotation === 'true'});
  });
})();
