pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Window
import Theme
import App

// Film grain (v2.5 F; rebuilt in v2.11 from the research below). Rules:
//  - Grain goes where there are GRADIENTS: the page atmosphere (blooms, vignette) and acrylic glass. It stops their
//    8-bit banding. Flat chrome (menu row, bar, rail) and cards get none: on a flat fill grain has nothing to hide
//    and only reads as dirt. One layer per surface, never stacked.
//  - Blue noise (scripts/theme/gen_grain.py, void and cluster): energy only at the finest scale, so it averages out to a
//    smooth surface instead of blotches. White or blurred noise clumps; never blur grain.
//  - Zero mean per theme: grain-dark.png / grain-light.png balance white and black specks for that theme's surface,
//    so the grain never lifts a dark page grey or tints a light one.
//  - One texel = one device pixel at any display scaling (laid out at devicePixelRatio size, scaled back down).
//  - Strength: AppState.grainOpacity (Settings > Appearance > Grain: Off / Subtle / Film; Effects Reduced halves it).
//    The rule of thumb: felt at arm's length, seen only up close; if it is the first thing you notice, halve it.
//  - Place it right after the surface's fill and before its content, so text and icons are never grained.
Item {
    id: root

    readonly property real dpr: Screen.devicePixelRatio > 0 ? Screen.devicePixelRatio : 1
    property real strength: 1.0

    clip: true
    opacity: AppState.grainOpacity * strength
    visible: opacity > 0

    Image {
        asynchronous: false
        cache: true
        fillMode: Image.Tile
        height: Math.ceil(root.height * root.dpr)
        horizontalAlignment: Image.AlignLeft
        mipmap: false
        scale: 1 / root.dpr
        smooth: false
        source: Qt.resolvedUrl(Theme.dark ? "../../assets/atmosphere/grain-dark.png" : "../../assets/atmosphere/grain-light.png")
        sourceSize: Qt.size(64, 64)
        transformOrigin: Item.TopLeft
        verticalAlignment: Image.AlignTop
        width: Math.ceil(root.width * root.dpr)
    }
}
