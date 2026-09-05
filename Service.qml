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
  property bool restoring: false

  readonly property string ctlPath: {
    var u = pluginRootUrl.toString()
    if (u.indexOf("file://") === 0) u = u.substring(7)
    if (u.charAt(0) !== "/") {
      var home = Quickshell.env("HOME") || ""
      u = home + "/.config/omarchy/plugins/io.github.dicebagstudios.lan-mouse/"
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

  function applyPayload(raw) {
    var parsed = Model.parseStatus(raw)
    if (parsed.ok === false && parsed.error) lastError = parsed.error
    else lastError = ""
    status = parsed
  }

  function refresh() {
    if (statusProcess.running) return
    statusProcess.command = ["python3", ctlPath, "status"]
    statusProcess.running = true
  }

  function runVerb(args) {
    if (actionProcess.running) return
    lastError = ""
    actionProcess.command = ["python3", ctlPath].concat(args)
    actionProcess.running = true
  }

  function startDaemon() { runVerb(["start"]) }
  function stopDaemon() { runVerb(["stop"]) }
  function toggleDaemon() {
    if (status.daemonRunning) stopDaemon()
    else startDaemon()
  }
  function installPackages() { runVerb(["install"]) }
  function addPeer(name, position) { runVerb(["add-peer", "--name", name, "--position", position]) }
  function removePeer(name) { runVerb(["remove-peer", "--name", name]) }
  function authorize(name, fingerprint) { runVerb(["authorize", "--name", name, "--fingerprint", fingerprint]) }
  function deauthorize(fingerprint) { runVerb(["deauthorize", "--fingerprint", fingerprint]) }
  function setClipboard(on) { runVerb(["clipboard", "--enabled", on ? "on" : "off"]) }
  function copyFingerprint() { runVerb(["copy-fingerprint"]) }
  function restore() {
    if (!restoreDaemon || restoring) return
    restoring = true
    runVerb(["restore"])
  }

  Process {
    id: statusProcess
    stdout: StdioCollector {
      onStreamFinished: root.applyPayload(text)
    }
    onExited: root.refreshingDone()
  }

  Process {
    id: actionProcess
    stdout: StdioCollector {
      onStreamFinished: root.applyPayload(text)
    }
    stderr: StdioCollector {
      onStreamFinished: {
        if (text && text.trim() !== "") root.lastError = text.trim().split("\n").slice(-1)[0]
      }
    }
    onExited: {
      root.restoring = false
      root.refresh()
    }
  }

  function refreshingDone() {}

  Timer {
    interval: root.refreshIntervalSec * 1000
    running: true
    repeat: true
    onTriggered: root.refresh()
  }

  Component.onCompleted: {
    refresh()
    Qt.callLater(root.restore)
  }
}
