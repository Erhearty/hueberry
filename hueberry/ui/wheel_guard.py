# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2025 Hueberry contributors
"""App-wide guard so the mouse wheel scrolls pages instead of editing fields.

A wheel event over an unfocused spin box or combo box is forwarded to the
widget's parent (so a surrounding scroll area scrolls) and swallowed. Focused
fields behave normally.

Qt gives ``QAbstractSpinBox`` and ``QComboBox`` the ``WheelFocus`` policy by
default. For a spontaneous wheel event ``QApplication::notify`` focuses a
``WheelFocus`` widget *before* application event filters run, so by the time
the guard sees the wheel the field already reports ``hasFocus()`` and the value
would change. Guarded fields are therefore demoted to ``StrongFocus`` as soon
as they are polished (and, on install, for every widget that already exists),
so the wheel can never grant them focus.
"""

from PyQt6.QtCore import QEvent, QObject, Qt
from PyQt6.QtGui import QWheelEvent
from PyQt6.QtWidgets import QAbstractSpinBox, QApplication, QComboBox, QLineEdit, QWidget

_GUARDED = (QAbstractSpinBox, QComboBox)


def _guarded_field(widget: QObject) -> QWidget | None:
    """The spin/combo box ``widget`` is or is the line edit of, else None."""
    if isinstance(widget, _GUARDED):
        return widget
    if isinstance(widget, QLineEdit) and isinstance(widget.parent(), _GUARDED):
        return widget.parent()
    return None


def _make_strong(widget: QWidget) -> None:
    """Demote a wheel-focusable policy to StrongFocus; leave others untouched."""
    wheel = Qt.FocusPolicy.WheelFocus.value
    if (widget.focusPolicy().value & wheel) == wheel:
        widget.setFocusPolicy(Qt.FocusPolicy.StrongFocus)


def _field_has_focus(field: QWidget) -> bool:
    """Whether ``field`` or its focus proxy/child currently has focus."""
    if field.hasFocus():
        return True
    child = field.focusWidget()
    return child is not None and child.hasFocus()


class WheelGuard(QObject):
    """Event filter that stops wheel events from changing unfocused fields."""

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: N802 (Qt API)
        """Demote guarded fields on polish; redirect wheel on unfocused fields."""
        if event.type() == QEvent.Type.Polish:
            if isinstance(obj, _GUARDED):
                _make_strong(obj)
            return False
        if event.type() != QEvent.Type.Wheel:
            return False
        field = _guarded_field(obj)
        if field is None or _field_has_focus(field):
            return False
        parent = field.parentWidget()
        if parent is not None and isinstance(event, QWheelEvent):
            QApplication.sendEvent(parent, event)
        return True


def install(app: QApplication) -> WheelGuard:
    """Install a WheelGuard on ``app`` and return it (kept alive by parenting).

    Widgets polished later are demoted by the filter itself; guarded widgets
    that already exist are demoted here.
    """
    guard = WheelGuard(app)
    app.installEventFilter(guard)
    for widget in QApplication.allWidgets():
        if isinstance(widget, _GUARDED):
            _make_strong(widget)
    return guard
