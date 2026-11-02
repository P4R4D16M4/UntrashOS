/* Admin settings → UntrashOS (no build step: plain DOM, Nextcloud's OC helpers) */
(function () {
	'use strict';
	const url = p => OC.generateUrl('/apps/untrash/settings/' + p);
	const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
	const when = t => t ? new Date(t * 1000).toLocaleString() : '–';
	const $ = id => document.getElementById(id);
	async function call(p, body) {
		const r = await fetch(url(p), {
			method: body ? 'POST' : 'GET', credentials: 'same-origin',
			headers: { requesttoken: OC.requestToken, 'Content-Type': 'application/json' },
			body: body ? JSON.stringify(body) : undefined,
		});
		const j = await r.json().catch(() => ({}));
		if (!r.ok) throw new Error(j.error || ('HTTP ' + r.status));
		return j;
	}
	function msg(text, ok) {
		const m = $('untrash-msg');
		m.textContent = text || '';
		m.className = 'untrash-msg ' + (ok ? 'untrash-ok' : 'untrash-err');
	}
	function render(s) {
		const b = $('untrash-body');
		if (!s.mesh) {
			b.innerHTML = `<h3>Join a mesh</h3>
				<p class="settings-hint">On the UntrashOS NAS choose <b>UntrashMesh → Connect a Nextcloud</b> and paste the invitation here.
				This server must reach the NAS while it joins.</p>
				<p><textarea id="untrash-inv" rows="4" placeholder="Invitation"></textarea></p>
				<p><label>Name in the mesh <input type="text" id="untrash-name" placeholder="nextcloud" maxlength="32"></label></p>
				<p><button id="untrash-join" class="primary">Join</button></p>`;
			$('untrash-join').onclick = async () => {
				msg('Joining …', true);
				try { render(await call('join', { invitation: $('untrash-inv').value, name: $('untrash-name').value })); msg('Joined.', true); } catch (e) { msg(e.message); }
			};
			return;
		}
		if (s.removed) {
			b.innerHTML = `<p class="untrash-err">An admin removed this Nextcloud from the mesh <b>${esc(s.mesh.name)}</b>. It no longer keeps the address book.
				To join again, leave the mesh here and paste a new invitation.</p><p><button id="untrash-leave">Leave the mesh</button></p>`;
			$('untrash-leave').onclick = async () => {
				try { render(await call('leave', {})); msg('', true); } catch (e) { msg(e.message); }
			};
			return;
		}
		const rows = s.members.map(m => `<tr><td><b>${esc(m.name)}</b>${m.self ? ' (this Nextcloud)' : ''}<div class="untrash-mono">${esc(m.node)}</div></td>
			<td>${m.kind === 'cloud' ? 'Nextcloud' : m.kind === 'app' ? 'App' : 'NAS'}${m.role === 'admin' ? ' · admin' : ''}</td>
			<td class="untrash-mono">${esc((m.endpoints || []).join(', '))}</td><td>${when(m.seen)}</td></tr>`).join('');
		const nas = s.members.filter(m => m.kind !== 'cloud' && m.kind !== 'app').map(m => {
			const f = m.feed || {}, l = f.last || null;
			return `<div class="untrash-feed" data-node="${esc(m.node)}"><h4>${esc(m.name)}</h4>
				<p><input type="text" class="untrash-base" value="${esc(f.base || '')}" placeholder="http://NAS:5002/untrash-cloudlink">
				<label><input type="checkbox" class="untrash-verify"${f.verify === false ? '' : ' checked'}> check the HTTPS certificate</label></p>
				<p><button class="untrash-save">Save</button> <button class="untrash-test"${f.base ? '' : ' disabled'}>Test</button>
				<span class="${l && !l.ok ? 'untrash-err' : 'untrash-ok'}">${l ? (l.ok ? 'last round ' + when(l.t) + ': ' + l.changes + ' changes' : esc(l.error)) : ''}</span></p></div>`;
		}).join('');
		b.innerHTML = `<p>Member of <b>${esc(s.mesh.name)}</b> as <b>${esc(s.name)}</b>. Directory address: <span class="untrash-mono">${esc(s.dir)}</span></p>
			<table><thead><tr><th>Member</th><th>Kind</th><th>Endpoints</th><th>Record from</th></tr></thead><tbody>${rows}</tbody></table>
			<h3>Change feed</h3>
			<p class="settings-hint">For each NAS, the address of its WebDAV port with <span class="untrash-mono">/untrash-cloudlink</span>.
			External storages (WebDAV) whose URL is that NAS and whose folder is <span class="untrash-mono">webdav/&lt;share&gt;</span>
			are then updated path by path; set their <b>Check for changes</b> to <b>Never</b>. The changes arrive every 5 minutes
			with the background jobs, or within seconds while <span class="untrash-mono">occ untrash:feed</span> runs as a service.</p>
			${nas || '<p>No NAS in the mesh.</p>'}
			<p><button id="untrash-leave">Leave the mesh</button></p>`;
		b.querySelectorAll('.untrash-feed').forEach(d => {
			const node = d.dataset.node;
			d.querySelector('.untrash-save').onclick = async () => {
				try { render(await call('nas', { node, base: d.querySelector('.untrash-base').value, verify: d.querySelector('.untrash-verify').checked })); msg('Saved.', true); } catch (e) { msg(e.message); }
			};
			d.querySelector('.untrash-test').onclick = async () => {
				try { const i = await call('test', { node }); msg('Reached ' + i.nas + ' (UntrashOS ' + i.version + '), shares: ' + (i.shares || []).map(x => x.name).join(', '), true); } catch (e) { msg(e.message); }
			};
		});
		$('untrash-leave').onclick = async () => {
			if (!confirm('Leave the mesh? The NAS admin can remove this Nextcloud there too.')) return;
			try { render(await call('leave', {})); msg('Left the mesh.', true); } catch (e) { msg(e.message); }
		};
	}
	document.addEventListener('DOMContentLoaded', () => call('state').then(render).catch(e => msg(e.message)));
})();
