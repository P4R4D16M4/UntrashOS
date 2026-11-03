/* Admin settings → UntrashOS (no build step: plain DOM, Nextcloud's OC helpers) */
(function () {
	'use strict';
	const url = p => OC.generateUrl('/apps/untrash/settings/' + p);
	const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
	const when = t => t ? new Date(t * 1000).toLocaleString() : '–';
	const $ = id => document.getElementById(id);
	const T = (s, v) => t('untrash', s, v, undefined, { escape: false, sanitize: false });   // Nextcloud's l10n; esc() is the one escaping
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
			b.innerHTML = `<h3>${esc(T('Join a mesh'))}</h3>
				<p class="settings-hint">${esc(T('On the UntrashOS NAS choose UntrashMesh → Connect a Nextcloud and paste the invitation here. This server must reach the NAS while it joins.'))}</p>
				<p><textarea id="untrash-inv" rows="4" placeholder="${esc(T('Invitation'))}"></textarea></p>
				<p><label>${esc(T('Name in the mesh'))} <input type="text" id="untrash-name" placeholder="nextcloud" maxlength="32"></label></p>
				<p><button id="untrash-join" class="primary">${esc(T('Join'))}</button></p>`;
			$('untrash-join').onclick = async () => {
				msg(T('Joining …'), true);
				try { render(await call('join', { invitation: $('untrash-inv').value, name: $('untrash-name').value })); msg(T('Joined.'), true); } catch (e) { msg(e.message); }
			};
			return;
		}
		if (s.removed) {
			b.innerHTML = `<p class="untrash-err">${esc(T('An admin removed this Nextcloud from the mesh {mesh}. It no longer keeps the address book. To join again, leave the mesh here and paste a new invitation.', { mesh: s.mesh.name }))}</p>
				<p><button id="untrash-leave">${esc(T('Leave the mesh'))}</button></p>`;
			$('untrash-leave').onclick = async () => {
				try { render(await call('leave', {})); msg('', true); } catch (e) { msg(e.message); }
			};
			return;
		}
		const rows = s.members.map(m => `<tr><td><b>${esc(m.name)}</b>${m.self ? ' ' + esc(T('(this Nextcloud)')) : ''}<div class="untrash-mono">${esc(m.node)}</div></td>
			<td>${m.kind === 'cloud' ? 'Nextcloud' : m.kind === 'app' ? 'App' : 'NAS'}${m.role === 'admin' ? ' · ' + esc(T('admin')) : ''}</td>
			<td class="untrash-mono">${esc((m.endpoints || []).join(', '))}</td><td>${when(m.seen)}</td></tr>`).join('');
		const now = Date.now() / 1000;
		const meshBase = m => m.address ? 'http://[' + m.address + ']:5002/untrash-cloudlink' : '';
		const nas = s.members.filter(m => m.kind !== 'cloud' && m.kind !== 'app').map(m => {
			const f = m.feed || {}, l = f.last || null;
			const up = m.tunnel && now - m.tunnel < 180;
			const tun = !s.tunnel ? '' : `<p>${up ? `<span class="untrash-ok">${esc(T('Tunnel connected'))}</span>`
				+ (f.base !== meshBase(m) ? ` <button class="untrash-meshaddr">${esc(T('Use the mesh address'))}</button>` : '')
				: `<span class="untrash-err">${esc(T('Tunnel: no connection from this NAS yet'))}</span>`}</p>`;
			return `<div class="untrash-feed" data-node="${esc(m.node)}"><h4>${esc(m.name)}</h4>
				<p><input type="text" class="untrash-base" value="${esc(f.base || '')}" placeholder="http://NAS:5002/untrash-cloudlink">
				${m.pinned && /^https:/i.test(f.base || '') ? `<input type="checkbox" class="untrash-verify" checked hidden><span class="untrash-ok">${esc(T('HTTPS key pinned through the mesh'))}</span>`
					: `<label><input type="checkbox" class="untrash-verify"${f.verify === false ? '' : ' checked'}> ${esc(T('check the HTTPS certificate'))}</label>`}</p>
				<p><button class="untrash-save">${esc(T('Save'))}</button> <button class="untrash-test"${f.base ? '' : ' disabled'}>${esc(T('Test'))}</button>
				<span class="${l && !l.ok ? 'untrash-err' : 'untrash-ok'}">${l ? esc(l.ok ? T('last round {time}: {changes} changes', { time: when(l.t), changes: l.changes }) : l.error) : ''}</span></p>${tun}</div>`;
		}).join('');
		b.innerHTML = `<p>${esc(T('Member of {mesh} as {name}.', { mesh: s.mesh.name, name: s.name }))} ${esc(T('Directory address:'))} <span class="untrash-mono">${esc(s.dir)}</span></p>
			<table><thead><tr><th>${esc(T('Member'))}</th><th>${esc(T('Kind'))}</th><th>${esc(T('Endpoints'))}</th><th>${esc(T('Record from'))}</th></tr></thead><tbody>${rows}</tbody></table>
			<p>${s.tunnel ? esc(T('Tunnel: this server is a WireGuard peer of the mesh at {endpoints}. The NAS connect to it, so it reaches them at their mesh address.', { endpoints: s.tunnel.endpoints.join(', ') }))
				: esc(T('No tunnel: this server reaches a NAS only at the address entered below. With the helper untrash-cloud-wg on this server it reaches a NAS behind a router without a port forward (see the app README).'))}</p>
			<h3>${esc(T('Change feed'))}</h3>
			<p class="settings-hint">${esc(T('For each NAS, the address of its WebDAV port with /untrash-cloudlink. External storages (WebDAV) whose URL is that NAS and whose folder is webdav/<share> are then updated path by path; set their "Check for changes" to "Never". The changes arrive every 5 minutes with the background jobs, or within seconds while "occ untrash:feed" runs as a service.'))}</p>
			${nas || '<p>' + esc(T('No NAS in the mesh.')) + '</p>'}
			<p><button id="untrash-leave">${esc(T('Leave the mesh'))}</button></p>`;
		b.querySelectorAll('.untrash-feed').forEach(d => {
			const node = d.dataset.node;
			d.querySelector('.untrash-save').onclick = async () => {
				try { render(await call('nas', { node, base: d.querySelector('.untrash-base').value, verify: d.querySelector('.untrash-verify').checked })); msg(T('Saved.'), true); } catch (e) { msg(e.message); }
			};
			const ma = d.querySelector('.untrash-meshaddr');
			if (ma) ma.onclick = async () => {
				const m = s.members.find(x => x.node === node);
				try { render(await call('nas', { node, base: meshBase(m), verify: true })); msg(T('Saved.'), true); } catch (e) { msg(e.message); }
			};
			d.querySelector('.untrash-test').onclick = async () => {
				try { const i = await call('test', { node }); msg(T('Reached {nas} (UntrashOS {version}), shares: {shares}', { nas: i.nas, version: i.version, shares: (i.shares || []).map(x => x.name).join(', ') }), true); } catch (e) { msg(e.message); }
			};
		});
		$('untrash-leave').onclick = async () => {
			if (!confirm(T('Leave the mesh? The NAS admin can remove this Nextcloud there too.'))) return;
			try { render(await call('leave', {})); msg(T('Left the mesh.'), true); } catch (e) { msg(e.message); }
		};
	}
	document.addEventListener('DOMContentLoaded', () => call('state').then(render).catch(e => msg(e.message)));
})();
