const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const context = vm.createContext({});
vm.runInContext(fs.readFileSync('Model.js', 'utf8').replace('.pragma library', ''), context);
const previous = context.emptyStatus();
previous.ok = true;
previous.daemonRunning = true;
previous.packageInstalled = true;
previous.machines = [{name: 'peer', shareable: true}];
previous.tailscale.running = true;
const failed = context.parseStatus(JSON.stringify({ok: false, error: 'SSH failed', lastInstall: {name: 'peer', needAuth: true}}), previous);
assert.equal(failed.daemonRunning, true);
assert.equal(failed.lastInstall.needAuth, true);
assert.equal(failed.machines.length, 1);
assert.equal(failed.tailscale.running, true);
const partial = context.parseStatus('{"ok":true,"copied":true}', previous);
assert.equal(partial.daemonRunning, true);
assert.equal(partial.machines.length, 1);
for (const raw of ['', 'no JSON', 'null', '[]']) {
  const result = context.parseStatus(raw, previous);
  assert.equal(result.ok, false);
  assert.equal(result.daemonRunning, true);
  assert.ok(result.error);
}
assert.equal(context.parseStatus('{"ok":true}').fingerprint, '');
assert.equal(context.shareableMachines([null, {shareable:true}]).length, 1);
console.log('Model regression checks passed');
