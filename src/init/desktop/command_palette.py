#  Copyright (c) 2026 Diego.
#
#  SPDX-License-Identifier: GPL-3.0-or-later
#
#  This file is part of morgan.
#
#  This program is free software: you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation, either version 3
#  of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty
#  of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
#  See the GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program. If not, see <https://www.gnu.org/licenses/>.
"""Workspace-local discovery and execution of existing desktop actions."""

import ast
import operator
import re
import threading
from dataclasses import dataclass
from math import ceil, log10
from typing import Callable

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import (
    QApplication, QFrame, QLabel, QLayout, QPlainTextEdit, QListWidget, QListWidgetItem,
    QVBoxLayout, QWidget,
)
from shiboken6 import isValid

from src.init.choice_dialog import ChoiceDialog
from src.init.lang import tr


_MATH = {}
_MATH_LOCK = threading.Lock()
_PRELOADING = False
_CONVERT = re.compile(r"\s+(?:to|in|as)\s+|\s*(?:->|→)\s*", re.IGNORECASE)
_EQUATION = re.compile(r"(?<![=<>!])=(?!=)")
_IMPLICIT_NUMBER = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)(?![\d.]|[eE][+-]?\d)\s*(?=[A-Za-z_(])")
_IMPLICIT_PAREN = re.compile(r"\)\s*(?=[\w(])")
_HEAVY = frozenset(("diff", "integrate", "limit", "solve", "simplify", "factor", "expand", "factorint"))
_LIMITS = {"factorial": 5000, "binomial": 5000, "factorint": 10 ** 18}
_BINARY = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
           ast.Div: operator.truediv}


def _load_math():
    with _MATH_LOCK:
        if not _MATH:
            import pint
            import sympy

            functions = {
                "sqrt": sympy.sqrt, "cbrt": sympy.cbrt, "root": sympy.root,
                "sin": sympy.sin, "cos": sympy.cos, "tan": sympy.tan, "cot": sympy.cot,
                "sec": sympy.sec, "csc": sympy.csc, "asin": sympy.asin, "acos": sympy.acos,
                "atan": sympy.atan, "atan2": sympy.atan2, "sinh": sympy.sinh,
                "cosh": sympy.cosh, "tanh": sympy.tanh, "asinh": sympy.asinh,
                "acosh": sympy.acosh, "atanh": sympy.atanh, "exp": sympy.exp,
                "ln": sympy.log, "log": sympy.log,
                "log2": lambda value: sympy.log(value, 2),
                "log10": lambda value: sympy.log(value, 10),
                "abs": sympy.Abs, "sign": sympy.sign, "floor": sympy.floor,
                "ceil": sympy.ceiling, "factorial": sympy.factorial,
                "binomial": sympy.binomial, "gcd": sympy.gcd, "lcm": sympy.lcm,
                "mod": sympy.Mod, "min": sympy.Min, "max": sympy.Max,
                "degrees": lambda value: value * 180 / sympy.pi,
                "radians": lambda value: value * sympy.pi / 180,
                "isprime": sympy.isprime, "factorint": sympy.factorint,
                "diff": sympy.diff, "integrate": sympy.integrate, "limit": sympy.limit,
                "solve": sympy.solve, "simplify": sympy.simplify, "factor": sympy.factor,
                "expand": sympy.expand,
            }
            constants = {
                "pi": sympy.pi, "e": sympy.E, "tau": 2 * sympy.pi, "phi": sympy.GoldenRatio,
                "i": sympy.I, "inf": sympy.oo, "oo": sympy.oo,
            }
            _MATH.update(sympy=sympy, units=pint.UnitRegistry(),
                         functions=functions, constants=constants)
        return _MATH


def preload_calculator():
    global _PRELOADING
    if _PRELOADING:
        return
    _PRELOADING = True

    def load():
        try:
            _load_math()
        except Exception:
            pass

    threading.Thread(target=load, daemon=True).start()


def _too_large(base, exponent):
    if not getattr(exponent, "is_Number", False):
        return False
    try:
        size = abs(float(exponent))
        if getattr(base, "is_Number", False):
            return base != 0 and size * abs(log10(abs(float(base)))) > 20000
        return size > 1000
    except (OverflowError, ValueError):
        return True


def _evaluate(node, namespace):
    sympy = namespace["sympy"]
    if isinstance(node, ast.Constant) and type(node.value) in (int, float):
        value = node.value
        return sympy.Integer(value) if type(value) is int else sympy.Rational(repr(value))
    if isinstance(node, ast.Name):
        if node.id in namespace["constants"]:
            return namespace["constants"][node.id]
        if node.id.startswith("_") or node.id in namespace["functions"]:
            raise ValueError(node.id)
        return sympy.Symbol(node.id)
    if isinstance(node, ast.Tuple):
        return tuple(_evaluate(item, namespace) for item in node.elts)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        operand = _evaluate(node.operand, namespace)
        return -operand if isinstance(node.op, ast.USub) else operand
    if isinstance(node, ast.BinOp):
        left = _evaluate(node.left, namespace)
        right = _evaluate(node.right, namespace)
        kind = type(node.op)
        if kind in _BINARY:
            return _BINARY[kind](left, right)
        if kind is ast.FloorDiv:
            return sympy.floor(left / right)
        if kind is ast.Mod:
            return sympy.Mod(left, right)
        if kind is ast.Pow:
            if _too_large(left, right):
                raise OverflowError
            return left ** right
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and not node.keywords and node.func.id in namespace["functions"]):
        name = node.func.id
        args = [_evaluate(arg, namespace) for arg in node.args]
        limit = _LIMITS.get(name)
        if limit is not None and any(getattr(arg, "is_Number", False) and abs(arg) > limit
                                     for arg in args):
            raise OverflowError
        if name == "integrate" and len(args) == 4:
            args = [args[0], tuple(args[1:])]
        return namespace["functions"][name](*args)
    raise ValueError


def _normalize(text):
    text = re.sub(r"(\d+)!(?!=)", r"factorial(\1)", " ".join(text.split()))
    for old, new in (("×", "*"), ("÷", "/"), ("−", "-"), ("π", "pi"), ("^", "**")):
        text = text.replace(old, new)
    return _IMPLICIT_PAREN.sub(")*", _IMPLICIT_NUMBER.sub(r"\1*", text))


def _text(value):
    return re.sub(r"\bI\b", "i", str(value).replace("**", "^"))


def _decimal(number):
    mantissa, marker, exponent = str(number).partition("e")
    if "." in mantissa:
        mantissa = mantissa.rstrip("0").rstrip(".")
    return mantissa + marker + exponent


def _present(value, namespace):
    sympy = namespace["sympy"]
    if isinstance(value, bool):
        text = "true" if value else "false"
        return "result", text, text
    if isinstance(value, dict):
        if all(isinstance(key, sympy.Symbol) for key in value):
            text = ", ".join(f"{_text(key)} = {_text(item)}" for key, item in value.items())
        else:
            text = " · ".join(f"{base}^{power}" if power > 1 else str(base)
                                   for base, power in value.items())
        return "result", text, text
    if isinstance(value, (list, tuple, set)):
        text = ", ".join(_text(item) for item in value) or "∅"
        return "result", text, text
    if value.has(sympy.zoo, sympy.nan):
        raise ValueError
    if value.free_symbols:
        text = _text(value)
        return "result", text, text
    exact = _text(value)
    if value.is_Integer or not value.is_real:
        return "result", exact, exact
    approximate = _text(_decimal(sympy.N(value, 15)))
    if exact == approximate:
        return "result", exact, exact
    denominator = value.q if value.is_Rational else 0
    for factor in (2, 5):
        while denominator and denominator % factor == 0:
            denominator //= factor
    if denominator == 1:
        return "result", approximate, approximate
    return "result", f"{exact} ≈ {approximate}", approximate


def calculate(expression, force=False):
    expression = expression.strip()
    if not expression:
        return "idle", tr("palette.calc"), ""
    try:
        namespace = _load_math()
        sympy = namespace["sympy"]
        conversion = _CONVERT.split(expression, maxsplit=1)
        if len(conversion) == 2:
            quantity = namespace["units"].Quantity(conversion[0].strip()).to(conversion[1].strip())
            text = f"{format(float(quantity.magnitude), '.10g')} {quantity.units:~P}"
            return "result", text, text
        sides = _EQUATION.split(expression)
        if len(sides) > 2:
            raise ValueError
        trees = [ast.parse(_normalize(side), mode="eval") for side in sides]
        heavy = len(trees) == 2 or any(
            isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _HEAVY
            for tree in trees for node in ast.walk(tree))
        if heavy and not force:
            return "pending", tr("palette.calc_compute"), ""
        values = [_evaluate(tree.body, namespace) for tree in trees]
        if len(values) == 1:
            return _present(values[0], namespace)
        difference = values[0] - values[1]
        symbols = sorted(difference.free_symbols, key=str)
        if not symbols:
            return _present(bool(sympy.simplify(difference) == 0), namespace)
        solutions = sympy.solve(difference, symbols[0])
        text = f"{_text(symbols[0])} = " + (", ".join(_text(item) for item in solutions) or "∅")
        return "result", text, text
    except SyntaxError:
        return "idle", tr("palette.calc"), ""
    except Exception:
        return "error", tr("palette.calc_error"), ""


@dataclass(frozen=True)
class Command:
    id: str
    label: str
    callback: Callable[[], None]
    keywords: tuple[str, ...] = ()
    available: Callable[[], bool] = lambda: True


class CommandRegistry:
    def __init__(self, commands):
        self.commands = tuple(commands)
        if len({command.id for command in self.commands}) != len(self.commands):
            raise ValueError("Command IDs must be unique")

    def search(self, query):
        tokens = query.casefold().split()
        if not tokens:
            return []
        return [command for command in self.commands
                if all(token in " ".join((tr(command.label), command.id,
                                           *command.keywords)).casefold()
                       for token in tokens)]


class CommandPalette(QFrame):
    def __init__(self, registry, owner):
        super().__init__(owner)
        self.registry = registry
        self.owner = owner
        self.host = None
        self.previous_focus = None
        self.setObjectName("commandPalette")
        self.setFrameShape(QFrame.NoFrame)
        layout = QVBoxLayout(self)
        layout.setSizeConstraint(QLayout.SetNoConstraint)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        self.search_input = QPlainTextEdit(self)
        self.search_input.setObjectName("commandPaletteSearch")
        self.search_input.setFrameShape(QFrame.NoFrame)
        self.results = QListWidget(self)
        self.results.setObjectName("commandPaletteResults")
        self.results.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.results.setTextElideMode(Qt.ElideRight)
        self.empty = QLabel(self)
        self.empty.setObjectName("commandPaletteEmpty")
        self.empty.setAlignment(Qt.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        layout.addWidget(self.search_input)
        layout.addWidget(self.results)
        layout.addWidget(self.empty)
        self.calculation = None
        self.search_input.textChanged.connect(self._filter)
        self.results.itemClicked.connect(self._execute)
        self.hide()
        self.refresh_language()

    def open(self, host):
        preload_calculator()
        if self.isVisible() and self.host is host:
            self.search_input.setFocus(Qt.ShortcutFocusReason)
            return
        self.dismiss(restore_focus=False)
        self.previous_focus = host.window().focusWidget() or QApplication.focusWidget()
        self.host = host
        self.setParent(host)
        self.results.setCurrentRow(-1)
        self.search_input.clear()
        self._filter()
        self.show()
        self.raise_()
        QApplication.instance().installEventFilter(self)
        self.search_input.setFocus(Qt.ShortcutFocusReason)

    def dismiss(self, *, restore_focus=True):
        if self.host is None:
            return
        QApplication.instance().removeEventFilter(self)
        focus, self.previous_focus = self.previous_focus, None
        self.host = None
        self.hide()
        if isValid(self.owner):
            self.setParent(self.owner)
        if restore_focus and focus is not None and isValid(focus) and focus.isVisible():
            focus.setFocus(Qt.OtherFocusReason)

    def refresh_language(self):
        self.search_input.setPlaceholderText(tr("palette.search"))
        self.search_input.setAccessibleName(tr("palette.search"))
        self.results.setAccessibleName(tr("palette.commands"))
        self.empty.setText(tr("palette.empty"))
        self._filter()

    def _filter(self, _query=None):
        expression = self._calculation()
        if expression is not None:
            self._show_calculation(expression)
            return
        self.calculation = None
        selected = self.results.currentItem()
        selected_id = getattr(selected.data(Qt.UserRole), "id", None) if selected else None
        self.results.clear()
        query = self.search_input.toPlainText()
        shell = self._shell_command()
        current = None
        for command in self.registry.search(query) if shell is None else ():
            item = QListWidgetItem(tr(command.label), self.results)
            item.setData(Qt.UserRole, command)
            item.setToolTip(item.text())
            if not command.available():
                item.setFlags(item.flags() & ~Qt.ItemIsEnabled & ~Qt.ItemIsSelectable)
                item.setToolTip(item.text() + "\n" + tr("palette.unavailable"))
            elif current is None or command.id == selected_id:
                current = item
        self.results.setCurrentItem(current)
        self.results.setVisible(self.results.count() > 0)
        self.empty.setText(tr("palette.shell") if shell is not None else tr("palette.empty"))
        self.empty.setVisible(bool(query.strip()) and self.results.count() == 0)
        self._place()

    def _calculation(self):
        text = self.search_input.toPlainText()
        return text[2:] if text.startswith(">>") else None

    def _show_calculation(self, expression, force=False):
        self.calculation = calculate(expression, force)
        state, text, _ = self.calculation
        self.results.clear()
        if state == "result":
            item = QListWidgetItem(text if len(text) <= 80 else text[:79] + "…", self.results)
            item.setToolTip(text)
            self.results.setCurrentItem(item)
        else:
            self.empty.setText(text)
        self.results.setVisible(state == "result")
        self.empty.setVisible(state != "result")
        self._place()

    def _shell_command(self):
        text = self.search_input.toPlainText()
        if not text.startswith(">") or text.startswith(">>"):
            return None
        command = text[1:]
        return command[1:] if command.startswith(" ") else command

    def _move(self, direction):
        row = self.results.currentRow()
        if row < 0 and direction < 0:
            row = self.results.count()
        for candidate in range(row + direction, self.results.count() if direction > 0 else -1, direction):
            item = self.results.item(candidate)
            if item.flags() & Qt.ItemIsEnabled:
                self.results.setCurrentItem(item)
                self.results.scrollToItem(item)
                return

    def _execute(self, item=None):
        if self.host is None:
            return
        expression = self._calculation()
        if expression is not None:
            state, _, copy = self.calculation or ("idle", "", "")
            if state == "pending":
                self._show_calculation(expression, force=True)
            elif state == "result":
                QApplication.clipboard().setText(copy)
                self.dismiss()
            return
        shell = self._shell_command()
        if shell is not None:
            if not shell.strip():
                return
            self.dismiss(restore_focus=False)
            try:
                self.owner.open_terminal_command(shell)
            except Exception as error:
                ChoiceDialog.of(self.owner).notify(tr("palette.shell_error"), f"{error}\n\n{shell}")
            return
        item = item or self.results.currentItem()
        if item is None:
            return
        command = item.data(Qt.UserRole)
        if not command.available():
            self._filter()
            return
        self.dismiss(restore_focus=False)
        command.callback()

    def _place(self):
        if self.host is None:
            return
        area = self.host.rect().adjusted(12, 12, -12, -12)
        width = max(0, min(560, area.width()))
        self.search_input.ensurePolished()
        search_margins = self.search_input.contentsMargins()
        block = self.search_input.document().firstBlock()
        content = 0.0
        while block.isValid():
            content += self.search_input.blockBoundingRect(block).height()
            block = block.next()
        limit = 6 * self.search_input.fontMetrics().lineSpacing()
        self.search_input.setVerticalScrollBarPolicy(
            Qt.ScrollBarAsNeeded if content > limit else Qt.ScrollBarAlwaysOff)
        self.search_input.setFixedHeight(
            ceil(min(content, limit) + 2 * self.search_input.document().documentMargin())
            + search_margins.top() + search_margins.bottom())
        count = self.results.count()
        row_height = self.results.sizeHintForRow(0) if count else 0
        list_frame = 2 * self.results.frameWidth()
        margins = self.layout().contentsMargins()
        overhead = (margins.top() + margins.bottom() + self.layout().spacing()
                    + self.search_input.height())
        needed = overhead + (row_height * min(3, count) + list_frame if count
                             else self.empty.sizeHint().height() if not self.empty.isHidden() else 0)
        orb = getattr(self.owner, "orb", None)
        if orb is not None and self.host.isAncestorOf(orb):
            orb_top = orb.mapTo(self.host, orb.rect().topLeft()).y()
            if orb_top - 12 >= area.y() + needed:
                area.setBottom(min(area.bottom(), orb_top - 12))
        self.results.setFixedHeight(max(0, min(row_height * min(8, count) + list_frame,
                                              area.height() - overhead)))
        height = min(max(0, area.height()), self.layout().sizeHint().height())
        self.setGeometry(area.x() + (area.width() - width) // 2,
                         area.y(), width, height)

    def eventFilter(self, watched, event):
        if self.host is None:
            return False
        if watched is self.host:
            if event.type() == QEvent.Resize:
                self._place()
            elif event.type() in (QEvent.Hide, QEvent.DeferredDelete):
                self.dismiss(restore_focus=False)
                return False
        elif (watched is getattr(self.owner, "orb", None)
              and event.type() in (QEvent.Move, QEvent.Resize)):
            self._place()
        if event.type() == QEvent.WindowDeactivate and watched is self.owner:
            self.dismiss(restore_focus=False)
        elif event.type() == QEvent.MouseButtonPress:
            if not self.rect().contains(self.mapFromGlobal(event.globalPosition().toPoint())):
                self.dismiss(restore_focus=False)
        elif (event.type() in (QEvent.ShortcutOverride, QEvent.KeyPress)
              and isinstance(watched, QWidget)
              and (watched is self or self.isAncestorOf(watched))
              and event.modifiers() == Qt.NoModifier
              and event.key() in (Qt.Key_Up, Qt.Key_Down, Qt.Key_Return, Qt.Key_Enter, Qt.Key_Escape)):
            event.accept()
            if ((self._shell_command() is not None or self._calculation() is not None)
                    and event.key() in (Qt.Key_Up, Qt.Key_Down)):
                return False
            if event.type() == QEvent.KeyPress:
                if event.isAutoRepeat() and event.key() in (Qt.Key_Return, Qt.Key_Enter):
                    return True
                if event.key() == Qt.Key_Escape:
                    self.dismiss()
                elif event.key() in (Qt.Key_Return, Qt.Key_Enter):
                    self._execute()
                else:
                    self._move(1 if event.key() == Qt.Key_Down else -1)
            return True
        return False
