from qgis.PyQt.QtWidgets import (
    QAction, QAbstractItemView, QDockWidget, QTreeView,
    QVBoxLayout, QWidget, QToolButton, QToolBar, QMenu,
)
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtCore import Qt, QSize, QPoint, QTimer, QModelIndex
from qgis.core import (
    QgsLayerTreeLayer, QgsLayerTreeGroup, QgsProject, QgsVectorLayer,
)
import os

try:
    ContextMenuPolicy = Qt.ContextMenuPolicy
    DockWidgetArea = Qt.DockWidgetArea
except AttributeError:
    ContextMenuPolicy = Qt
    DockWidgetArea = Qt

try:
    DragDrop = QAbstractItemView.DragDropMode.DragDrop
    MoveAction = Qt.DropAction.MoveAction
except AttributeError:
    DragDrop = QAbstractItemView.DragDrop
    MoveAction = Qt.MoveAction


class VisibleLayers:
    """QGIS plugin — shows a filtered view of the Layers panel containing
    only the currently visible, spatial layers.

    Architecture: a plain QTreeView shares the same QgsLayerTreeModel as the
    main Layers panel.  Invisible / non-spatial rows are hidden with
    setRowHidden(), which is per-view and does not touch the source model.
    Because the model is shared, checkbox changes propagate instantly to the
    main Layers panel and vice-versa, and every icon / legend / group feature
    comes for free.
    """

    def __init__(self, iface_):
        self.iface = iface_
        self.action = None
        self.dock = None
        self.tree_view = None       # QTreeView backed by shared QgsLayerTreeModel
        self._src_model = None      # QgsLayerTreeModel from iface.layerTreeView()
        self.button = None
        self.dock_is_open = False
        self.auto_refresh_enabled = False
        self.act_toggle_auto = None
        self._auto_timer = None
        self._action_added_to_menu = False
        self._first_show = True     # expand all only on the very first open

    # ── helpers ────────────────────────────────────────────────────────────

    def _node_at(self, idx):
        """Return the QgsLayerTreeNode for *idx*, or None (e.g. legend row)."""
        if not idx.isValid() or self._src_model is None:
            return None
        try:
            return self._src_model.index2node(idx)
        except Exception:
            return None

    def _group_has_visible_content(self, group_node):
        """True if *group_node* contains at least one visible, spatial layer."""
        for child in group_node.children():
            if isinstance(child, QgsLayerTreeLayer):
                if child.isVisible():
                    layer = child.layer()
                    nonspatial = isinstance(layer, QgsVectorLayer) and not layer.isSpatial()
                    if layer and not nonspatial:
                        return True
            elif isinstance(child, QgsLayerTreeGroup):
                if child.isVisible() and self._group_has_visible_content(child):
                    return True
        return False

    def _should_hide(self, node):
        """True if the row for *node* should be hidden in the VL panel."""
        if node is None:
            return False  # Legend pseudo-node — always visible
        if isinstance(node, QgsLayerTreeLayer):
            if not node.isVisible():
                return True
            layer = node.layer()
            if layer is None:
                return True
            if isinstance(layer, QgsVectorLayer) and not layer.isSpatial():
                return True
            return False
        if isinstance(node, QgsLayerTreeGroup):
            if not node.isVisible():
                return True
            return not self._group_has_visible_content(node)
        return False

    def _hide_rows(self, parent):
        """Recursively hide/show rows to match current layer visibility."""
        if self.tree_view is None or self._src_model is None:
            return
        for row in range(self._src_model.rowCount(parent)):
            idx = self._src_model.index(row, 0, parent)
            node = self._node_at(idx)
            hide = self._should_hide(node)
            self.tree_view.setRowHidden(row, parent, hide)
            if not hide:
                self._hide_rows(idx)  # Only recurse into visible rows

    def _refresh_hidden(self):
        """Re-apply the visibility filter.  Does NOT touch expand state so that
        drag-and-drop and auto-refresh do not collapse/expand nodes the user
        has deliberately arranged.  expandAll() is called only on first open
        and after a project load (see toggle_dock / _on_project_loaded)."""
        if self.tree_view is None or self._src_model is None:
            return
        self._hide_rows(QModelIndex())

    def _set_action_icon(self, filename, theme_fallback):
        icon_path = os.path.join(os.path.dirname(__file__), "icons", filename)
        icon = QIcon(icon_path)
        if icon.isNull():
            icon = QIcon.fromTheme(theme_fallback)
        self.action.setIcon(icon)
        if self.button:
            self.button.setIcon(icon)

    # ── initGui / unload ──────────────────────────────────────────────────

    def initGui(self):
        icon_path = os.path.join(os.path.dirname(__file__), "icons", "glasses_on.svg")
        icon = QIcon(icon_path)
        if icon.isNull():
            icon = QIcon.fromTheme("view-visible")

        self.action = QAction(icon, "Visible Layers Panel", self.iface.mainWindow())
        self.action.triggered.connect(self.toggle_dock)
        self._inject_button_in_layer_panel_toolbar()
        self._inject_action_in_layer_panel_menu()

        root = QgsProject.instance().layerTreeRoot()
        root.visibilityChanged.connect(self._on_visibility_changed)
        QgsProject.instance().layerWasAdded.connect(self._on_layer_added)
        QgsProject.instance().layerWillBeRemoved.connect(self._on_any_change)
        QgsProject.instance().readProject.connect(self._on_project_loaded)

    def unload(self):
        root = QgsProject.instance().layerTreeRoot()
        for sig, slot in [
            (root.visibilityChanged, self._on_visibility_changed),
            (QgsProject.instance().layerWasAdded, self._on_layer_added),
            (QgsProject.instance().layerWillBeRemoved, self._on_any_change),
            (QgsProject.instance().readProject, self._on_project_loaded),
        ]:
            try:
                sig.disconnect(slot)
            except Exception:
                pass

        self._disconnect_model_signals()

        if self._auto_timer:
            self._auto_timer.stop()

        if self.action:
            lt_view = self.iface.layerTreeView()
            parent = lt_view.parent() if lt_view else None
            toolbar = parent.findChild(QToolBar) if parent else None
            if toolbar:
                toolbar.removeAction(self.action)
            self.action = None

        if self.dock:
            self.iface.removeDockWidget(self.dock)
            self.dock = None
        if self.button:
            self.button.setParent(None)
            self.button = None
        self.tree_view = None
        self._src_model = None

    # ── toolbar / menu injection ───────────────────────────────────────────

    def _inject_button_in_layer_panel_toolbar(self):
        lt_view = self.iface.layerTreeView()
        parent = lt_view.parent() if lt_view else None
        toolbar = parent.findChild(QToolBar) if parent else None
        if toolbar:
            toolbar.addAction(self.action)
            for widget in toolbar.findChildren(QToolButton):
                if widget.defaultAction() == self.action:
                    self.button = widget
                    break

    def _inject_action_in_layer_panel_menu(self):
        """Schedule the action to be added to the Layers Panel title-bar menu."""
        for delay in (100, 500, 1000, 2000):
            QTimer.singleShot(delay, self._add_action_to_dock_menu)

    def _add_action_to_dock_menu(self):
        if self._action_added_to_menu:
            return
        try:
            main_window = self.iface.mainWindow()
            if not main_window:
                return

            layer_tree_view = self.iface.layerTreeView()
            dock = None

            # Strategy 1: look by known object names / title
            for candidate in main_window.findChildren(QDockWidget):
                name = candidate.objectName()
                if name in ('LayersPanel', 'Layers', 'qgis_layer_tree_dock'):
                    if layer_tree_view and candidate.widget():
                        if layer_tree_view in candidate.widget().findChildren(
                                type(layer_tree_view)):
                            dock = candidate
                            break
                elif 'layer' in candidate.windowTitle().lower():
                    if layer_tree_view and candidate.widget():
                        if layer_tree_view in candidate.widget().findChildren(
                                type(layer_tree_view)):
                            dock = candidate
                            break

            # Strategy 2: walk up from the layer tree view
            if not dock and layer_tree_view:
                widget = layer_tree_view
                for _ in range(10):
                    p = widget.parent()
                    if isinstance(p, QDockWidget):
                        dock = p
                        break
                    if p is None:
                        break
                    widget = p

            if not dock:
                return

            # Find the title-bar options button
            options_button = None
            for btn in dock.findChildren(QToolButton):
                if btn.objectName() == 'qt_dockwidget_options':
                    options_button = btn
                    break
            if not options_button:
                for btn in dock.findChildren(QToolButton):
                    if btn.menu() is not None and btn is not self.button:
                        options_button = btn
                        break

            if not options_button:
                return

            menu = options_button.menu()
            if menu is None:
                menu = QMenu(options_button)
                options_button.setMenu(menu)

            if self.action not in menu.actions():
                if menu.actions():
                    menu.addSeparator()
                menu.addAction(self.action)
                self._action_added_to_menu = True

        except Exception:
            pass

    # ── dock creation / toggle ─────────────────────────────────────────────

    def toggle_dock(self):
        if not self.dock:
            self._create_dock()
        if self.dock_is_open:
            self.dock.hide()
            self._set_action_icon("glasses_on.svg", "view-visible")
            self.dock_is_open = False
        else:
            self._refresh_hidden()
            if self._first_show:
                self.tree_view.expandAll()
                self._first_show = False
            self.dock.show()
            self._set_action_icon("glasses_off.svg", "view-hidden")
            self.dock_is_open = True

    def _create_dock(self):
        # ── Grab the shared model from the main Layers panel ──────────────
        lt_view = self.iface.layerTreeView()
        self._src_model = lt_view.layerTreeModel()

        # ── QTreeView backed by the shared model ──────────────────────────
        self.tree_view = QTreeView()
        self.tree_view.setModel(self._src_model)
        self.tree_view.header().setVisible(False)
        self.tree_view.setIndentation(14)
        self.tree_view.setContextMenuPolicy(ContextMenuPolicy.CustomContextMenu)
        self.tree_view.customContextMenuRequested.connect(self._show_context_menu)
        self.tree_view.doubleClicked.connect(self._on_double_clicked)
        self.tree_view.clicked.connect(self._on_clicked)

        # Drag-and-drop reordering — the shared QgsLayerTreeModel handles the
        # actual move, so reordering here propagates to the Layers panel.
        self.tree_view.setDragEnabled(True)
        self.tree_view.setAcceptDrops(True)
        self.tree_view.setDropIndicatorShown(True)
        self.tree_view.setDragDropMode(DragDrop)
        self.tree_view.setDefaultDropAction(MoveAction)

        # ── Toolbar ───────────────────────────────────────────────────────
        toolbar = QToolBar()
        toolbar.setIconSize(QSize(16, 16))
        toolbar.setStyleSheet("QToolBar { border: none; }")

        refresh_action = QAction(
            QIcon(":/images/themes/default/mActionRefresh.svg"),
            "Refresh", self.iface.mainWindow(),
        )
        refresh_action.triggered.connect(self._refresh_hidden)
        toolbar.addAction(refresh_action)

        icon_off_path = os.path.join(os.path.dirname(__file__), "icons", "mActionOff.svg")
        icon_off = QIcon(icon_off_path)
        if icon_off.isNull():
            icon_off = QIcon.fromTheme("media-playback-stop")
        self.act_toggle_auto = QAction(self.iface.mainWindow())
        self.act_toggle_auto.setIcon(icon_off)
        self.act_toggle_auto.setToolTip("Activate Auto-refresh")
        self.act_toggle_auto.setCheckable(True)
        self.act_toggle_auto.setChecked(False)
        self.act_toggle_auto.triggered.connect(self._toggle_auto_refresh)
        toolbar.addAction(self.act_toggle_auto)

        # ── Layout ────────────────────────────────────────────────────────
        main_widget = QWidget()
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(toolbar)
        layout.addWidget(self.tree_view)
        main_widget.setLayout(layout)

        # ── Dock widget ───────────────────────────────────────────────────
        self.dock = QDockWidget("Visible Layers", self.iface.mainWindow())
        self.dock.setWidget(main_widget)
        self.iface.addDockWidget(DockWidgetArea.LeftDockWidgetArea, self.dock)
        self.dock.visibilityChanged.connect(self._update_dock_state)

        if self.auto_refresh_enabled:
            self._connect_model_signals()

    def _update_dock_state(self, visible):
        self.dock_is_open = visible
        if not visible:
            self._set_action_icon("glasses_on.svg", "view-visible")

    # ── signal handlers ───────────────────────────────────────────────────

    def _on_visibility_changed(self, node):
        if self.dock_is_open and self.auto_refresh_enabled:
            self._schedule_refresh()

    def _on_layer_added(self, *_):
        """Always-on: refresh when a new layer is added to the project.

        Intentionally ignores auto_refresh_enabled — a newly added layer
        should appear in the panel immediately regardless of mode.
        Uses a 100 ms debounce to let QGIS finish adding the layer fully.
        """
        if not self.dock_is_open:
            return
        self._schedule_refresh(delay_ms=100)

    def _on_any_change(self, *_):
        if self.dock_is_open and self.auto_refresh_enabled:
            self._schedule_refresh()

    def _on_model_changed(self, *_):
        if self.dock_is_open and self.auto_refresh_enabled:
            self._schedule_refresh()

    def _on_project_loaded(self):
        if not self.dock_is_open or self.tree_view is None:
            return
        lt_view = self.iface.layerTreeView()
        new_model = lt_view.layerTreeModel()
        if new_model is not self._src_model:
            self._disconnect_model_signals()   # disconnects both always-on and auto-refresh
            self._src_model = new_model
            self.tree_view.setModel(self._src_model)
            if self.auto_refresh_enabled:
                self._connect_model_signals()
        self._refresh_hidden()
        self.tree_view.expandAll()  # fresh project = expand everything once
        self._first_show = False

    def _schedule_refresh(self, delay_ms=60):
        """Debounce rapid-fire changes before calling _refresh_hidden."""
        if self._auto_timer is None:
            self._auto_timer = QTimer(self.iface.mainWindow())
            self._auto_timer.setSingleShot(True)
            self._auto_timer.timeout.connect(self._refresh_hidden)
        self._auto_timer.start(delay_ms)

    # ── model signal connections (used for auto-refresh) ──────────────────

    def _model_signals(self):
        """Signals used only in auto-refresh mode."""
        if self._src_model is None:
            return []
        return [
            self._src_model.rowsRemoved,
            self._src_model.layoutChanged,
            self._src_model.modelReset,
        ]

    def _connect_model_signals(self):
        for sig in self._model_signals():
            try:
                sig.disconnect(self._on_model_changed)
            except Exception:
                pass
            sig.connect(self._on_model_changed)

    def _disconnect_model_signals(self):
        for sig in self._model_signals():
            try:
                sig.disconnect(self._on_model_changed)
            except Exception:
                pass

    # ── auto-refresh toggle ───────────────────────────────────────────────

    def _toggle_auto_refresh(self, checked):
        self.auto_refresh_enabled = bool(checked)

        if self.auto_refresh_enabled:
            icon_name, theme, tooltip = (
                "mActionOn.svg", "media-playback-start", "Deactivate Auto-refresh")
            self._connect_model_signals()
        else:
            icon_name, theme, tooltip = (
                "mActionOff.svg", "media-playback-stop", "Activate Auto-refresh")
            self._disconnect_model_signals()

        icon = QIcon(os.path.join(os.path.dirname(__file__), "icons", icon_name))
        if icon.isNull():
            icon = QIcon.fromTheme(theme)
        self.act_toggle_auto.setIcon(icon)
        self.act_toggle_auto.setToolTip(tooltip)

        self._refresh_hidden()

    # ── interaction handlers ──────────────────────────────────────────────

    def _on_clicked(self, idx):
        node = self._node_at(idx)
        if isinstance(node, QgsLayerTreeLayer):
            layer = node.layer()
            if layer:
                self.iface.setActiveLayer(layer)

    def _on_double_clicked(self, idx):
        node = self._node_at(idx)
        if isinstance(node, QgsLayerTreeLayer):
            layer = node.layer()
            if layer:
                self.iface.showLayerProperties(layer)

    def _show_context_menu(self, pos: QPoint):
        if self.tree_view is None:
            return
        idx = self.tree_view.indexAt(pos)
        if not idx.isValid():
            return
        node = self._node_at(idx)
        lt_view = self.iface.layerTreeView()

        if isinstance(node, QgsLayerTreeLayer):
            layer = node.layer()
            if not layer:
                return
            self.iface.setActiveLayer(layer)
            if lt_view:
                # Sync lt_view's selection so menuProvider knows which layer
                lt_view.setCurrentIndex(idx)
                try:
                    lt_view.setCurrentLayer(layer)
                except Exception:
                    pass
                provider = lt_view.menuProvider()
                if provider:
                    menu = provider.createContextMenu()
                    if menu:
                        menu.exec(self.tree_view.mapToGlobal(pos))
                        return
            # Fallback minimal menu
            menu = QMenu(self.tree_view)
            for act in (self.iface.actionZoomToLayer(),
                        self.iface.actionRenameLayer()):
                if act:
                    menu.addAction(act)
            menu.exec(self.tree_view.mapToGlobal(pos))

        elif isinstance(node, QgsLayerTreeGroup):
            if lt_view:
                lt_view.setCurrentIndex(idx)
                provider = lt_view.menuProvider()
                if provider:
                    menu = provider.createContextMenu()
                    if menu:
                        menu.exec(self.tree_view.mapToGlobal(pos))
                        return
            menu = QMenu(self.tree_view)
            act_expand = QAction("Expand all", menu)
            act_expand.triggered.connect(self.tree_view.expandAll)
            act_collapse = QAction("Collapse all", menu)
            act_collapse.triggered.connect(self.tree_view.collapseAll)
            menu.addAction(act_expand)
            menu.addAction(act_collapse)
            menu.exec(self.tree_view.mapToGlobal(pos))
