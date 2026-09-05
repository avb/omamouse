import QtQuick
import QtQuick.Controls
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui
import "Model.js" as Model

Panel {
  id: root
  moduleName: "io.github.dicebagstudios.lan-mouse"
  ipcTarget: "io.github.dicebagstudios.lan-mouse"
  manageIpc: false

  property string focusSection: "header"
  property int machineIndex: 0
  property int authIndex: 0
  property bool cursorActive: false
  property bool fingerprintEdit: false
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
  readonly property color barIconColor: service.status.daemonRunning ? barForeground : Qt.darker(barForeground, 1.55)
  readonly property string statusLine: {
    if (!service.status.packageInstalled) return "lan-mouse is not installed"
    if (!service.status.tailscale.installed) return "Tailscale is not installed"
    if (!service.status.tailscale.running) return "Tailscale is disconnected"
    if (service.status.daemonRunning) return heroPhraseText
    if (service.lastError) return service.lastError
    return "Lan Mouse is off"
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

  function cycleOrAdd(machine) {
    if (!machine) return
    if (!machine.configured) {
      service.addPeer(machine.name, "right")
      return
    }
    var idx = positionChoices.indexOf(machine.position)
    var next = positionChoices[(idx + 1) % positionChoices.length]
    service.addPeer(machine.name, next)
  }

  function forgetAuth(row) {
    if (!row) return
    service.deauthorize(row.fingerprint)
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
    root.controller.show()
    Qt.callLater(function() { if (keyCatcher) keyCatcher.forceActiveFocus() })
  }
  function close() {
    fingerprintEdit = false
    root.controller.hide()
  }
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
    contentWidth: panel.fittedContentWidth(Style.space(400))
    contentHeight: panel.fittedContentHeight(column.implicitHeight, Style.space(560))

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      blocked: root.fingerprintEdit
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
        else if (t === "i" || t === "I") service.installPackages()
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
              title: service.status.tailscale.selfName || "Lan Mouse"
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
              color: root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
              visible: service.status.tailscale.selfIp !== ""
            }

            PanelActionButton {
              iconText: "󰆏"
              tooltipText: "Copy fingerprint"
              foreground: root.foreground
              fontFamily: root.fontFamily
              onClicked: service.copyFingerprint()
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
                      else bits.push("click to add on the right")
                      return bits.join(" · ")
                    }
                    color: root.dim
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.caption
                    wrapMode: Text.WordWrap
                  }
                }

                MouseArea {
                  id: machineMouse
                  anchors.fill: parent
                  hoverEnabled: true
                  acceptedButtons: Qt.LeftButton | Qt.RightButton
                  onClicked: function(ev) {
                    root.focusSection = "machines"
                    root.machineIndex = index
                    root.cursorActive = true
                    if (ev.button === Qt.RightButton && modelData.configured)
                      service.removePeer(modelData.name)
                    else
                      root.cycleOrAdd(modelData)
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
