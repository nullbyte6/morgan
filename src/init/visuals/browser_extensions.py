#  Copyright (c) 2026 Diego.
#
#  SPDX-License-Identifier: GPL-3.0-or-later
#
#  This file is part of arlo.
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
"""Persistent extension preferences and the embedded browser's extension manager."""

import shutil
import struct
import tempfile
import zipfile
from pathlib import Path

from PySide6.QtCore import QObject, QSettings, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QBoxLayout, QFileDialog, QLabel, QListWidget, QListWidgetItem,
    QPushButton, QVBoxLayout, QWidget, QScrollArea, QLayout, QSizePolicy,
)


class BrowserExtensions(QObject):
    changed = Signal()
    message = Signal(str)

    def __init__(self, session):
        super().__init__(session)
        self.manager = session.profile.extensionManager()
        self._closed = False
        self.settings = QSettings(str(session.data_path / 'extensions.ini'), QSettings.IniFormat)
        self.import_path = Path(session.data_path) / 'imports'
        self.import_path.mkdir(parents=True, exist_ok=True)
        # Handle completion after Qt has returned from its registry callbacks.
        self.manager.loadFinished.connect(self._loaded, Qt.QueuedConnection)
        self.manager.installFinished.connect(self._installed, Qt.QueuedConnection)
        self.manager.uninstallFinished.connect(self._uninstalled, Qt.QueuedConnection)
        self.manager.unloadFinished.connect(self._loaded, Qt.QueuedConnection)
        for extension in self.manager.extensions():
            self._restore(extension)

    def _restore(self, extension):
        if extension.isLoaded() and extension.isInstalled():
            enabled = self.settings.value(f'enabled/{extension.id()}', True, type=bool)
            self.manager.setExtensionEnabled(extension, enabled)

    @Slot(object)
    def _loaded(self, extension):
        if self._closed:
            return
        if extension.error():
            self.message.emit(extension.error())
        else:
            self._restore(extension)
        self.changed.emit()

    @Slot(object)
    def _installed(self, extension):
        if self._closed:
            return
        if extension.error() or not extension.isInstalled():
            self.message.emit(extension.error() or 'Could not install extension')
        else:
            self.set_enabled(extension, True)
            self.message.emit(f'Installed: {extension.name()}')
        self.changed.emit()

    @Slot(object)
    def _uninstalled(self, extension):
        if self._closed:
            return
        if extension.error():
            self.message.emit(extension.error())
        else:
            self.settings.remove(f'enabled/{extension.id()}')
            self.settings.sync()
            self.message.emit('Extension removed')
        self.changed.emit()

    def set_enabled(self, extension, enabled):
        self.manager.setExtensionEnabled(extension, enabled)
        self.settings.setValue(f'enabled/{extension.id()}', enabled)
        self.settings.sync()
        self.changed.emit()

    def prepare_archive(self, source: str) -> str:
        """Convert a CRX/ZIP import into a stable unpacked MV3 directory."""
        source_path = Path(source).expanduser().resolve()
        if source_path.suffix.lower() == '.zip':
            return str(source_path)
        if source_path.suffix.lower() != '.crx':
            raise ValueError('Select a .crx or .zip Chromium extension')

        raw = source_path.read_bytes()
        if raw[:4] != b'Cr24' or len(raw) < 12:
            raise ValueError('Invalid CRX header')
        version = struct.unpack_from('<I', raw, 4)[0]
        if version == 2:
            public_size, signature_size = struct.unpack_from('<II', raw, 8)
            payload_offset = 16 + public_size + signature_size
        elif version == 3:
            header_size = struct.unpack_from('<I', raw, 8)[0]
            payload_offset = 12 + header_size
        else:
            raise ValueError(f'Unsupported CRX version: {version}')
        if payload_offset >= len(raw):
            raise ValueError('CRX payload is empty')

        archive_dir = self.import_path / source_path.stem
        if archive_dir.exists():
            shutil.rmtree(archive_dir)
        archive_dir.mkdir(parents=True)
        with tempfile.SpooledTemporaryFile() as payload:
            payload.write(raw[payload_offset:])
            payload.seek(0)
            with zipfile.ZipFile(payload) as archive:
                names = archive.namelist()
                if 'manifest.json' not in names:
                    raise ValueError('CRX manifest.json must be at the archive root')
                root = archive_dir.resolve()
                for member in archive.infolist():
                    destination = (archive_dir / member.filename).resolve()
                    if destination != root and root not in destination.parents:
                        raise ValueError('CRX contains an unsafe archive path')
                archive.extractall(archive_dir)
        return str(archive_dir)

    def shutdown(self):
        self._closed = True
        self.settings.sync()


class ExtensionsView(QWidget):
    """Resizable workspace content sharing the application's browser session."""

    def __init__(self, session, workspace):
        super().__init__()
        self.setObjectName('browserExtensionsPage')
        self.setProperty('workspaceViewKey', 'browser_extensions')
        self.session = session
        self.workspace = workspace
        self.controller = session.extensions
        self.manager = self.controller.manager
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.scroll = QScrollArea(self)
        self.scroll.setObjectName('browserExtensionsScroll')
        self.scroll.setWidgetResizable(True)
        content = QWidget()
        content.setObjectName('browserExtensionsContent')
        self.scroll.setWidget(content)
        outer.addWidget(self.scroll)
        root = QVBoxLayout(content)
        root.setSizeConstraint(QLayout.SetMinimumSize)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(12)
        hint = QLabel('Install Chromium Manifest V3 extensions from a folder or ZIP.\n'
                      'Extensions and their enabled state are saved across restarts.', self)
        hint.setWordWrap(True)
        root.addWidget(hint)
        install = QBoxLayout(QBoxLayout.LeftToRight)
        self.install_layout = install
        for label, handler in (('Install folder', self._install_folder), ('Install extension', self._install_zip)):
            button = self._button(label, handler)
            install.addWidget(button)
        root.addLayout(install)
        self.list = QListWidget(self)
        self.list.setObjectName('browserExtensionsList')
        self.list.setMinimumSize(0, 100)
        self.list.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.list.currentItemChanged.connect(self._selection_changed)
        root.addWidget(self.list, 1)
        self.details = QLabel(self)
        self.details.setWordWrap(True)
        self.details.setTextFormat(Qt.PlainText)
        root.addWidget(self.details)
        actions = QBoxLayout(QBoxLayout.LeftToRight)
        self.actions_layout = actions
        self.toggle = self._button('Enable', self._toggle)
        self.popup = self._button('Open panel', self._popup)
        self.remove = self._button('Remove', self._remove)
        for button in (self.toggle, self.popup, self.remove):
            actions.addWidget(button)
        root.addLayout(actions)
        self.status = QLabel('Ready', self)
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.PlainText)
        root.addWidget(self.status)
        self.controller.changed.connect(self.refresh)
        self.controller.message.connect(self.status.setText)
        self.refresh()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        direction = QBoxLayout.TopToBottom if self.width() < 420 else QBoxLayout.LeftToRight
        self.install_layout.setDirection(direction)
        self.actions_layout.setDirection(direction)

    def _button(self, label, handler):
        button = QPushButton(label, self)
        button.setCursor(Qt.PointingHandCursor)
        button.clicked.connect(handler)
        return button

    def _selected(self):
        item = self.list.currentItem()
        if item is not None:
            return next((ext for ext in self.manager.extensions()
                         if ext.id() == item.data(Qt.UserRole)), None)
        return None

    @Slot()
    def refresh(self):
        selected = self._selected()
        selected_id = selected.id() if selected else None
        self.list.clear()
        for extension in self.manager.extensions():
            # The built-in PDF and Hangouts components are not user installs.
            if not extension.isInstalled():
                continue
            state = 'Enabled' if extension.isEnabled() else 'Disabled'
            item = QListWidgetItem(f'{extension.name()}  ·  {state}')
            item.setData(Qt.UserRole, extension.id())
            self.list.addItem(item)
            if extension.id() == selected_id:
                self.list.setCurrentItem(item)
        if self.list.currentItem() is None and self.list.count():
            self.list.setCurrentRow(0)
        self._selection_changed()

    def _selection_changed(self, *_):
        extension = self._selected()
        self.toggle.setEnabled(extension is not None)
        self.remove.setEnabled(extension is not None)
        self.popup.setEnabled(extension is not None and extension.isEnabled()
                              and not extension.actionPopupUrl().isEmpty())
        self.toggle.setText('Disable' if extension and extension.isEnabled() else 'Enable')
        self.details.setText(extension.description() if extension else 'No extensions installed')

    def _install_folder(self):
        path = QFileDialog.getExistingDirectory(self, 'Select extension folder')
        if path:
            self.status.setText('Installing…')
            self.manager.installExtension(path)

    def _install_zip(self):
        path, _ = QFileDialog.getOpenFileName(
            self, 'Select Chromium extension', '',
            'Chromium extension (*.crx *.zip);;CRX extension (*.crx);;ZIP extension (*.zip)')
        if path:
            self.status.setText('Installing…')
            try:
                self.manager.installExtension(self.controller.prepare_archive(path))
            except (OSError, ValueError, zipfile.BadZipFile) as error:
                self.status.setText(f'Could not prepare extension: {error}')

    def _toggle(self):
        extension = self._selected()
        if extension:
            self.controller.set_enabled(extension, not extension.isEnabled())

    def _remove(self):
        extension = self._selected()
        if extension:
            self.status.setText('Removing…')
            self.manager.uninstallExtension(extension)

    def _popup(self):
        extension = self._selected()
        if extension and extension.isEnabled() and not extension.actionPopupUrl().isEmpty():
            from PySide6.QtWebEngineWidgets import QWebEngineView
            from .workspace import WorkspacePanel
            owner = self.parentWidget()
            while owner is not None and not isinstance(owner, WorkspacePanel):
                owner = owner.parentWidget()
            session_id = owner.property("session_id") if owner is not None else None
            key = f'browser_extension:{extension.id()}'
            for panel_id in self.workspace.panel_ids:
                panel = self.workspace.get_panel(panel_id)
                if (panel.property('workspaceViewKey') == key
                        and panel.property('session_id') == session_id
                        and panel_id not in self.workspace._closing_panels):
                    self.workspace.focus_panel(panel_id)
                    return
            popup = QWidget()
            popup.setObjectName('browserExtensionPopup')
            popup.setProperty('workspaceViewKey', key)
            layout = QVBoxLayout(popup)
            layout.setContentsMargins(8, 8, 8, 8)
            view = QWebEngineView(popup)
            view.setPage(self.session.create_page(view))
            def open_web_link(request):
                from .browser_bridge import open_embedded_url
                url = request.requestedUrl()
                if url.scheme() in ('http', 'https'):
                    try:
                        open_embedded_url(url.toString(), session_id=session_id)
                    except (RuntimeError, ValueError) as error:
                        view.setToolTip(str(error))

            view.page().newWindowRequested.connect(open_web_link)
            layout.addWidget(view)
            view.setUrl(extension.actionPopupUrl())
            panel_id = self.workspace.open_panel(title=extension.name(), content=popup,
                                                 target_id=owner.panel_id if owner is not None else None)
            self.workspace.get_panel(panel_id).setProperty('session_id', session_id)
