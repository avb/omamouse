import QtQuick
import Quickshell
import Quickshell.Io
import "Model.js" as Model

Item {
  id: root

  property var settings: ({})
  property url pluginRootUrl: Qt.resolvedUrl(".")

  property var status: Model.emptyStatus()
  property string lastError: ""
  property bool busy: statusProcess.running || actionProcess.running
  property bool probing: probeProcess.running
  property bool restoring: false
  property string pendingSecret: ""
  property int actionGeneration: 0

  readonly property string ctlPath: {
    var u = pluginRootUrl.toString()
    if (u.indexOf("file://") === 0) u = decodeURIComponent(u.substring(7))
    if (u.charAt(0) !== "/") {
      var home = Quickshell.env("HOME") || ""
      u = home + "/.config/omarchy/plugins/io.github.avb.omamouse/"
    }
    return u.replace(/\/+$/, "") + "/scripts/ctl"
  }
  readonly property int refreshIntervalSec: {
    var n = parseInt(String(settings && settings.refreshIntervalSec != null ? settings.refreshIntervalSec : 15), 10)
    if (!isFinite(n) || n < 5) n = 15
    if (n > 120) n = 120
    return n
  }
  readonly property bool restoreDaemon: !(settings && settings.restoreDaemon === false)

  function applyPayload(raw, isAction) {
    var parsed = Model.parseStatus(raw, status)
    if (parsed.ok === false && parsed.error) lastError = parsed.error
    else if (isAction) lastError = ""
    status = parsed
  }

  function refresh() {
    if (statusProcess.running || actionProcess.running) return
    statusProcess.generation = actionGeneration
    statusProcess.command = ["python3", ctlPath, "status"]
    statusProcess.running = true
  }

  function runVerb(args, secret) {
    if (actionProcess.running) return
    actionGeneration += 1
    lastError = ""
    pendingSecret = secret || ""
    actionProcess.stdinEnabled = pendingSecret !== ""
    actionProcess.command = ["python3", ctlPath].concat(args)
    actionProcess.running = true
  }

  function startDaemon() { runVerb(["start"]) }
  function stopDaemon() { runVerb(["stop"]) }
  function releasePointer() { runVerb(["release"]) }
  function toggleDaemon() {
    if (status.daemonRunning) stopDaemon()
    else startDaemon()
  }
  function installPackages() { runVerb(["install"]) }
  function addPeer(name, position) { runVerb(["add-peer", "--name", name, "--position", position]) }
  function placePeer(name, position, user, password) {
    var args = ["place-peer", "--name", name, "--position", position]
    if (user) args.push("--user", user)
    if (password) args.push("--password-stdin")
    runVerb(args, password || "")
  }
  function removePeer(name) { runVerb(["remove-peer", "--name", name]) }
  function authorize(name, fingerprint) { runVerb(["authorize", "--name", name, "--fingerprint", fingerprint]) }
  function deauthorize(fingerprint) { runVerb(["deauthorize", "--fingerprint", fingerprint]) }
  function setClipboard(on) { runVerb(["clipboard", "--enabled", on ? "on" : "off"]) }
  function copyFingerprint() { runVerb(["copy-fingerprint"]) }
  function installPeer(name, user, password) {
    var args = ["install-peer", "--name", name]
    if (user) args.push("--user", user)
    if (password) args.push("--password-stdin")
    runVerb(args, password || "")
  }
  function retrySsh(name, user, password) {
    var args = ["retry-ssh", "--name", name]
    if (user) args.push("--user", user)
    if (password) args.push("--password-stdin")
    runVerb(args, password || "")
  }
  function repairPeer(name, user, password) {
    var args = ["repair-peer", "--name", name]
    if (user) args.push("--user", user)
    if (password) args.push("--password-stdin")
    runVerb(args, password || "")
  }
  function copyInstructions(name) { runVerb(["copy-instructions", "--name", name]) }
  function probePeers() {
    if (probeProcess.running || actionProcess.running) return
    probeProcess.generation = actionGeneration
    probeProcess.command = ["python3", ctlPath, "probe-peers"]
    probeProcess.running = true
  }
  function restartPeer(name, user, password) {
    var args = ["restart-peer", "--name", name]
    if (user) args.push("--user", user)
    if (password) args.push("--password-stdin")
    runVerb(args, password || "")
  }
  function forgetPeer(name) { runVerb(["forget-peer", "--name", name]) }
  function restore() {
    if (!restoreDaemon || restoring || actionProcess.running) return
    restoring = true
    runVerb(["restore"])
  }

  Process {
    id: statusProcess
    property int generation: 0
    stdout: StdioCollector {
      onStreamFinished: {
        if (!actionProcess.running && statusProcess.generation === root.actionGeneration) root.applyPayload(text, false)
      }
    }
    onExited: {
      if (generation !== root.actionGeneration) Qt.callLater(root.refresh)
    }
  }

  Process {
    id: actionProcess
    stdinEnabled: false
    stdout: StdioCollector {
      onStreamFinished: root.applyPayload(text, true)
    }
    stderr: StdioCollector {
      onStreamFinished: {
        if (text && text.trim() !== "") root.lastError = text.trim().split("\n").slice(-1)[0]
      }
    }
    onStarted: {
      if (root.pendingSecret !== "") {
        write(root.pendingSecret + "\n")
        root.pendingSecret = ""
      }
    }
    onExited: {
      root.pendingSecret = ""
      root.restoring = false
      root.refresh()
    }
  }

  Process {
    id: probeProcess
    property int generation: 0
    stdout: StdioCollector {
      onStreamFinished: {
        if (!actionProcess.running && probeProcess.generation === root.actionGeneration) root.applyPayload(text, false)
      }
    }
  }

  Timer {
    interval: root.refreshIntervalSec * 1000
    running: true
    repeat: true
    onTriggered: root.refresh()
  }

  Timer {
    interval: 30000
    running: true
    repeat: true
    onTriggered: {
      var machines = root.status.machines || []
      var any = false
      for (var i = 0; i < machines.length; i++) {
        if (machines[i].configured && machines[i].online) any = true
      }
      if (any) root.probePeers()
    }
  }

  Component.onCompleted: {
    refresh()
    Qt.callLater(root.restore)
    Qt.callLater(root.probePeers)
  }
}
