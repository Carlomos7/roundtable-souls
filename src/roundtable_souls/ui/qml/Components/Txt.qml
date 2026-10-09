pragma ComponentBehavior: Bound
import QtQuick
import Theme

// Text in the type roles (v2.5 A): body 13, strong (body 600), caption / hint 12 secondary, tertiary 12 at 50%,
// rowTitle 14/600, section 18/600, page 22/600 ("title" is kept as page). `tabular` turns on tabular figures for
// numbers (font.features, Qt 6.6+).
Text {
    id: root

    property string kind: "body"
    property bool tabular: false

    elide: Text.ElideRight
    readonly property bool head: kind === "section" || kind === "page" || kind === "title" || kind === "cardTitle"
    readonly property bool serif: head || kind === "rowTitle" || kind === "serif"

    font.family: head ? Theme.fontHead : serif ? Theme.fontSerif : Theme.fontFamily
    font.features: tabular ? ({
            "tnum": 1
        }) : ({})
    font.pixelSize: kind === "caption" || kind === "hint" || kind === "tertiary" ? Theme.fontCaption : kind === "rowTitle" ? Math.round(Theme.fontRow * 1.12) : kind === "serif" ? 15 : kind === "cardTitle" ? 18 : kind === "section" ? Math.round(Theme.fontSection * Theme.headScale) : kind === "page" || kind === "title" ? Math.round(Theme.fontPage * Theme.headScale) : Theme.fontBody
    font.weight: head ? Font.DemiBold : kind === "rowTitle" ? Font.Medium : kind === "strong" ? Font.DemiBold : Font.Normal
    color: head ? (kind === "section" || kind === "cardTitle" ? Theme.textPrimary : Theme.title) : kind === "hint" || kind === "caption" ? Theme.textSecondary : kind === "tertiary" ? Theme.textTertiary : Theme.textPrimary
    verticalAlignment: Text.AlignVCenter

    Behavior on color {
        ColorAnimation {
            duration: Theme.mFast
            easing.type: Easing.OutCubic
        }
    }
}
