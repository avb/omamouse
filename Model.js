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

function parseStatus(raw, previous) {
  var result = Object.assign(emptyStatus(), previous || {})
  var data
  try {
    data = JSON.parse(String(raw || ""))
    if (!data || typeof data !== "object" || Array.isArray(data)) throw new Error("invalid status")
  } catch (e) {
    result.ok = false
    result.error = "status was not valid JSON"
    return result
  }
  Object.assign(result, data)
  result.error = data.ok === false ? String(data.error || "command failed") : ""
  if (!Array.isArray(result.machines)) result.machines = []
  if (!Array.isArray(result.authorized)) result.authorized = []
  result.tailscale = Object.assign(emptyStatus().tailscale, previous && previous.tailscale || {}, data.tailscale || {})
  return result
}

function shareableMachines(machines) {
  var out = []
  for (var i = 0; i < machines.length; i++) {
    if (machines[i] && machines[i].shareable) out.push(machines[i])
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
