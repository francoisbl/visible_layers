from functools import partial
from qgis.PyQt.QtWidgets import (
    QAction, QDockWidget, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget, QToolButton, QToolBar, QMenu
)
from qgis.PyQt.QtGui import QIcon, QPixmap
from qgis.PyQt.QtCore import Qt, QSize, QPoint, QTimer
from qgis.core import QgsLayerTreeLayer, QgsLayerTreeGroup, QgsWkbTypes, QgsProject, QgsVectorLayer
from qgis.utils import iface
import os

try:
    Checked = Qt.CheckState.Checked
    Unchecked = Qt.CheckState.Unchecked
except AttributeError:
    Checked = Qt.Checked
    Unchecked = Qt.Unchecked

try:
    ContextMenuPolicy = Qt.ContextMenuPolicy
    DockWidgetArea = Qt.DockWidgetArea
except AttributeError:
    ContextMenuPolicy = Qt
    DockWidgetArea = Qt

try:
    UserRole = Qt.ItemDataRole.UserRole
    DecorationRole = Qt.ItemDataRole.DecorationRole
except AttributeError:
    UserRole = Qt.UserRole
    DecorationRole = Qt.DecorationRole

try:
    ItemIsEnabled = Qt.ItemFlag.ItemIsEnabled
except AttributeError:
    ItemIsEnabled = Qt.ItemIsEnabled

class VisibleLayers:
    def __init__(self, iface_):
        self.iface = iface_
        self.action = None
        self.dock = None
        self.tree = None
        self.button = None
        self.layer_items = {}
        self.group_items = {}
        self._icon_connections = {}
        self.dock_is_open = False
        self.auto_refresh_enabled = False
        self.act_toggle_auto = None
        self._auto_timer = None
        self._action_added_to_menu = False
        self._options_button = None

    def _node_path(self, group_node: QgsLayerTreeGroup):
        path = []
        n = group_node
        while n and n.parent() is not None:
            path.append(n.name())
            n = n.parent()
        return tuple(reversed(path))

    def _icon_for_layernode(self, layer_id):
        lt_view = self.iface.layerTreeView()
        if not lt_view:
            return None
        model = lt_view.layerTreeModel()
        ltl = QgsProject.instance().layerTreeRoot().findLayer(layer_id)
        if not ltl:
            return None
        try:
            legend_nodes = model.layerLegendNodes(ltl)
            if legend_nodes:
                icon = legend_nodes[0].data(DecorationRole)
                if isinstance(icon, QPixmap):
                    icon = QIcon(icon)
                return icon if isinstance(icon, QIcon) else None
        except Exception:
            pass
        return None

    def initGui(self):
        icon_path = os.path.join(os.path.dirname(__file__), "icons", "glasses_on.svg")
        icon = QIcon(icon_path)
        if icon.isNull():
            icon = QIcon.fromTheme("view-visible")
        
        self.action = QAction(icon, "Visible Layers Panel", self.iface.mainWindow())
        self.action.triggered.connect(self.toggle_dock)
        self.inject_button_in_layer_panel_toolbar()
        self.inject_action_in_layer_panel_menu()

        root = QgsProject.instance().layerTreeRoot()
        root.visibilityChanged.connect(self._on_tree_visibility_changed)
        QgsProject.instance().readProject.connect(self.auto_refresh_on_project_load)

    def unload(self):
        root = QgsProject.instance().layerTreeRoot()
        try:
            root.visibilityChanged.disconnect(self._on_tree_visibility_changed)
        except Exception:
            pass
        try:
            QgsProject.instance().readProject.disconnect(self.auto_refresh_on_project_load)
        except Exception:
            pass

        self._disconnect_icon_updates()
        self._disconnect_project_signals_for_autorefresh()

        if self.dock:
            self.iface.removeDockWidget(self.dock)
            self.dock = None
        if self.button:
            self.button.setParent(None)
            self.button = None

    def inject_button_in_layer_panel_toolbar(self):
        parent = self.iface.layerTreeView().parent()
        toolbar = parent.findChild(QToolBar)
        if toolbar:
            # Use addAction instead of addWidget so it appears in dropdown menu when collapsed
            # The action is already created in initGui with icon and text
            toolbar.addAction(self.action)
            # Keep reference to button for icon updates, but use action for toolbar
            # Find the button that was created by addAction
            for widget in toolbar.findChildren(QToolButton):
                if widget.defaultAction() == self.action:
                    self.button = widget
                    break

    def inject_action_in_layer_panel_menu(self):
        """Add action to Layers Panel dock widget menu so it appears in dropdown when collapsed"""
        # Use a timer to ensure the UI is fully initialized before trying to access the dock
        # Try multiple times as the UI might not be ready immediately
        QTimer.singleShot(100, self._add_action_to_dock_menu)
        QTimer.singleShot(500, self._add_action_to_dock_menu)
        QTimer.singleShot(1000, self._add_action_to_dock_menu)
        QTimer.singleShot(2000, self._add_action_to_dock_menu)
    
    def _add_action_to_dock_menu(self):
        """Add action to Layers Panel dock widget's menu"""
        # Prevent adding the action multiple times
        if self._action_added_to_menu:
            return
        
        try:
            main_window = self.iface.mainWindow()
            if not main_window:
                return
            
            # Method 1: Find dock by objectName (most reliable)
            dock = None
            for candidate_dock in main_window.findChildren(QDockWidget):
                obj_name = candidate_dock.objectName()
                # QGIS Layers Panel might have different object names in different versions
                if obj_name in ('LayersPanel', 'Layers', 'qgis_layer_tree_dock'):
                    # Verify it contains the layer tree view
                    layer_tree_view = self.iface.layerTreeView()
                    if layer_tree_view and candidate_dock.widget():
                        if layer_tree_view in candidate_dock.widget().findChildren(type(layer_tree_view), recursive=True):
                            dock = candidate_dock
                            break
                # Also check by window title
                elif 'layer' in candidate_dock.windowTitle().lower():
                    layer_tree_view = self.iface.layerTreeView()
                    if layer_tree_view and candidate_dock.widget():
                        if layer_tree_view in candidate_dock.widget().findChildren(type(layer_tree_view), recursive=True):
                            dock = candidate_dock
                            break
            
            # Method 2: Find dock by walking up from layer tree view
            if not dock:
                layer_tree_view = self.iface.layerTreeView()
                if layer_tree_view:
                    widget = layer_tree_view
                    max_depth = 10
                    depth = 0
                    while widget and depth < max_depth:
                        parent = widget.parent()
                        if isinstance(parent, QDockWidget):
                            dock = parent
                            break
                        widget = parent
                        depth += 1
            
            if not dock:
                return
            
            # Find the options button in the dock widget's title bar
            # The options button is typically named 'qt_dockwidget_options'
            options_button = None
            
            # Method 1: Find by objectName
            for btn in dock.findChildren(QToolButton):
                if btn.objectName() == 'qt_dockwidget_options':
                    options_button = btn
                    break
            
            # Method 2: Find by looking in title bar widget
            if not options_button:
                title_bar = dock.titleBarWidget()
                if title_bar:
                    for btn in title_bar.findChildren(QToolButton):
                        if btn.objectName() == 'qt_dockwidget_options':
                            options_button = btn
                            break
            
            # Method 3: Find any button with a menu in the dock (likely the options button)
            if not options_button:
                all_buttons = dock.findChildren(QToolButton)
                for btn in all_buttons:
                    # Options button typically has a menu or is in the title bar area
                    if btn.menu() is not None:
                        # Check if it's likely the options button (not our custom button)
                        if btn != self.button:
                            options_button = btn
                            break
            
            # Method 4: Look for buttons in widgets that are direct children of the dock
            # (title bar widgets are often direct children)
            if not options_button:
                for child in dock.children():
                    if isinstance(child, QWidget):
                        for btn in child.findChildren(QToolButton):
                            if btn.menu() is not None and btn != self.button:
                                options_button = btn
                                break
                        if options_button:
                            break
            
            if not options_button:
                return
            
            # Get or create the menu for the options button
            menu = options_button.menu()
            if menu is None:
                menu = QMenu(options_button)
                options_button.setMenu(menu)
            
            # Add the action to the menu if it's not already there
            if self.action not in menu.actions():
                if menu.actions():
                    menu.addSeparator()
                menu.addAction(self.action)
                self._action_added_to_menu = True
                self._options_button = options_button
                    
        except Exception as e:
            # If we can't add to menu, that's okay - toolbar button will still work when expanded
            # Print for debugging if needed
            pass

    def toggle_dock(self):
        if not self.dock:
            self.create_dock()
        if self.dock_is_open:
            self.dock.hide()
            icon_path = os.path.join(os.path.dirname(__file__), "icons", "glasses_on.svg")
            icon = QIcon(icon_path)
            if icon.isNull():
                icon = QIcon.fromTheme("view-visible")
            self.action.setIcon(icon)
            # Also update button if it exists (for visual consistency)
            if self.button:
                self.button.setIcon(icon)
            self.dock_is_open = False
        else:
            self.update_visible_tree()
            self.dock.show()
            icon_path = os.path.join(os.path.dirname(__file__), "icons", "glasses_off.svg")
            icon = QIcon(icon_path)
            if icon.isNull():
                icon = QIcon.fromTheme("view-hidden")
            self.action.setIcon(icon)
            # Also update button if it exists (for visual consistency)
            if self.button:
                self.button.setIcon(icon)
            self.dock_is_open = True

    def create_dock(self):
        self.dock = QDockWidget("Visible Layers", self.iface.mainWindow())
        main_widget = QWidget()
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        toolbar = QToolBar()
        toolbar.setIconSize(QSize(16, 16))
        toolbar.setStyleSheet("QToolBar { border: none; }")
        refresh_action = QAction(QIcon(":/images/themes/default/mActionRefresh.svg"),
                                 "Refresh visible layers", self.iface.mainWindow())
        refresh_action.triggered.connect(self.update_visible_tree)
        toolbar.addAction(refresh_action)

        self.act_toggle_auto = QAction(self.iface.mainWindow())
        icon_off = QIcon(os.path.join(os.path.dirname(__file__), "icons", "mActionOff.svg"))
        if icon_off.isNull():
            icon_off = QIcon.fromTheme("media-playback-stop")
        self.act_toggle_auto.setIcon(icon_off)
        self.act_toggle_auto.setToolTip("Activate Auto-refresh")
        self.act_toggle_auto.setCheckable(True)
        self.act_toggle_auto.setChecked(False)
        self.act_toggle_auto.triggered.connect(self._toggle_auto_refresh)

        toolbar.addAction(self.act_toggle_auto)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(14)
        self.tree.itemChanged.connect(self._on_item_changed)
        self.tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.tree.itemClicked.connect(self._on_item_clicked)
        self.tree.setContextMenuPolicy(ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._show_context_menu)

        layout.addWidget(toolbar)
        layout.addWidget(self.tree)
        main_widget.setLayout(layout)

        self.dock.setWidget(main_widget)
        self.iface.addDockWidget(DockWidgetArea.LeftDockWidgetArea, self.dock)
        self.dock.visibilityChanged.connect(self._update_dock_state)

    def _update_dock_state(self, visible):
        self.dock_is_open = visible
        if not visible:
            icon_path = os.path.join(os.path.dirname(__file__), "icons", "glasses_on.svg")
            icon = QIcon(icon_path)
            if icon.isNull():
                icon = QIcon.fromTheme("view-visible")
            self.action.setIcon(icon)
            # Also update button if it exists (for visual consistency)
            if self.button:
                self.button.setIcon(icon)

    def update_visible_tree(self):
        if self.tree is None:
            return
        self.tree.blockSignals(True)
        self._disconnect_icon_updates()
        self.tree.clear()
        self.layer_items.clear()
        self.group_items.clear()

        root = QgsProject.instance().layerTreeRoot()

        def has_visible_descendant(g):
            if not g.isVisible():
                return False
            for n in g.children():
                if isinstance(n, QgsLayerTreeLayer):
                    if n.isVisible():
                        lyr = n.layer()
                        from qgis.core import QgsVectorLayer, QgsWkbTypes
                        if isinstance(lyr, QgsVectorLayer):
                            if not lyr.isSpatial() or lyr.geometryType() == QgsWkbTypes.NoGeometry:
                                continue
                        return True
                elif isinstance(n, QgsLayerTreeGroup):
                    if has_visible_descendant(n):
                        return True
            return False

        def add_children(parent_qt_item, parent_node):
            for child in parent_node.children():
                if isinstance(child, QgsLayerTreeLayer):
                    if not child.isVisible():
                        continue
                    layer = child.layer()
                    from qgis.core import QgsVectorLayer, QgsWkbTypes
                    if isinstance(layer, QgsVectorLayer):
                        if not layer.isSpatial() or layer.geometryType() == QgsWkbTypes.NoGeometry:
                            continue

                    it = QTreeWidgetItem(parent_qt_item, [layer.name()])
                    it.setFlags(self._flags_for_item(it.flags(), is_group=False))
                    if not self.auto_refresh_enabled:
                        it.setCheckState(0, Qt.CheckState.Checked)
                    it.setData(0, UserRole, ("layer", layer.id()))
                    icon = self._icon_for_layernode(layer.id())
                    if icon:
                        it.setIcon(0, icon)
                    self.layer_items[layer.id()] = it
                    self._connect_icon_updates(layer)

                elif isinstance(child, QgsLayerTreeGroup):
                    if not has_visible_descendant(child):
                        continue

                    path = self._node_path(child)
                    git = QTreeWidgetItem(parent_qt_item, [child.name()])
                    git.setFlags(self._flags_for_item(ItemIsEnabled, is_group=True))
                    if not self.auto_refresh_enabled:
                        git.setCheckState(0, Qt.CheckState.Checked)
                    git.setData(0, UserRole, ("group", path))
                    self.group_items[path] = git

                    add_children(git, child)

        add_children(self.tree.invisibleRootItem(), root)

        self.tree.expandAll()
        self.tree.blockSignals(False)

    def _on_item_clicked(self, item, column):
        if not item:
            return
        kind, val = item.data(0, UserRole) or (None, None)
        if kind == "layer":
            layer = QgsProject.instance().mapLayer(val)
            if layer:
                self.iface.setActiveLayer(layer)

    def _on_item_double_clicked(self, item, column):
        if self.auto_refresh_enabled:
            return         
        if not item:
            return
        kind, val = item.data(0, UserRole) or (None, None)
        if kind == "layer":
            layer = QgsProject.instance().mapLayer(val)
            if layer:
                self.iface.showLayerProperties(layer)

    def _on_item_changed(self, item, column):
        if not item:
            return
        kind, val = item.data(0, UserRole) or (None, None)
        if kind == "layer":
            layer_id = val
            node = QgsProject.instance().layerTreeRoot().findLayer(layer_id)
            if node:
                node.setItemVisibilityChecked(item.checkState(0) == Checked)
        elif kind == "group":
            root = QgsProject.instance().layerTreeRoot()
            g = root
            for name in val or ():
                if not name:
                    continue
                nxt = next((gg for gg in g.findGroups() if gg.name() == name), None)
                if nxt is None:
                    g = None
                    break
                g = nxt
            if g is not None:
                vis = (item.checkState(0) == Checked)
                try:
                    g.setItemVisibilityCheckedRecursive(vis)
                except Exception:
                    g.setItemVisibilityChecked(vis)


    def _show_context_menu(self, pos: QPoint):
        it = self.tree.itemAt(pos)
        if not it:
            return
        kind, val = it.data(0, UserRole) or (None, None)

        if kind == "layer":
            layer = QgsProject.instance().mapLayer(val)
            if not layer:
                return
            self.iface.setActiveLayer(layer)
            lt_view = self.iface.layerTreeView()
            if not lt_view:
                return
            lt_view.setCurrentLayer(layer)

            provider = lt_view.menuProvider()
            menu = provider.createContextMenu() if provider else None
            if menu:
                menu.exec_(self.tree.mapToGlobal(pos))
            else:
                menu = QMenu(self.tree)
                if self.iface.actionZoomToLayer():
                    menu.addAction(self.iface.actionZoomToLayer())
                if self.iface.actionRenameLayer():
                    menu.addAction(self.iface.actionRenameLayer())
                menu.exec_(self.tree.mapToGlobal(pos))

        elif kind == "group":
            menu = QMenu(self.tree)
            act_toggle = QAction("Toggle visibility", menu)
            act_expand = QAction("Expand", menu)
            act_collapse = QAction("Collapse", menu)

            def _toggle_group():
                state = it.checkState(0)
                it.setCheckState(0, Unchecked if state == Checked else Checked)

            act_toggle.triggered.connect(_toggle_group)
            act_expand.triggered.connect(lambda: self.tree.expandItem(it))
            act_collapse.triggered.connect(lambda: self.tree.collapseItem(it))
            menu.addAction(act_toggle)
            menu.addSeparator()
            menu.addAction(act_expand)
            menu.addAction(act_collapse)
            menu.exec_(self.tree.mapToGlobal(pos))

    def _on_tree_visibility_changed(self, node):
        if node is None or not self.dock_is_open or self.tree is None:
            return

        def _set_check_safe(item, checked):
            if not item:
                return
            self.tree.blockSignals(True)
            try:
                item.setCheckState(0, Checked if checked else Unchecked)
            finally:
                self.tree.blockSignals(False)

        from qgis.core import QgsLayerTreeLayer, QgsLayerTreeGroup

        if isinstance(node, QgsLayerTreeLayer):
            it = self.layer_items.get(node.layerId())
            _set_check_safe(it, node.isVisible())

        elif isinstance(node, QgsLayerTreeGroup):
            path = []
            g = node
            while g and g.parent() is not None:
                path.append(g.name())
                g = g.parent()
            path = tuple(reversed(path))
            it = self.group_items.get(path)
            _set_check_safe(it, node.isVisible())

    def auto_refresh_on_project_load(self):
        if self.dock_is_open:
            self.update_visible_tree()

    def _connect_icon_updates(self, layer):
        lid = layer.id()
        if lid in self._icon_connections:
            return
        callbacks = []
        if hasattr(layer, "styleChanged"):
            cb = partial(self._refresh_item_icon, layer)
            layer.styleChanged.connect(cb)
            callbacks.append(("styleChanged", cb))
        if hasattr(layer, "rendererChanged"):
            cb = partial(self._refresh_item_icon, layer)
            layer.rendererChanged.connect(cb)
            callbacks.append(("rendererChanged", cb))
        if hasattr(layer, "repaintRequested"):
            cb = partial(self._refresh_item_icon, layer)
            layer.repaintRequested.connect(cb)
            callbacks.append(("repaintRequested", cb))
        self._icon_connections[lid] = (layer, callbacks)

    def _disconnect_icon_updates(self):
        for lid, (layer, callbacks) in list(self._icon_connections.items()):
            for sig_name, cb in callbacks:
                try:
                    getattr(layer, sig_name).disconnect(cb)
                except Exception:
                    pass
        self._icon_connections.clear()

    def _refresh_item_icon(self, layer):
        item = self.layer_items.get(layer.id())
        if not item:
            return
        icon = self._icon_for_layernode(layer.id())
        if icon:
            item.setIcon(0, icon)

    def _toggle_auto_refresh(self, checked):
        self.auto_refresh_enabled = bool(checked)

        if self.act_toggle_auto:
            if self.auto_refresh_enabled:
                icon_on = QIcon(os.path.join(os.path.dirname(__file__), "icons", "mActionOn.svg"))
                if icon_on.isNull():
                    icon_on = QIcon.fromTheme("media-playback-start")
                self.act_toggle_auto.setIcon(icon_on)
                self.act_toggle_auto.setToolTip("Desactivate Auto-refresh")
            else:
                icon_off = QIcon(os.path.join(os.path.dirname(__file__), "icons", "mActionOff.svg"))
                if icon_off.isNull():
                    icon_off = QIcon.fromTheme("media-playback-stop")
                self.act_toggle_auto.setIcon(icon_off)
                self.act_toggle_auto.setToolTip("Activate Auto-refresh")

        if self.auto_refresh_enabled:
            self._connect_project_signals_for_autorefresh()
        else:
            self._disconnect_project_signals_for_autorefresh()

        self.update_visible_tree()


    def _connect_project_signals_for_autorefresh(self):
        root = QgsProject.instance().layerTreeRoot()
        try: root.visibilityChanged.disconnect(self._on_tree_visibility_changed_autorefresh)
        except Exception: pass
        root.visibilityChanged.connect(self._on_tree_visibility_changed_autorefresh)

        try: QgsProject.instance().layerWasAdded.disconnect(self._on_any_change_autorefresh)
        except Exception: pass
        QgsProject.instance().layerWasAdded.connect(self._on_any_change_autorefresh)

        try: QgsProject.instance().layerWillBeRemoved.disconnect(self._on_any_change_autorefresh)
        except Exception: pass
        QgsProject.instance().layerWillBeRemoved.connect(self._on_any_change_autorefresh)

        lt_view = self.iface.layerTreeView()
        self._lt_model = lt_view.layerTreeModel() if lt_view else None

        if self._lt_model:
            try: self._lt_model.rowsMoved.disconnect(self._on_model_changed_autorefresh)
            except Exception: pass
            try: self._lt_model.rowsInserted.disconnect(self._on_model_changed_autorefresh)
            except Exception: pass
            try: self._lt_model.rowsRemoved.disconnect(self._on_model_changed_autorefresh)
            except Exception: pass
            try: self._lt_model.layoutChanged.disconnect(self._on_model_changed_autorefresh)
            except Exception: pass
            try: self._lt_model.modelReset.disconnect(self._on_model_changed_autorefresh)
            except Exception: pass

            self._lt_model.rowsMoved.connect(self._on_model_changed_autorefresh)
            self._lt_model.rowsInserted.connect(self._on_model_changed_autorefresh)
            self._lt_model.rowsRemoved.connect(self._on_model_changed_autorefresh)
            self._lt_model.layoutChanged.connect(self._on_model_changed_autorefresh)
            self._lt_model.modelReset.connect(self._on_model_changed_autorefresh)

    def _on_model_changed_autorefresh(self, *args, **kwargs):
        self._schedule_autorefresh(60)

    def _disconnect_project_signals_for_autorefresh(self):
        root = QgsProject.instance().layerTreeRoot()
        try: root.visibilityChanged.disconnect(self._on_tree_visibility_changed_autorefresh)
        except Exception: pass
        try: QgsProject.instance().layerWasAdded.disconnect(self._on_any_change_autorefresh)
        except Exception: pass
        try: QgsProject.instance().layerWillBeRemoved.disconnect(self._on_any_change_autorefresh)
        except Exception: pass

        if hasattr(self, "_lt_model") and self._lt_model:
            try: self._lt_model.rowsMoved.disconnect(self._on_model_changed_autorefresh)
            except Exception: pass
            try: self._lt_model.rowsInserted.disconnect(self._on_model_changed_autorefresh)
            except Exception: pass
            try: self._lt_model.rowsRemoved.disconnect(self._on_model_changed_autorefresh)
            except Exception: pass
            try: self._lt_model.layoutChanged.disconnect(self._on_model_changed_autorefresh)
            except Exception: pass
            try: self._lt_model.modelReset.disconnect(self._on_model_changed_autorefresh)
            except Exception: pass
        self._lt_model = None

        if self._auto_timer and self._auto_timer.isActive():
            self._auto_timer.stop()


    def _on_tree_visibility_changed_autorefresh(self, node):
        if not self.dock_is_open or self.tree is None or not self.auto_refresh_enabled:
            return
        self.update_visible_tree()


    def _on_any_change_autorefresh(self, *_args, **_kwargs):
        if not self.dock_is_open or self.tree is None or not self.auto_refresh_enabled:
            return
        self.update_visible_tree()

    def _flags_for_item(self, base_flags, is_group=False):
        try:
            # PyQt6 (QGIS 4)
            flags = base_flags | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled
            if not self.auto_refresh_enabled:
                flags |= Qt.ItemFlag.ItemIsUserCheckable
        except AttributeError:
            # PyQt5 (QGIS 3)
            flags = base_flags | Qt.ItemIsSelectable | Qt.ItemIsEnabled
            if not self.auto_refresh_enabled:
                flags |= Qt.ItemIsUserCheckable
        return flags

    def _schedule_autorefresh(self, delay_ms=60):
        if not self.auto_refresh_enabled or not self.dock_is_open or self.tree is None:
            return
        if self._auto_timer is None:
            self._auto_timer = QTimer(self.iface.mainWindow())
            self._auto_timer.setSingleShot(True)
            self._auto_timer.timeout.connect(self.update_visible_tree)
        self._auto_timer.start(delay_ms)
