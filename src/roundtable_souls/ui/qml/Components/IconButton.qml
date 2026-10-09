pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic
import Theme

// A transparent icon button (the gear on a row, window buttons, a row's reset). Icon colour = text at 80%, accent
// when `selected`; the `danger` variant (trash icons) is neutral at 50% and red on hover only (v2.5 D). The
// tooltip (ToolTip.text) shows after 500 ms below the button, as the themed card (the shared instance; v2.13: this
// used to create its own popup per button, dozens of them).
Button {
    id: root

    property bool danger: false
    property color fg: Theme.textIcon
    property color hoverColor: Theme.smearHover
    readonly property color iconColor: !enabled ? Theme.textDisabled : danger ? (hovered || down ? Theme.statusDanger : Theme.textTertiary) : selected || hovered ? Theme.goldText : fg
    property int iconSize: 16
    property string icon_: "Setting"
    property color pressColor: Theme.fillGhost
    property bool selected: false

    ToolTip.delay: Theme.mTooltipDelay
    ToolTip.visible: hovered && ToolTip.text !== ""   // the ONE shared tooltip (restyled in Main), not a popup per button
    focusPolicy: Qt.TabFocus
    hoverEnabled: true
    implicitHeight: Theme.controlH
    implicitWidth: 32

    background: Rectangle {
        color: root.down ? root.pressColor : "transparent"
        radius: Theme.radiusControl

        Smear {
            anchors.fill: parent
            peak: 0.5
            radius: Theme.radiusControl
            strength: root.hovered && !root.danger ? 1 : 0
            tint: root.hoverColor
        }
        Rectangle {
            anchors.fill: parent
            color: Theme.statusDangerBg
            opacity: root.hovered && root.danger ? 1 : 0
            radius: Theme.radiusControl
        }

        Behavior on color {
            ColorAnimation {
                duration: Theme.mFast
                easing.type: Easing.OutCubic
            }
        }

        FocusRing {
            active: root.visualFocus
            radiusOf: Theme.radiusControl
        }
    }
    contentItem: Item {
        FluentIcon {
            anchors.centerIn: parent
            color: root.iconColor
            name: root.icon_
            size: root.iconSize
        }
    }
}
