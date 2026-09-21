import QtQuick
import QtQuick.Controls
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui
import "Model.js" as Model

Panel {
  id: root
  moduleName: "io.github.avb.omamouse"
  ipcTarget: "io.github.avb.omamouse"
  manageIpc: false

  property string focusSection: "header"
  property int machineIndex: 0
  property int authIndex: 0
  property bool cursorActive: false
  property bool fingerprintEdit: false
  property bool sshEdit: false
  property string sshUserText: ""
  property string sshPassText: ""
  property var sshUserDrafts: ({})
  property string pendingAuthName: ""
  property int phraseIndex: 0
  property var positionChoices: ["right", "left", "top", "bottom"]

  readonly property var activePhrases: [
    "Herding cursors",
    "Borrowing keystrokes",
    "Sliding off the edge",
    "Sharing the desk",
    "Walking the tailnet",
    "Passing the pointer"
  ]
  readonly property string heroPhraseText: activePhrases[phraseIndex % activePhrases.length]
  readonly property color foreground: bar ? bar.foreground : Color.foreground
  readonly property color dim: Qt.darker(foreground, 1.55)
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family
  readonly property var machines: Model.shareableMachines(service.status.machines || [])
  readonly property var authorized: service.status.authorized || []
  readonly property bool headerHasCursor: cursorActive && focusSection === "header"
  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  readonly property color barIconColor: service.status.daemonRunning ? barForeground : Qt.darker(barForeground, 1.55)
  readonly property string statusLine: {
    if (!service.status.packageInstalled) return "lan-mouse is not installed"
    if (!service.status.tailscale.installed) return "Tailscale is not installed"
    if (!service.status.tailscale.running) return "Tailscale is disconnected"
    if (service.status.emulationDummy) return "emulation is dummy; incoming pointer will not move"
    if (service.status.captureStuck) return "pointer captured but the peer did not connect"
    if (service.status.daemonRunning) return heroPhraseText
    if (service.lastError) return service.lastError
    return "OmaMouse is off"
  }

  Service {
    id: service
    settings: root.settings
  }

  function selectedMachine() {
    if (machines.length === 0) return null
    return machines[Math.max(0, Math.min(machineIndex, machines.length - 1))]
  }

  function selectedAuth() {
    if (authorized.length === 0) return null
    return authorized[Math.max(0, Math.min(authIndex, authorized.length - 1))]
  }

  function ensureCursor() {
    if (focusSection === "machines" && machines.length === 0) focusSection = "header"
    if (focusSection === "auth" && authorized.length === 0) focusSection = machines.length ? "machines" : "header"
    if (machineIndex >= machines.length) machineIndex = Math.max(0, machines.length - 1)
    if (authIndex >= authorized.length) authIndex = Math.max(0, authorized.length - 1)
  }

  function moveCursor(dx, dy) {
    cursorActive = true
    ensureCursor()
    if (dy === 0) return
    if (focusSection === "header") {
      if (dy > 0 && machines.length > 0) {
        focusSection = "machines"
        machineIndex = 0
      } else if (dy > 0 && authorized.length > 0) {
        focusSection = "auth"
        authIndex = 0
      }
      return
    }
    if (focusSection === "machines") {
      if (dy < 0 && machineIndex === 0) {
        focusSection = "header"
        return
      }
      if (dy > 0 && machineIndex === machines.length - 1 && authorized.length > 0) {
        focusSection = "auth"
        authIndex = 0
        return
      }
      machineIndex = Math.max(0, Math.min(machines.length - 1, machineIndex + dy))
      return
    }
    if (focusSection === "auth") {
      if (dy < 0 && authIndex === 0) {
        focusSection = machines.length ? "machines" : "header"
        if (focusSection === "machines") machineIndex = Math.max(0, machines.length - 1)
        return
      }
      authIndex = Math.max(0, Math.min(authorized.length - 1, authIndex + dy))
    }
  }

  function activateCursor() {
    ensureCursor()
    if (focusSection === "header") service.toggleDaemon()
    else if (focusSection === "machines") cycleOrAdd(selectedMachine())
    else if (focusSection === "auth") forgetAuth(selectedAuth())
  }

  function machineOnEdge(edge) {
    return Model.machineOnEdge(machines, edge)
  }

  function indexOfMachine(name) {
    for (var i = 0; i < machines.length; i++) {
      if (machines[i].name === name) return i
    }
    return -1
  }

  function placeNamed(name, edge) {
    if (!name || !edge) return
    service.placePeer(name, edge, (sshUserText || "").trim(), sshPassText || "")
    sshPassText = ""
  }

  function cycleOrAdd(machine) {
    if (!machine) return
    if (!machine.configured) {
      placeNamed(machine.name, "right")
      return
    }
    var idx = positionChoices.indexOf(machine.position)
    var next = positionChoices[(idx + 1) % positionChoices.length]
    placeNamed(machine.name, next)
  }

  function forgetAuth(row) {
    if (!row) return
    service.deauthorize(row.fingerprint)
  }

  function loadSshForm() {
    var m = selectedMachine()
    if (!m) {
      sshUserText = ""
      sshPassText = ""
      return
    }
    if (sshUserDrafts[m.name] !== undefined && String(sshUserDrafts[m.name]) !== "")
      sshUserText = sshUserDrafts[m.name]
    else
      sshUserText = m.sshUser || ""
    sshPassText = ""
  }

  function rememberSshUser() {
    var m = selectedMachine()
    if (!m) return
    var d = Object.assign({}, sshUserDrafts)
    d[m.name] = sshUserText
    sshUserDrafts = d
  }

  function lastFor(name) {
    var last = service.status.lastInstall || {}
    if (last.name === name) return last
    return {}
  }

  function sshFailedFor(name) {
    var last = lastFor(name)
    return last.ssh === false && !last.installed
  }

  function installedFor(name) {
    return lastFor(name).installed === true
  }

  function retrySelectedSsh() {
    var m = selectedMachine()
    if (!m) return
    service.retrySsh(m.name, (sshUserText || "").trim(), sshPassText || "")
    sshPassText = ""
  }

  function repairSelected() {
    var m = selectedMachine()
    if (!m) return
    service.repairPeer(m.name, (sshUserText || "").trim(), sshPassText || "")
    sshPassText = ""
  }

  function installSelected() {
    var m = selectedMachine()
    if (!m) return
    service.installPeer(m.name, (sshUserText || "").trim(), sshPassText || "")
    sshPassText = ""
  }

  function submitIncoming() {
    var name = (authNameField.text || "").trim()
    var fp = (authFpField.text || "").trim()
    if (name === "" || fp === "") return
    service.authorize(name, fp)
    authNameField.text = ""
    authFpField.text = ""
    fingerprintEdit = false
  }

  function open() {
    service.refresh()
    service.probePeers()
    loadSshForm()
    root.controller.show()
    Qt.callLater(function() { if (keyCatcher) keyCatcher.forceActiveFocus() })
  }
  function close() {
    fingerprintEdit = false
    sshEdit = false
    sshPassText = ""
    root.controller.hide()
  }

  onMachineIndexChanged: loadSshForm()
  function toggle() {
    if (root.opened) root.close()
    else root.open()
  }
  function switchPanel(direction) {
    if (root.bar && typeof root.bar.switchPanelFrom === "function")
      return root.bar.switchPanelFrom(root, direction)
    return false
  }

  Timer {
    interval: 2800
    running: root.opened && service.status.daemonRunning
    repeat: true
    onTriggered: root.phraseIndex = (root.phraseIndex + 1) % root.activePhrases.length
  }

  IpcHandler {
    target: root.ipcTarget
    function open(): void { root.open() }
    function close(): void { root.close() }
    function show(): void { root.open() }
    function hide(): void { root.close() }
    function toggle(): void { root.toggle() }
    function start(): string { service.startDaemon(); return "ok" }
    function stop(): string { service.stopDaemon(); return "ok" }
    function refresh(): string { service.refresh(); return "ok" }
    function status(): string { return root.statusLine }
  }

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: "󰍽"
    active: service.status.daemonRunning
    tooltipText: root.statusLine
    onPressed: function(buttonCode) {
      if (buttonCode === Qt.RightButton) service.toggleDaemon()
      else if (buttonCode === Qt.MiddleButton) service.refresh()
      else root.toggle()
    }
  }

  KeyboardPanel {
    id: panel
    anchorItem: button
    owner: root
    bar: root.bar
    open: root.opened
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(460))
    contentHeight: panel.fittedContentHeight(column.implicitHeight, Style.space(640))

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      blocked: root.fingerprintEdit || root.sshEdit
      onMoveRequested: function(dx, dy) {
        if (!root.cursorActive) { root.cursorActive = true; return }
        root.moveCursor(dx, dy)
      }
      onActivateRequested: if (root.cursorActive) root.activateCursor()
      onCloseRequested: root.close()
      onTabRequested: function(direction) { root.switchPanel(direction) }
      onTextKey: function(t) {
        if (t === "s" || t === "S") service.toggleDaemon()
        else if (t === "c" || t === "C") service.copyFingerprint()
        else if (t === "b" || t === "B") service.setClipboard(!service.status.clipboardEnabled)
        else if (t === "i" || t === "I") {
          var sel = root.selectedMachine()
          if (sel) root.installSelected()
          else service.installPackages()
        }
        else if (t === "n" || t === "N") {
          if (root.selectedMachine()) root.installSelected()
        }
        else if (t === "t" || t === "T") {
          var retryPeer = root.selectedMachine()
          if (retryPeer && (root.sshFailedFor(retryPeer.name) || (root.installedFor(retryPeer.name) && !retryPeer.authorized)))
            root.retrySelectedSsh()
        }
        else if (t === "a" || t === "A") root.cycleOrAdd(root.selectedMachine())
        else if (t === "u" || t === "U") service.releasePointer()
        else if (t === "r" || t === "R") service.refresh()
        else if (t === "x" || t === "X") {
          var m = root.selectedMachine()
          if (m && m.configured) service.removePeer(m.name)
        }
      }

      Flickable {
        id: panelFlick
        anchors.fill: parent
        contentWidth: width
        contentHeight: column.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        flickableDirection: Flickable.VerticalFlick
        interactive: contentHeight > height

        Column {
          id: column
          width: panelFlick.width
          spacing: Style.space(12)

          Item {
            id: header
            width: parent.width
            implicitHeight: hero.implicitHeight
            readonly property bool ringVisible: root.headerHasCursor
            function focusHero() { root.focusSection = "header"; root.cursorActive = true }

            PanelHero {
              id: hero
              width: parent.width
              title: service.status.tailscale.selfName || "OmaMouse"
              meta: root.statusLine
              foreground: root.foreground
              fontFamily: root.fontFamily
              iconOpacity: service.status.daemonRunning ? 1.0 : 0.5
              iconComponent: Component {
                Text {
                  text: "󰍽"
                  color: root.foreground
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.display
                }
              }
              trailingControl: Component {
                ToggleSwitch {
                  checked: service.status.daemonRunning
                  enabled: service.status.packageInstalled && service.status.tailscale.running && !service.busy
                  onToggled: service.toggleDaemon()
                }
              }
            }
          }

          Column {
            width: parent.width
            spacing: Style.space(4)
            visible: !service.status.packageInstalled || !service.status.tailscale.running

            Text {
              width: parent.width
              wrapMode: Text.WordWrap
              text: !service.status.packageInstalled
                ? "Install lan-mouse, then turn the switch on."
                : "Connect Tailscale first. The bar already has a Tailscale icon for that."
              color: root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.body
            }

            PanelActionButton {
              visible: !service.status.packageInstalled
              iconText: "󰏕"
              tooltipText: service.busy ? "Installing…" : "Install lan-mouse"
              foreground: root.foreground
              fontFamily: root.fontFamily
              onClicked: service.installPackages()
            }
          }

          Column {
            width: parent.width
            spacing: Style.space(6)
            visible: service.status.tailscale.running

            Text {
              text: "THIS MACHINE"
              color: root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
              font.letterSpacing: 1
              font.bold: true
            }

            Text {
              width: parent.width
              wrapMode: Text.WrapAnywhere
              text: service.status.fingerprint !== ""
                ? service.status.fingerprint
                : "Start once to mint a fingerprint."
              color: root.foreground
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
            }

            Text {
              text: (service.status.tailscale.selfIp || "") + (service.status.tailscale.selfIp ? " · UDP " + service.status.port : "")
                + (service.status.emulationBackend ? " · " + service.status.emulationBackend : "")
              color: root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
              visible: service.status.tailscale.selfIp !== ""
            }

            Text {
              width: parent.width
              visible: service.status.emulationDummy || service.status.captureStuck
              wrapMode: Text.WordWrap
              text: service.status.emulationDummy
                ? "Incoming pointer is dummy. Release pointer so lan-mouse restarts in this desktop session."
                : "Capture is stuck. Release pointer, or the other computer is not listening."
              color: root.foreground
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
            }

            Row {
              spacing: Style.space(12)
              PanelActionButton {
                iconText: "󰆏"
                tooltipText: "Copy fingerprint"
                foreground: root.foreground
                fontFamily: root.fontFamily
                onClicked: service.copyFingerprint()
              }
              Text {
                visible: service.status.daemonRunning
                anchors.verticalCenter: parent.verticalCenter
                text: "Release pointer"
                color: root.foreground
                font.family: root.fontFamily
                font.pixelSize: Style.font.body
                font.underline: true
                MouseArea {
                  anchors.fill: parent
                  cursorShape: Qt.PointingHandCursor
                  onClicked: service.releasePointer()
                }
              }
              Text {
                visible: !service.status.packageInstalled
                anchors.verticalCenter: parent.verticalCenter
                text: service.busy ? "Installing on this computer…" : "Install lan-mouse on this computer"
                color: root.foreground
                font.family: root.fontFamily
                font.pixelSize: Style.font.body
                font.underline: true
                MouseArea {
                  anchors.fill: parent
                  cursorShape: Qt.PointingHandCursor
                  onClicked: service.installPackages()
                }
              }
            }
          }

          Column {
            width: parent.width
            spacing: Style.space(8)
            visible: service.status.tailscale.running && machines.length > 0

            Text {
              text: "LAYOUT"
              color: root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
              font.letterSpacing: 1
              font.bold: true
            }

            Text {
              width: parent.width
              wrapMode: Text.WordWrap
              text: service.busy
                ? "Setting both computers…"
                : "Click a computer, then an edge. That sets both sides: off this edge goes there, off their opposite edge comes back. If a mouse disappears, Release pointer or Control+Shift+Alt+Super."
              color: root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
            }

            Item {
              id: desk
              width: parent.width
              height: Style.space(200)

              component EdgeCard: Rectangle {
                id: slot
                property string edge: "right"
                readonly property var occupant: root.machineOnEdge(edge)
                readonly property bool lit: {
                  var sel = root.selectedMachine()
                  return (sel && occupant && sel.name === occupant.name) || (hovered && occupant)
                }
                width: Style.space(112)
                height: Style.space(58)
                radius: Style.cornerRadius
                color: occupant
                  ? (slot.lit ? Style.selectedFillFor(root.foreground, Color.accent) : Style.hoverFillFor(root.foreground, Color.accent))
                  : (slotMouse.containsMouse ? Style.hoverFillFor(root.foreground, Color.accent) : "transparent")
                border.width: Style.space(1)
                border.color: occupant ? root.foreground : root.dim
                opacity: occupant ? 1 : 0.7

                Column {
                  anchors.centerIn: parent
                  spacing: Style.space(2)
                  width: parent.width - Style.space(8)
                  Text {
                    width: parent.width
                    horizontalAlignment: Text.AlignHCenter
                    text: slot.occupant ? slot.occupant.name : slot.edge
                    color: slot.occupant ? root.foreground : root.dim
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.caption
                    font.bold: !!slot.occupant
                    elide: Text.ElideRight
                  }
                  Text {
                    width: parent.width
                    horizontalAlignment: Text.AlignHCenter
                    visible: !!slot.occupant
                    text: "back " + Model.oppositeEdge(slot.edge)
                    color: root.dim
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.caption
                    elide: Text.ElideRight
                  }
                }

                MouseArea {
                  id: slotMouse
                  anchors.fill: parent
                  hoverEnabled: true
                  acceptedButtons: Qt.LeftButton | Qt.RightButton
                  cursorShape: Qt.PointingHandCursor
                  onClicked: function(ev) {
                    if (ev.button === Qt.RightButton) {
                      if (slot.occupant) service.removePeer(slot.occupant.name)
                      return
                    }
                    var sel = root.selectedMachine()
                    if (sel) {
                      root.placeNamed(sel.name, slot.edge)
                      return
                    }
                    if (slot.occupant) {
                      root.focusSection = "machines"
                      root.machineIndex = root.indexOfMachine(slot.occupant.name)
                      root.cursorActive = true
                    }
                  }
                }
              }

              EdgeCard {
                edge: "top"
                anchors.top: parent.top
                anchors.horizontalCenter: parent.horizontalCenter
              }
              EdgeCard {
                edge: "left"
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
              }
              Rectangle {
                width: Style.space(128)
                height: Style.space(64)
                radius: Style.cornerRadius
                anchors.centerIn: parent
                color: Style.selectedFillFor(root.foreground, Color.accent)
                border.width: Style.space(1)
                border.color: root.foreground
                Column {
                  anchors.centerIn: parent
                  spacing: Style.space(2)
                  width: parent.width - Style.space(8)
                  Text {
                    width: parent.width
                    horizontalAlignment: Text.AlignHCenter
                    text: service.status.tailscale.selfName || "this screen"
                    color: root.foreground
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.body
                    font.bold: true
                    elide: Text.ElideRight
                  }
                  Text {
                    width: parent.width
                    horizontalAlignment: Text.AlignHCenter
                    text: "this machine"
                    color: root.dim
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.caption
                  }
                }
              }
              EdgeCard {
                edge: "right"
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
              }
              EdgeCard {
                edge: "bottom"
                anchors.bottom: parent.bottom
                anchors.horizontalCenter: parent.horizontalCenter
              }
            }
          }

          Column {
            width: parent.width
            spacing: Style.space(6)
            visible: machines.length > 0

            Text {
              text: "TAILSCALE MACHINES"
              color: root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
              font.letterSpacing: 1
              font.bold: true
            }

            Repeater {
              model: machines

              Rectangle {
                required property var modelData
                required property int index
                width: column.width
                height: machineCol.implicitHeight + Style.space(10)
                radius: Style.cornerRadius
                color: (root.cursorActive && root.focusSection === "machines" && root.machineIndex === index)
                  ? Style.selectedFillFor(root.foreground, Color.accent)
                  : (machineMouse.containsMouse ? Style.hoverFillFor(root.foreground, Color.accent) : "transparent")

                Column {
                  id: machineCol
                  anchors.left: parent.left
                  anchors.right: parent.right
                  anchors.verticalCenter: parent.verticalCenter
                  anchors.leftMargin: Style.space(8)
                  anchors.rightMargin: Style.space(8)
                  spacing: Style.space(2)

                  Text {
                    width: parent.width
                    text: modelData.name + (modelData.online ? "" : "  offline")
                    color: modelData.online ? root.foreground : root.dim
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.body
                    font.bold: true
                  }

                  Text {
                    width: parent.width
                    text: {
                      var bits = [Model.osLabel(modelData.os)]
                      if (modelData.configured) bits.push("edge " + modelData.position)
                      if (modelData.authorized) bits.push("can control this machine")
                      else if (modelData.configured) bits.push("waiting for their fingerprint")
                      else bits.push("click to select")
                      if (modelData.configured && modelData.healthError) bits.push(modelData.healthError)
                      else if (modelData.configured && modelData.remoteRunning === false) bits.push("lan-mouse down")
                      else if (modelData.configured && modelData.remotePaired === false) bits.push("pairing missing there")
                      return bits.join(" · ")
                    }
                    color: root.dim
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.caption
                    wrapMode: Text.WordWrap
                  }

                  Column {
                    width: parent.width
                    spacing: Style.space(4)
                    visible: root.focusSection === "machines" && root.machineIndex === index
                    topPadding: Style.space(4)

                    Text {
                      width: parent.width
                      text: {
                        if (service.busy) return "Working on " + modelData.name + "…"
                        if (root.installedFor(modelData.name)) {
                          var last = root.lastFor(modelData.name)
                          if (modelData.authorized && last.paired)
                            return "Paired. Off this screen's " + (modelData.position || "edge") + " goes there. Off their " + (last.returnEdge || "opposite") + " comes back. Re-pair if the Mac app blanks the connection."
                          if (last.paired) return "Installed and started on " + modelData.name + ". Waiting for their fingerprint."
                          return "Installed. Grant Accessibility on that Mac if it asks, then Re-pair."
                        }
                        if (root.sshFailedFor(modelData.name))
                          return "SSH did not accept this computer's user or key. Enter the SSH user and password, then Retry SSH. The password is not stored."
                        if (Model.osLabel(modelData.os) === "Windows")
                          return "Windows is installed by hand. Copy the steps below."
                        if (Model.osLabel(modelData.os) === "macOS")
                          return "Install lan-mouse over SSH, then we start it and exchange fingerprints."
                        return "Install lan-mouse over SSH when this is Arch, then we start it and exchange fingerprints."
                      }
                      color: root.dim
                      font.family: root.fontFamily
                      font.pixelSize: Style.font.caption
                      wrapMode: Text.WordWrap
                    }

                    TextField {
                      width: parent.width
                      visible: Model.osLabel(modelData.os) !== "Windows" && root.sshFailedFor(modelData.name)
                      text: root.sshUserText
                      placeholderText: "SSH user, default " + (service.status.osUser || "this computer's user")
                      foreground: root.foreground
                      font.family: root.fontFamily
                      onTextChanged: {
                        if (root.sshUserText !== text) root.sshUserText = text
                        root.rememberSshUser()
                      }
                      onActiveFocusChanged: root.sshEdit = activeFocus || sshPassField.activeFocus
                    }

                    TextField {
                      id: sshPassField
                      width: parent.width
                      visible: Model.osLabel(modelData.os) !== "Windows" && root.sshFailedFor(modelData.name)
                      password: true
                      text: root.sshPassText
                      placeholderText: "SSH password, if there is no key"
                      foreground: root.foreground
                      font.family: root.fontFamily
                      onTextChanged: if (root.sshPassText !== text) root.sshPassText = text
                      onActiveFocusChanged: root.sshEdit = activeFocus
                      Keys.onReturnPressed: root.retrySelectedSsh()
                    }

                    Row {
                      spacing: Style.space(14)
                      Text {
                        visible: Model.osLabel(modelData.os) !== "Windows" && root.sshFailedFor(modelData.name)
                        text: "Retry SSH"
                        color: root.foreground
                        font.family: root.fontFamily
                        font.pixelSize: Style.font.body
                        font.underline: true
                        font.bold: true
                        MouseArea {
                          anchors.fill: parent
                          cursorShape: Qt.PointingHandCursor
                          onClicked: root.retrySelectedSsh()
                        }
                      }
                      Text {
                        visible: modelData.configured
                        text: "Restart there"
                        color: root.foreground
                        font.family: root.fontFamily
                        font.pixelSize: Style.font.body
                        font.underline: true
                        MouseArea {
                          anchors.fill: parent
                          cursorShape: Qt.PointingHandCursor
                          onClicked: service.restartPeer(modelData.name)
                        }
                      }
                      Text {
                        visible: modelData.configured || root.installedFor(modelData.name)
                        text: "Re-pair"
                        color: root.foreground
                        font.family: root.fontFamily
                        font.pixelSize: Style.font.body
                        font.underline: true
                        MouseArea {
                          anchors.fill: parent
                          cursorShape: Qt.PointingHandCursor
                          onClicked: root.repairSelected()
                        }
                      }
                      Text {
                        visible: !root.installedFor(modelData.name) || Model.osLabel(modelData.os) === "Windows"
                        text: "Install"
                        color: root.foreground
                        font.family: root.fontFamily
                        font.pixelSize: Style.font.body
                        font.underline: true
                        MouseArea {
                          anchors.fill: parent
                          cursorShape: Qt.PointingHandCursor
                          onClicked: root.installSelected()
                        }
                      }
                      Text {
                        visible: root.sshFailedFor(modelData.name) || Model.osLabel(modelData.os) === "Windows"
                        text: "Copy steps"
                        color: root.foreground
                        font.family: root.fontFamily
                        font.pixelSize: Style.font.body
                        font.underline: true
                        MouseArea {
                          anchors.fill: parent
                          cursorShape: Qt.PointingHandCursor
                          onClicked: service.copyInstructions(modelData.name)
                        }
                      }
                      Text {
                        text: modelData.configured ? ("Place: " + modelData.position) : "Place on the right"
                        color: root.foreground
                        font.family: root.fontFamily
                        font.pixelSize: Style.font.body
                        font.underline: true
                        MouseArea {
                          anchors.fill: parent
                          cursorShape: Qt.PointingHandCursor
                          onClicked: root.cycleOrAdd(modelData)
                        }
                      }
                      Text {
                        visible: modelData.configured
                        text: "Forget pair"
                        color: root.foreground
                        font.family: root.fontFamily
                        font.pixelSize: Style.font.body
                        font.underline: true
                        MouseArea {
                          anchors.fill: parent
                          cursorShape: Qt.PointingHandCursor
                          onClicked: service.forgetPeer(modelData.name)
                        }
                      }
                    }

                    Text {
                      width: parent.width
                      visible: (service.status.lastInstall && service.status.lastInstall.name === modelData.name)
                      text: {
                        var last = root.lastFor(modelData.name)
                        if (!last.name) return ""
                        if (last.paired) return last.log || ("Paired with " + modelData.name + ".")
                        if (last.installed) return last.log || ("Installed on " + modelData.name + ".")
                        if (last.ssh === false && last.log) return "SSH failed: " + String(last.log).split("\n")[0]
                        return last.log || ""
                      }
                      color: root.foreground
                      font.family: root.fontFamily
                      font.pixelSize: Style.font.caption
                      wrapMode: Text.WordWrap
                    }
                  }
                }

                MouseArea {
                  id: machineMouse
                  anchors.fill: parent
                  z: -1
                  hoverEnabled: true
                  acceptedButtons: Qt.LeftButton | Qt.RightButton
                  onClicked: function(ev) {
                    root.focusSection = "machines"
                    root.machineIndex = index
                    root.cursorActive = true
                    if (ev.button === Qt.RightButton && modelData.configured)
                      service.removePeer(modelData.name)
                  }
                }
              }
            }
          }

          Column {
            width: parent.width
            spacing: Style.space(6)

            Text {
              text: "ALLOW A PEER IN"
              color: root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
              font.letterSpacing: 1
              font.bold: true
            }

            Text {
              width: parent.width
              wrapMode: Text.WordWrap
              text: "Paste the fingerprint from the other machine so it can push its pointer onto this one."
              color: root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
            }

            TextField {
              id: authNameField
              width: parent.width
              placeholderText: "name, usually the Tailscale hostname"
              foreground: root.foreground
              font.family: root.fontFamily
              onActiveFocusChanged: root.fingerprintEdit = activeFocus || authFpField.activeFocus
            }

            TextField {
              id: authFpField
              width: parent.width
              placeholderText: "aa:bb:cc:…"
              foreground: root.foreground
              font.family: root.fontFamily
              onActiveFocusChanged: root.fingerprintEdit = activeFocus || authNameField.activeFocus
              Keys.onReturnPressed: root.submitIncoming()
            }

            PanelActionButton {
              iconText: "󰄬"
              tooltipText: "Authorize this fingerprint"
              foreground: root.foreground
              fontFamily: root.fontFamily
              onClicked: root.submitIncoming()
            }

            Repeater {
              model: authorized
              Text {
                required property var modelData
                required property int index
                width: column.width
                text: modelData.name + " · " + Model.shortFingerprint(modelData.fingerprint)
                color: (root.cursorActive && root.focusSection === "auth" && root.authIndex === index)
                  ? root.foreground : root.dim
                font.family: root.fontFamily
                font.pixelSize: Style.font.caption
                wrapMode: Text.WrapAnywhere
                MouseArea {
                  anchors.fill: parent
                  onClicked: {
                    root.focusSection = "auth"
                    root.authIndex = index
                    service.deauthorize(modelData.fingerprint)
                  }
                }
              }
            }
          }

          Row {
            spacing: Style.space(10)
            visible: service.status.tailscale.running

            ToggleSwitch {
              id: clipSwitch
              checked: service.status.clipboardEnabled
              onToggled: service.setClipboard(checked)
            }

            Text {
              anchors.verticalCenter: parent.verticalCenter
              text: "Copy clipboard when the pointer crosses"
              color: root.foreground
              font.family: root.fontFamily
              font.pixelSize: Style.font.body
            }
          }

          Text {
            width: parent.width
            visible: service.lastError !== ""
            wrapMode: Text.WordWrap
            text: service.lastError
            color: bar ? bar.urgent : Color.urgent
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
          }
        }
      }
    }
  }
}
