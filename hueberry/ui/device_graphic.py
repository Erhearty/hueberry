# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""A Polychromatic device-map SVG painted with live LED colours.

An LED is a node (or the ``<g>`` parent of several nodes) with class ``LED``
and id ``x{col}-y{row}``. Its paintable shapes (path, rect, circle, text,
ellipse, polygon) get the LED colour as fill and stroke, merged into their
``style`` so it overrides inline styles. A ``nostroke="true"`` node gets black
or white (whichever contrasts with the LED colour) and no stroke; a
``nochange="true"`` node is left untouched. An LED without a colour (None) keeps
the SVG's original styling. The SVG is parsed once and only re-serialised into
the renderer when the colours change.
"""

import io
import logging
import re
import xml.etree.ElementTree as ET
from typing import Callable

from PyQt6.QtCore import QByteArray, QPointF, QRectF, QSize, QSizeF
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtSvg import QSvgRenderer

__all__ = ["DeviceGraphic"]

logger = logging.getLogger(__name__)

SVG_NS = "http://www.w3.org/2000/svg"
KNOWN_NAMESPACES = {
    "": SVG_NS,
    "xlink": "http://www.w3.org/1999/xlink",
    "sodipodi": "http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd",
    "inkscape": "http://www.inkscape.org/namespaces/inkscape",
}
LED_CLASS = "LED"
LED_ID = re.compile(r"^x(\d+)-y(\d+)$")
PAINTABLE_TAGS = frozenset({"path", "rect", "circle", "text", "ellipse", "polygon"})
TRUE_TEXT = "true"
NOSTROKE_ATTR = "nostroke"
NOCHANGE_ATTR = "nochange"
CLASS_ATTR = "class"
ID_ATTR = "id"
STYLE_ATTR = "style"
FILL = "fill"
STROKE = "stroke"
ORIGINAL_ATTRS = (STYLE_ATTR, FILL, STROKE)  # restored for an LED without a colour
NO_STROKE = "none"
MODE_COLOUR = "colour"  # fill and stroke take the LED colour
MODE_CONTRAST = "contrast"  # black/white fill contrasting the LED colour, no stroke
DARK = "#000000"
LIGHT = "#ffffff"
HEX_COLOUR = "#{:02x}{:02x}{:02x}"
RGB_MAX = 255
# sRGB linearisation and relative luminance (WCAG 2.x)
SRGB_THRESHOLD = 0.04045
SRGB_LOW_DIVISOR = 12.92
SRGB_OFFSET = 0.055
SRGB_SCALE = 1.055
SRGB_GAMMA = 2.4
LUMINANCE_WEIGHTS = (0.2126, 0.7152, 0.0722)
CONTRAST_FLARE = 0.05
WHITE_LUMINANCE = 1.0
HALF = 0.5
ENCODING = "utf-8"
NS_EVENT = "start-ns"

RGBTuple = tuple[int, int, int]
Led = tuple[int, int]  # (row, col)
Originals = dict[str, str | None]  # ORIGINAL_ATTRS as parsed, None where absent
Paintable = tuple[ET.Element, str, Originals]  # element, its mode, its original styling


def _register(prefix: str, uri: str) -> None:
    """Register one namespace prefix for serialisation; reserved prefixes are skipped."""
    try:
        ET.register_namespace(prefix, uri)
    except ValueError:
        logger.debug("Namespace prefix %r cannot be registered", prefix)


def _register_namespaces(data: bytes) -> None:
    """Register the common SVG namespaces plus every prefix declared in ``data``."""
    for prefix, uri in KNOWN_NAMESPACES.items():
        _register(prefix, uri)
    try:
        for _, (prefix, uri) in ET.iterparse(io.BytesIO(data), events=(NS_EVENT,)):
            if prefix and uri != SVG_NS:  # e.g. xmlns:svg must not claim the SVG namespace
                _register(prefix, uri)
    except ET.ParseError:
        pass  # reported by the real parse
    _register("", SVG_NS)  # last, so SVG is always serialised as the default namespace


def _local(tag: object) -> str:
    """The tag name without its ``{namespace}``."""
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _led_key(node: ET.Element) -> Led | None:
    """``(row, col)`` of an LED node, or None when ``node`` is not an LED."""
    if LED_CLASS not in (node.get(CLASS_ATTR) or "").split():
        return None
    found = LED_ID.match(node.get(ID_ATTR) or "")
    if found is None:
        return None
    return int(found[2]), int(found[1])


def _paintables(node: ET.Element, mode: str) -> list[Paintable]:
    """The paintable shapes of ``node`` and its descendants, each with its mode."""
    if node.get(NOCHANGE_ATTR) == TRUE_TEXT:
        return []
    if node.get(NOSTROKE_ATTR) == TRUE_TEXT:
        mode = MODE_CONTRAST
    found = [(node, mode, _originals(node))] if _local(node.tag) in PAINTABLE_TAGS else []
    for child in node:
        found.extend(_paintables(child, mode))
    return found


def _originals(node: ET.Element) -> Originals:
    """The styling attributes of ``node`` as parsed."""
    return {attr: node.get(attr) for attr in ORIGINAL_ATTRS}


def _restore(element: ET.Element, originals: Originals) -> None:
    """Put the parsed styling attributes of ``element`` back."""
    for attr, value in originals.items():
        if value is None:
            element.attrib.pop(attr, None)
        else:
            element.set(attr, value)


def _index(root: ET.Element) -> dict[Led, list[Paintable]]:
    """Every LED of the SVG with its paintable shapes."""
    index: dict[Led, list[Paintable]] = {}
    for node in root.iter():
        key = _led_key(node)
        if key is not None:
            index.setdefault(key, []).extend(_paintables(node, MODE_COLOUR))
    return index


def _led_ids(root: ET.Element) -> dict[Led, list[str]]:
    """The element ids (as parsed) of every LED of the SVG."""
    ids: dict[Led, list[str]] = {}
    for node in root.iter():
        key = _led_key(node)
        if key is not None:
            ids.setdefault(key, []).append(node.get(ID_ATTR) or "")
    return ids


def _element_rects(renderer: QSvgRenderer, root: ET.Element) -> dict[Led, QRectF]:
    """Each LED's bounds in viewBox coordinates; LEDs the renderer lacks are skipped."""
    rects: dict[Led, QRectF] = {}
    for led, ids in _led_ids(root).items():
        for element_id in ids:
            if not renderer.elementExists(element_id):
                continue
            bounds = renderer.transformForElement(element_id).mapRect(
                renderer.boundsOnElement(element_id))
            rects[led] = rects[led].united(bounds) if led in rects else bounds
    return rects


def _merge_style(style: str | None, fill: str, stroke: str) -> str:
    """``style`` (``k:v;`` pairs) with its fill and stroke replaced."""
    pairs: dict[str, str] = {}
    for item in (style or "").split(";"):
        key, sep, value = item.partition(":")
        if sep and key.strip():
            pairs[key.strip()] = value.strip()
    pairs[FILL] = fill
    pairs[STROKE] = stroke
    return ";".join(f"{key}:{value}" for key, value in pairs.items())


def _channel(value: int) -> float:
    """One sRGB channel (0-255) linearised."""
    scaled = value / RGB_MAX
    if scaled <= SRGB_THRESHOLD:
        return scaled / SRGB_LOW_DIVISOR
    return ((scaled + SRGB_OFFSET) / SRGB_SCALE) ** SRGB_GAMMA


def _contrasting(rgb: RGBTuple) -> str:
    """Black or white, whichever has the higher contrast ratio with ``rgb``."""
    luminance = sum(weight * _channel(value) for weight, value in zip(LUMINANCE_WEIGHTS, rgb))
    with_dark = (luminance + CONTRAST_FLARE) / CONTRAST_FLARE
    with_light = (WHITE_LUMINANCE + CONTRAST_FLARE) / (luminance + CONTRAST_FLARE)
    return DARK if with_dark >= with_light else LIGHT


def _fill_and_stroke(mode: str, rgb: RGBTuple) -> tuple[str, str]:
    """The fill and stroke of a shape in ``mode`` lit with ``rgb``."""
    if mode == MODE_CONTRAST:
        return _contrasting(rgb), NO_STROKE
    colour = HEX_COLOUR.format(*rgb)
    return colour, colour


def _rgb(colour: QColor | None) -> RGBTuple | None:
    """``colour`` as an RGB tuple, or None for an unlit LED."""
    return None if colour is None else (colour.red(), colour.green(), colour.blue())


class DeviceGraphic:
    """One device-map SVG whose LEDs are recoloured and rendered on demand."""

    def __init__(self, svg: bytes) -> None:
        """Parse ``svg``; raises ValueError when it is not a renderable SVG."""
        _register_namespaces(svg)
        try:
            self._root = ET.fromstring(svg)
        except ET.ParseError as exc:
            raise ValueError(f"device map is not valid XML: {exc}") from exc
        self._renderer = QSvgRenderer(QByteArray(svg))
        if not self._renderer.isValid():
            raise ValueError("device map is not a renderable SVG")
        self._elements = _index(self._root)
        self._order = sorted(self._elements)
        self._led_rects = _element_rects(self._renderer, self._root)  # before recolouring
        self._key: tuple[RGBTuple | None, ...] | None = None
        self.reload_count = 0

    @property
    def renderer(self) -> QSvgRenderer:
        """The renderer holding the most recently coloured SVG."""
        return self._renderer

    def leds(self) -> set[Led]:
        """Every ``(row, col)`` the SVG draws."""
        return set(self._elements)

    def led_rects(self) -> dict[Led, QRectF]:
        """Each drawn LED's ``(row, col)`` with its bounds in viewBox coordinates."""
        return {led: QRectF(rect) for led, rect in self._led_rects.items()}

    def to_widget(self, rect: QRectF, target: QRectF) -> QRectF:
        """``rect`` (viewBox coordinates) mapped onto ``target`` (from :meth:`target_rect`)."""
        view = self._renderer.viewBoxF()
        if view.isEmpty():
            view = QRectF(QPointF(), QSizeF(self.default_size()))
        if view.isEmpty():
            return QRectF()
        scale_x = target.width() / view.width()
        scale_y = target.height() / view.height()
        return QRectF(target.left() + (rect.left() - view.left()) * scale_x,
                      target.top() + (rect.top() - view.top()) * scale_y,
                      rect.width() * scale_x, rect.height() * scale_y)

    def default_size(self) -> QSize:
        """The SVG's own size."""
        return self._renderer.defaultSize()

    def target_rect(self, rect: QRectF) -> QRectF:
        """The largest rect of the SVG's aspect ratio centred in ``rect``."""
        size = self.default_size()
        if size.isEmpty() or rect.isEmpty():
            return QRectF(rect)
        scale = min(rect.width() / size.width(), rect.height() / size.height())
        width, height = size.width() * scale, size.height() * scale
        return QRectF(rect.left() + (rect.width() - width) * HALF,
                      rect.top() + (rect.height() - height) * HALF, width, height)

    def paint(self, painter: QPainter, rect: QRectF,
              colour_for: Callable[[int, int], QColor | None]) -> None:
        """Render aspect-fit in ``rect`` with each LED lit by ``colour_for(row, col)``.

        A None colour leaves that LED with the SVG's original styling.
        """
        colours = {led: _rgb(colour_for(*led)) for led in self._order}
        key = tuple(colours[led] for led in self._order)
        if key != self._key:
            self._apply(colours)
            self._renderer.load(QByteArray(ET.tostring(self._root, encoding=ENCODING)))
            self._key = key
            self.reload_count += 1
        self._renderer.render(painter, self.target_rect(rect))

    def _apply(self, colours: dict[Led, RGBTuple | None]) -> None:
        """Write each LED's colour into the style of its shapes (None restores them)."""
        for led, elements in self._elements.items():
            rgb = colours[led]
            for element, mode, originals in elements:
                if rgb is None:
                    _restore(element, originals)
                    continue
                fill, stroke = _fill_and_stroke(mode, rgb)
                element.set(STYLE_ATTR, _merge_style(originals[STYLE_ATTR], fill, stroke))
