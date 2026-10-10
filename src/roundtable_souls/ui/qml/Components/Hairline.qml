pragma ComponentBehavior: Bound
import QtQuick
import Theme

// A 1 px hairline (v2.5 D): integer position, no antialiasing. Horizontal by default, spanning the parent's width
// minus `inset` on the left and `endInset` on the right (dividers stop 16 px short of card edges; row dividers start
// 56 px in, under the title). Set `y` (or anchor the bottom) yourself; `vertical` makes it the one vertical divider.
Rectangle {
    id: root

    property int endInset: 0
    property int inset: 0
    property bool vertical: false

    antialiasing: false
    color: Theme.borderHairline
    height: vertical ? Math.max(0, (parent ? parent.height : 0) - inset - endInset) : 1
    width: vertical ? 1 : Math.max(0, (parent ? parent.width : 0) - inset - endInset)
    x: vertical ? 0 : inset
    y: vertical ? inset : 0

    Behavior on color {
        ColorAnimation {
            duration: Theme.mToggle
            easing.type: Easing.OutCubic
        }
    }
}
