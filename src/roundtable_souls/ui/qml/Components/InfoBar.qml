pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic
import Theme

// An inline notice at the top of the page it concerns (v2.3 C.2; qfluentwidgets.InfoBar in the real launcher):
// severity sets colour and icon; closable when the user can safely ignore it; one action button at most.
// No border (v2.5 D): the tinted status.bg only; the icon always accompanies the words (warning shares the gold).
Rectangle {
    id: root

    property string actionLabel: ""
    readonly property color bgc: severity === "error" ? Theme.statusDangerBg : severity === "warning" ? Theme.statusWarningBg : severity === "success" ? Theme.statusSuccessBg : Theme.statusInfoBg
    property bool closable: true
    readonly property color fg: severity === "error" ? Theme.statusDanger : severity === "warning" ? Theme.statusWarning : severity === "success" ? Theme.statusSuccess : Theme.statusInfo
    property bool open: true
    property string severity: "info"          // info | success | warning | error
    property string text

    signal actionClicked
    signal closed

    clip: true
    color: bgc
    implicitHeight: open ? Math.max(42, label.implicitHeight + 20) : 0
    radius: Theme.radiusControl
    visible: open

    Behavior on color {
        ColorAnimation {
            duration: Theme.mToggle
            easing.type: Easing.OutCubic
        }
    }

    FluentIcon {
        id: ic

        anchors.left: parent.left
        anchors.leftMargin: Theme.sp12
        anchors.verticalCenter: parent.verticalCenter
        color: root.fg
        name: root.severity === "error" ? "Cancel" : root.severity === "success" ? "Accept" : "Info"
        size: 14
    }
    Txt {
        id: label

        anchors.left: ic.right
        anchors.leftMargin: Theme.sp12
        anchors.right: actionBtn.visible ? actionBtn.left : (closeBtn.visible ? closeBtn.left : parent.right)
        anchors.rightMargin: Theme.sp12
        anchors.verticalCenter: parent.verticalCenter
        color: Theme.textPrimary
        elide: Text.ElideNone
        text: root.text
        wrapMode: Text.WordWrap
    }
    GhostButton {
        id: actionBtn

        anchors.right: closeBtn.visible ? closeBtn.left : parent.right
        anchors.rightMargin: Theme.sp8
        anchors.verticalCenter: parent.verticalCenter
        implicitHeight: Theme.controlSmallH
        text: root.actionLabel
        visible: root.actionLabel !== ""

        onClicked: root.actionClicked()
    }
    IconButton {
        id: closeBtn

        ToolTip.text: qsTr("Dismiss")
        anchors.right: parent.right
        anchors.rightMargin: Theme.sp8
        anchors.verticalCenter: parent.verticalCenter
        iconSize: 11
        icon_: "Close"
        implicitHeight: Theme.controlSmallH
        implicitWidth: 28
        visible: root.closable

        onClicked: {
            root.open = false;
            root.closed();
        }
    }
}
