.pragma library

function emptyStatus() {
  return {
    ok: false,
    packageInstalled: false,
    packageVersion: "",
    emulateReady: false,
    emulateError: "",
    daemonRunning: false,
    daemonPid: 0,
    clipboardRecvRunning: false,
    desiredOn: false,
    clipboardEnabled: true,
    fingerprint: "",
    port: 4242,
    osUser: "",
    tailscale: { installed: false, running: false, selfName: "", selfDns: "", selfIp: "" },
    machines: [],
    authorized: [],
    lastInstall: {},
    emulationBackend: "",
    captureBackend: "",
    emulationDummy: false,
    captureStuck: false,
    lastConnectError: "",
    error: ""
  }
}

function parseStatus(raw) {
  var text = String(raw || "").trim()
  if (text === "") return emptyStatus()
  try {
    var data = JSON.parse(text)
  } catch (e) {
    var failed = emptyStatus()
    failed.error = "status was not JSON"
    return failed
  }
  if (typeof data !== "object" || data === null) return emptyStatus()
  if (data.ok === false) {
    var err = emptyStatus()
    err.error = String(data.error || "command failed")
    err.packageInstalled = data.packageInstalled === true
    err.tailscale = data.tailscale || err.tailscale
    return err
  }
  if (!Array.isArray(data.machines)) data.machines = []
  if (!Array.isArray(data.authorized)) data.authorized = []
  if (!data.tailscale) data.tailscale = emptyStatus().tailscale
  return data
}

function shareableMachines(machines) {
  var out = []
  for (var i = 0; i < machines.length; i++) {
    if (machines[i].shareable) out.push(machines[i])
  }
  return out
}

function osLabel(os) {
  var n = String(os || "").toLowerCase()
  if (n.indexOf("mac") !== -1 || n === "darwin") return "macOS"
  if (n === "linux") return "Linux"
  if (n === "windows") return "Windows"
  return os || "unknown"
}

function shortFingerprint(fp) {
  var s = String(fp || "")
  if (s.length < 11) return s
  return s.slice(0, 8) + "…" + s.slice(-5)
}

function oppositeEdge(position) {
  var p = String(position || "")
  if (p === "left") return "right"
  if (p === "right") return "left"
  if (p === "top") return "bottom"
  if (p === "bottom") return "top"
  return "left"
}

function machineOnEdge(machines, edge) {
  var list = machines || []
  for (var i = 0; i < list.length; i++) {
    if (list[i].configured && list[i].position === edge) return list[i]
  }
  return null
}
