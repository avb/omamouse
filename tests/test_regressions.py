"""Regression coverage without touching a desktop session or remote computer."""
import contextlib
import io
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from deskshare import config, ctl, health, paths, remote, ssh, tailscale

FP = ':'.join(['ab'] * 32)
OTHER_FP = ':'.join(['cd'] * 32)
PEER = {'name': 'peer', 'dnsName': 'peer.example.ts.net', 'ips': ['100.64.0.2'],
        'os': 'linux', 'online': True, 'shareable': True}
TS = {'installed': True, 'running': True, 'selfName': 'local', 'selfDns': 'local.example.ts.net',
      'selfIp': '100.64.0.1', 'peers': [PEER]}


def completed(code=0, stdout='', stderr=''):
    return subprocess.CompletedProcess([], code, stdout, stderr)


class IsolatedTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for attr in ('CONFIG_PATH', 'CERT_PATH', 'PID_PATH', 'LOG_PATH', 'DESIRED_PATH',
                     'CLIPBOARD_FLAG', 'LAST_INSTALL_PATH', 'KNOWN_HOSTS_PATH', 'SSH_USERS_PATH', 'PEER_HEALTH_PATH'):
            self.enterContext(patch.object(paths, attr, self.root / attr))
        self.enterContext(patch.object(paths, 'RUNTIME_DIR', self.root))
        self.enterContext(patch.object(paths, 'STATE_DIR', self.root))
        self.enterContext(patch.object(paths, 'ensure'))


class ConfigTests(IsolatedTest):
    def test_round_trip_preserves_settings_and_control_characters(self):
        original = config.parse('''port = 5000
capture_backend = "layer-shell"
release_bind = []
[authorized_fingerprints]
"aa" = "name"
[[clients]]
hostname = "peer"
position = "left"
activate_on_startup = false
[clients.custom]
value = 1
''')
        original['authorized_fingerprints'][FP] = 'quotes" newline\n tab\t nul\0 del\x7f'
        ctl.write_config(original)
        self.assertEqual(ctl.load_config(), original)
        self.assertEqual(paths.CONFIG_PATH.stat().st_mode & 0o777, 0o600)

    def test_invalid_config_is_not_overwritten(self):
        paths.CONFIG_PATH.write_text('port = "broken"')
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            ctl.main(['authorize', '--name', 'peer', '--fingerprint', FP])
        self.assertFalse(json.loads(output.getvalue())['ok'])
        self.assertEqual(paths.CONFIG_PATH.read_text(), 'port = "broken"')

    def test_invalid_fingerprints_do_not_write(self):
        for fp in ['a:' * 32, 'xx:' * 31 + 'xx', FP + '\nother = true', 'aa:bb']:
            self.assertFalse(ctl.authorize('peer', fp)['ok'])
        self.assertFalse(paths.CONFIG_PATH.exists())

    def test_hook_preserves_empty_arguments_and_shell_metacharacters(self):
        hook = ctl.clipboard_hook('peer; echo bad', '', 'Mac OS')
        self.assertEqual(shlex.split(hook)[1:], ['peer; echo bad', '', 'Mac OS'])

    def test_move_preserves_peer_port_and_options(self):
        cfg = config.parse('')
        cfg['port'] = 6000
        cfg['clients'] = [{'hostname': PEER['dnsName'], 'position': 'left', 'port': 5000, 'custom': True}]
        ctl.write_config(cfg)
        with patch.object(tailscale, 'find_peer', return_value=PEER), patch.object(ctl, 'restart_if_running'), patch.object(ctl, 'build_status', return_value={'ok': True}):
            ctl.add_peer(PEER['dnsName'], 'right')
        clients = ctl.load_config()['clients']
        self.assertEqual(len(clients), 1)
        self.assertEqual(clients[0]['port'], 5000)
        self.assertTrue(clients[0]['custom'])


class SshTests(IsolatedTest):
    def test_known_key_is_not_replaced_or_scanned(self):
        paths.KNOWN_HOSTS_PATH.write_text('existing key\n')
        with patch.object(ssh.subprocess, 'run', return_value=completed(255, stderr='REMOTE HOST IDENTIFICATION HAS CHANGED')) as run:
            result = ssh.Session('peer', PEER).run(['true'])
        self.assertEqual(result.returncode, 255)
        self.assertEqual(run.call_count, 1)
        self.assertEqual(paths.KNOWN_HOSTS_PATH.read_text(), 'existing key\n')
        self.assertEqual(run.call_args.args[0][0], 'ssh')

    def test_timeout_does_not_replay_mutation(self):
        with patch.object(ssh.subprocess, 'run', side_effect=subprocess.TimeoutExpired('ssh', 1)) as run:
            result = ssh.Session('peer', PEER).run(['install'])
        self.assertEqual(result.returncode, 124)
        self.assertEqual(run.call_count, 1)

    def test_connection_failure_uses_fallback(self):
        with patch.object(ssh.subprocess, 'run', side_effect=[completed(255, stderr='Connection refused'), completed()]) as run:
            self.assertEqual(ssh.Session('peer', PEER).run(['true']).returncode, 0)
        self.assertEqual(run.call_count, 2)

    def test_remote_exit_127_does_not_replay(self):
        with patch.object(ssh.subprocess, 'run', return_value=completed(127)) as run:
            self.assertEqual(ssh.Session('peer', PEER).run(['install']).returncode, 127)
        self.assertEqual(run.call_count, 1)

    def test_password_files_are_private_independent_and_removed(self):
        env1, file1 = ssh._askpass_env('first')
        env2, file2 = ssh._askpass_env('second')
        self.assertNotEqual(file1, file2)
        self.assertEqual(file1.stat().st_mode & 0o777, 0o600)
        self.assertEqual(file1.read_text(), 'first')
        ssh._clear_passfile(file1)
        self.assertEqual(file2.read_text(), 'second')
        ssh._clear_passfile(file2)
        self.assertFalse(file1.exists() or file2.exists())

    def test_command_terminates_options_before_destination(self):
        cmd = ssh._cmd('-badhost', ['bash', '-c', 'echo "a b"'], 10)
        self.assertEqual(cmd[-3:-1], ['--', '-badhost'])
        self.assertEqual(shlex.split(cmd[-1]), ['bash', '-c', 'echo "a b"'])


class RemoteTests(IsolatedTest):
    def test_pair_scripts_preserve_other_pairs_and_ports(self):
        cfg = config.parse('')
        cfg['port'] = 5500
        cfg['capture_backend'] = 'layer-shell'
        cfg['authorized_fingerprints'][OTHER_FP] = 'other'
        cfg['clients'] = [{'hostname': 'other', 'position': 'top', 'activate_on_startup': False}]
        bindir = self.root / 'bin'
        bindir.mkdir()
        for command in ('killall', 'pkill', 'sleep', 'open', 'pgrep', 'lan-mouse'):
            script = bindir / command
            script.write_text('#!/bin/sh\nexit 0\n')
            script.chmod(0o700)
        openssl = bindir / 'openssl'
        openssl.write_text('#!/bin/sh\nprintf "%s\\n" "notice=value" "sha256 Fingerprint=' + FP + '"\n')
        openssl.chmod(0o700)
        cfgdir = self.root / 'config' / 'lan-mouse'
        cfgdir.mkdir(parents=True)
        (cfgdir / 'lan-mouse.pem').touch()
        env = {**os.environ, 'HOME': str(self.root), 'XDG_CONFIG_HOME': str(cfgdir.parent), 'PATH': str(bindir) + ':/usr/bin:/bin'}
        for os_name in ('linux', 'macOS'):
            with self.subTest(os=os_name):
                session = Mock(user="")
                session.run_script.side_effect = [completed(stdout=config.dumps(cfg)), completed(stdout='notice=value\nsha256 Fingerprint=' + FP)]
                with patch.object(remote, 'Session', return_value=session):
                    result = remote.pair_peer('peer', {**PEER, 'os': os_name}, local_fp=FP, local_name='local', local_ip='100.64.0.1', local_port=6500)
                self.assertTrue(result['paired'])
                self.assertEqual(result['remotePort'], 5500)
                script = session.run_script.call_args.args[0]
                proc = subprocess.run(['bash', '-c', script], env=env, capture_output=True, text=True, timeout=5)
                self.assertEqual(proc.returncode, 0, proc.stderr)
                saved = config.parse((cfgdir / 'config.toml').read_text())
                self.assertEqual(saved['authorized_fingerprints'][OTHER_FP], 'other')
                self.assertEqual(saved['clients'][0], cfg['clients'][0])
                self.assertEqual(saved['clients'][1]['port'], 6500)
                self.assertEqual(saved['port'], 5500)

    def test_pairing_does_not_claim_success_from_old_certificate_on_failure(self):
        session = Mock(user="")
        session.run_script.side_effect = [completed(), completed(1, 'sha256 Fingerprint=' + FP)]
        with patch.object(remote, 'Session', return_value=session):
            result = remote.pair_peer('peer', PEER, local_fp=FP, local_name='local', local_ip='100.64.0.1')
        self.assertFalse(result['paired'])
        self.assertFalse(result['remoteStarted'])
        self.assertTrue(result['error'])

    def test_windows_pairing_never_runs_unix_commands(self):
        with patch.object(remote, 'Session') as session:
            result = remote.pair_peer('peer', {**PEER, 'os': 'windows'}, local_fp=FP)
        self.assertFalse(result['paired'])
        session.assert_not_called()

    def test_linux_existing_install_needs_no_pacman(self):
        session = Mock(user='alice', via='ssh', target='peer')
        session.run_script.return_value = completed(stdout='ok\nalice\n/usr/bin/lan-mouse\nbin_present\n')
        with patch.object(remote, 'Session', return_value=session):
            result = remote.install_linux('peer', PEER)
        self.assertTrue(result['installed'])
        self.assertEqual(session.run_script.call_count, 1)

    def test_clipboard_failure_is_reported(self):
        with patch.object(remote.subprocess, 'run', side_effect=FileNotFoundError('wl-copy')):
            self.assertFalse(remote.copy_text('text')['ok'])
        with patch.object(remote.subprocess, 'run', return_value=completed(1, b'', b'no clipboard')):
            self.assertFalse(remote.copy_text('text')['ok'])

    def test_restart_forwards_credentials(self):
        with patch.object(tailscale, 'find_peer', return_value=PEER), patch.object(health, 'Session') as session:
            session.return_value.run_script.return_value = completed(stdout='restarted')
            self.assertTrue(health.restart_remote('peer', user='alice', password='secret')['ok'])
        session.assert_called_once_with('peer', PEER, user='alice', password='secret')

    def test_forget_preserves_unrelated_remote_pair(self):
        cfg = config.parse('')
        cfg['authorized_fingerprints'] = {FP: 'local', OTHER_FP: 'other'}
        cfg['clients'] = [{'hostname': 'local'}, {'hostname': 'other'}]
        session = Mock(user="")
        session.run_script.return_value = completed()
        with patch.object(tailscale, 'find_peer', return_value=PEER), patch.object(tailscale, 'status', return_value=TS), patch.object(ctl, 'fingerprint', return_value=FP), patch.object(ctl, 'restart_if_running'), patch.object(ctl, 'build_status', return_value={'ok': True}), patch.object(ssh, 'Session', return_value=session), patch.object(remote, 'read_config', return_value=cfg), patch.object(remote, 'write_config_script', return_value='write') as write, patch.object(health, 'restart_remote', return_value={'ok': True}):
            self.assertTrue(ctl.forget_peer('peer')['ok'])
        saved = write.call_args.args[0]
        self.assertEqual(saved['authorized_fingerprints'], {OTHER_FP: 'other'})
        self.assertEqual(saved['clients'], [{'hostname': 'other'}])


class DaemonTests(IsolatedTest):
    def test_dead_start_reports_error_even_with_existing_certificate(self):
        proc = Mock(pid=999999)
        proc.poll.return_value = 1
        with patch.object(ctl, 'package_version', return_value='test'), patch.object(tailscale, 'status', return_value=TS), patch.object(ctl, 'pid_alive', return_value=None), patch.object(ctl, '_graphical_env', return_value={}), patch.object(ctl.subprocess, 'Popen', return_value=proc), patch.object(ctl.time, 'sleep'), patch.object(ctl, 'fingerprint', return_value=FP):
            result = ctl.start_daemon()
        self.assertFalse(result['ok'])
        self.assertFalse(paths.PID_PATH.exists())

    def test_invalid_pid_never_signals_process_group(self):
        for pid in ('0', '-1', '1'):
            paths.PID_PATH.write_text(pid)
            with patch.object(ctl.os, 'kill') as kill:
                self.assertIsNone(ctl.pid_alive())
            kill.assert_not_called()


class ActivationTests(IsolatedTest):
    def setUp(self):
        super().setUp()
        self.enterContext(patch.object(ctl, 'package_version', return_value='test'))
        self.enterContext(patch.object(ctl, 'pid_alive', return_value=123))
        self.enterContext(patch.object(ctl, 'fingerprint', return_value=FP))
        self.enterContext(patch.object(tailscale, 'status', return_value=TS))
        self.enterContext(patch.object(tailscale, 'find_peer', return_value=PEER))
        self.enterContext(patch.object(ctl, 'restart_if_running'))

    def test_pair_uses_free_local_edge_and_both_listen_ports(self):
        cfg = config.parse('')
        cfg['port'] = 6000
        cfg['clients'] = [{'hostname': 'other', 'position': 'right'}]
        ctl.write_config(cfg)
        with patch.object(remote, 'pair_peer', return_value={'paired': True, 'remoteFingerprint': FP, 'remotePort': 5000}) as pair:
            result = ctl._activate_installed('peer', '', '', {'installed': True, 'name': 'peer'})
        self.assertTrue(result['paired'])
        self.assertEqual(pair.call_args.kwargs['local_port'], 6000)
        self.assertEqual(pair.call_args.kwargs['local_position'], 'left')
        self.assertEqual(ctl.load_config()['clients'][1]['port'], 5000)
        self.assertEqual(ctl.load_config()['clients'][0], cfg['clients'][0])

    def test_failed_pair_does_not_create_an_edge(self):
        with patch.object(remote, 'pair_peer', return_value={'paired': False, 'error': 'failure'}):
            result = ctl._activate_installed('peer', '', '', {'installed': True, 'name': 'peer'})
        self.assertFalse(result['paired'])
        self.assertEqual(ctl.load_config()['clients'], [])
        self.assertEqual(remote.load_last()['error'], 'failure')

    def test_full_layout_does_not_mutate_remote(self):
        cfg = config.parse('')
        cfg['clients'] = [{'hostname': edge, 'position': edge} for edge in ['left', 'right', 'top', 'bottom']]
        ctl.write_config(cfg)
        with patch.object(remote, 'pair_peer') as pair:
            result = ctl._activate_installed('peer', '', '', {'installed': True})
        self.assertFalse(result['paired'])
        pair.assert_not_called()

    def test_auth_failure_is_exposed_to_credential_form(self):
        session = Mock(user='')
        session.run_script.return_value = completed(255, stderr='Permission denied')
        with patch.object(remote, 'Session', return_value=session):
            result = remote.pair_peer('peer', PEER, local_fp=FP, local_name='local', local_ip='100.64.0.1')
        self.assertTrue(result['needAuth'])
        self.assertFalse(result['ssh'])

    def test_health_checks_exact_authorization_on_configured_port(self):
        cfg = config.parse('')
        # A fingerprint in a comment/name alone must not authorize incoming input.
        cfg['authorized_fingerprints'][OTHER_FP] = FP
        session = Mock(user='')
        session.run_script.return_value = completed(stdout='RUNNING=yes\nUDP=yes\nHAS_CONFIG=yes\nCONFIG_HEAD\n' + config.dumps(cfg) + 'CONFIG_TAIL\n')
        with patch.object(health, 'Session', return_value=session):
            result = health.probe_peer('peer', FP, port=6000)
        self.assertFalse(result['remotePaired'])
        self.assertIn('6000', session.run_script.call_args.args[0])


if __name__ == '__main__':
    unittest.main()
