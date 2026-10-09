pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic
import Theme

// A one-line text field (v2.5 D): 6% fill, no border at rest; a 2 px accent ring 2 px outside while it has focus
// (typing goes here), danger when `error`.
TextField {
    id: root

    property bool error: false

    color: Theme.textPrimary
    font.family: Theme.fontFamily
    font.pixelSize: Theme.fontBody
    implicitHeight: Theme.controlH
    implicitWidth: Theme.inputW
    leftPadding: Theme.sp10
    placeholderTextColor: Theme.textSecondary
    selectedTextColor: Theme.textOnAccent
    selectionColor: Theme.accent

    background: Rectangle {
        color: Theme.fillInput
        radius: Theme.radiusControl

        Behavior on color {
            ColorAnimation {
                duration: Theme.mToggle
                easing.type: Easing.OutCubic
            }
        }

        FocusRing {
            active: root.activeFocus
            error: root.error
            radiusOf: Theme.radiusControl
        }
    }
}
