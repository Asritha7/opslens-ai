'use strict';
(() => {
  const $ = id => document.getElementById(id);
  let authMode = 'loading';
  let token = '', epoch = 0, querySequence = 0, viewSequence = 0, lastQuery = null;
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
    $('disconnect').hidden = true; $('identity').textContent = authMode === 'google' ? 'Sign in with Google. Access is assigned by OpsLens.' : 'Connect with a local demo key. Your role is assigned by the server.';
    $('access-status').textContent = message; $('result').replaceChildren(); clearViewer();
    $('query-status').textContent = 'Connect and describe your situation to begin.';
    $('connect').disabled = false; $('submit-query').disabled = false;
  }
  async function request(path, options = {}, credential = token) {
    const response = await fetch(path, {...options, cache: 'no-store', credentials: authMode === 'google' ? 'same-origin' : 'omit', redirect: 'error',
      headers: {...(authMode === 'google' ? {'X-OpsLens-Request':'1'} : {'Authorization': `Bearer ${credential}`}), ...(options.body ? {'Content-Type': 'application/json'} : {})}});
    if (!response.ok) {
      const error = new Error(response.status === 401 ? 'Access expired or credentials missing. Reconnect to continue.' :
        response.status === 403 ? 'Your account has no permitted role, or this request was rejected. Reconnect or contact the operator.' :
        response.status === 404 ? 'This revision is unavailable or you no longer have access.' :
        response.status === 422 ? 'Check the service, version, environment, and key-rotation values.' :
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
      $('access-form').hidden = true; $('disconnect').hidden = false; $('query-fields').disabled = false;
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
      $('access-hint').textContent = authMode === 'google' ? 'Your session lasts up to one hour. Disconnect signs out of OpsLens.' : 'Key stays in this page’s memory. Reloading or disconnecting clears access.';
      $('access-form').hidden = authMode !== 'demo'; $('google-access').hidden = authMode !== 'google';
      if (authMode === 'google') {
        $('identity').textContent = 'Sign in with Google. Access is assigned by OpsLens.';
        try {
          const identity = await request('/auth/session');
          if (generation !== epoch) return;
          $('disconnect').hidden = false;
          if (!identity.role) {
            $('access-status').textContent = `Signed in, but no role is assigned. Give the operator your Google subject ID: ${identity.subject}`;
            return;
          }
          token = 'session'; $('google-access').hidden = true; $('query-fields').disabled = false;
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
  $('query-form').addEventListener('submit', event => {
    event.preventDefault(); const rotation = $('rotation').value;
    runQuery({service:$('service').value.trim(), software_version:$('version').value.trim(), environment:$('environment').value,
      key_rotation_enabled:rotation === 'unknown' ? null : rotation === 'true'});
  });
})();
