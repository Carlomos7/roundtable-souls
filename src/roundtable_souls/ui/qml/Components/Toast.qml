pragma ComponentBehavior: Bound
import QtQuick
import Theme

// A toast (v2.3 C.3): the result of something the user just did. Success / info hide after 4.5 s; an error stays
// until closed and carries "Details" (opens Activity). One at a time: the host replaces the previous one.
// Floats (v2.5 D / E): no border, shadow y8 blur24 45%; in 160 ms from the bottom, out 120 ms, never a bounce.
// An error shows a 3 px danger bar on the left with its icon (colour never the only signal).
// Acrylic: `acrylicSlot` behind the body holds the Acrylic (12 px blur + Theme.surfaceAcrylic; v2.5 F).
Rectangle {
    id: root

    property bool acrylic: false   // v2.15 (owner): overlays are opaque; the blur is opt-in per instance
    property var action: null
    property string actionLabel: ""
    property bool isError: false
    property string text

    signal done

    function dismiss() {
        hide.stop();
        fadeOut.start();
    }

    color: "transparent"
    height: 44
    opacity: 0
    width: Math.min(parent ? parent.width - Theme.padDialog * 2 : 520, row.implicitWidth + 32 + (isError ? 30 : 0))

    transform: Translate {
        id: slide

        y: 12
    }

    Component.onCompleted: {
        showAnim.start();
        if (!isError)
            hide.start();
    }

    ParallelAnimation {
        id: showAnim

        NumberAnimation {
            duration: Theme.mToastIn
            easing.type: Easing.OutCubic
            property: "opacity"
            target: root
            to: 1
        }
        NumberAnimation {
            duration: Theme.mToastIn
            easing.type: Easing.OutCubic
            property: "y"
            target: slide
            to: 0
        }
    }
    SequentialAnimation {
        id: hide

        PauseAnimation {
            duration: Theme.mToastHold
        }
        NumberAnimation {
            duration: Theme.mToastOut
            easing.type: Easing.OutCubic
            property: "opacity"
            target: root
            to: 0
        }
        ScriptAction {
            script: root.done()
        }
    }
    SequentialAnimation {
        id: fadeOut

        NumberAnimation {
            duration: Theme.mToastOut
            easing.type: Easing.OutCubic
            property: "opacity"
            target: root
            to: 0
        }
        ScriptAction {
            script: root.done()
        }
    }
    SoftShadow {
        elevation: "float"
        radius: Theme.radiusOverlay
        target: body
    }
    Item {
        id: acrylicSlot

        anchors.fill: parent

        Acrylic {  // 12 px blur for toasts (v2.5 F) + the card tint; the opaque card without blur
            active: root.acrylic
            anchors.fill: parent
            blurPx: Theme.ceilingBlurToastPx
            radius: Theme.radiusOverlay
        }
    }
    Rectangle {  // the shape the shadow follows and the error mark's clip; the acrylic paints the fill
        id: body

        anchors.fill: parent
        clip: true
        color: "transparent"
        radius: Theme.radiusOverlay

        Rectangle {  // the error mark
            anchors.bottom: parent.bottom
            anchors.left: parent.left
            anchors.top: parent.top
            color: Theme.statusDanger
            visible: root.isError
            width: 3
        }
    }
    Row {
        id: row

        anchors.left: parent.left
        anchors.leftMargin: Theme.sp16
        anchors.verticalCenter: parent.verticalCenter
        spacing: Theme.sp12

        FluentIcon {
            anchors.verticalCenter: parent.verticalCenter
            color: root.isError ? Theme.statusDanger : Theme.statusSuccess
            name: root.isError ? "Cancel" : "Accept"
            size: 14
        }
        Txt {
            anchors.verticalCenter: parent.verticalCenter
            text: root.text
        }
        Txt {
            anchors.verticalCenter: parent.verticalCenter
            color: Theme.accent
            kind: "strong"
            text: root.actionLabel
            visible: root.actionLabel !== ""

            MouseArea {
                anchors.fill: parent
                anchors.margins: -8
                cursorShape: Qt.PointingHandCursor

                onClicked: {
                    if (root.action)
                        root.action();
                    root.dismiss();
                }
            }
        }
    }
    IconButton {
        anchors.right: parent.right
        anchors.rightMargin: Theme.sp4
        anchors.verticalCenter: parent.verticalCenter
        iconSize: 10
        icon_: "Close"
        implicitHeight: Theme.controlSmallH
        implicitWidth: 26
        visible: root.isError

        onClicked: root.dismiss()
    }
}
