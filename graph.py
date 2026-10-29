"""ATLAS knowledge graph canvas, written entirely in Python/PySide6.

Contains ONLY the canvas: no sidebar, labels outside nodes, controls, or fake data.
Place AtlasGraph() inside any PySide6 layout. AtlasDemo is an alias for
compatibility with earlier ATLAS integrations.

Public API:
    create_node(name, color=None, group="", connections=None, ...)
    add_node({"id": ..., "name": ..., "color": ..., ...})
    add_edge({"from": node_id, "to": node_id, ...})
    connect_nodes(from_id, to_id, relation="related_to", color=None)
    load_graph({"nodes": [...], "edges": [...]})
    get_graph_data() -> JSON-serializable dict
    focus_node(node_id)

Signals:
    node_selected(str): emitted when a node is clicked
    graph_changed(): emitted after editing or moving graph items

This module never writes your project JSON. Your main.py handles saving.
"""

import math
import sys
import time
import uuid
from dataclasses import dataclass, field

from PySide6 import QtCore, QtGui, QtWidgets

# Node colors are UI styling, not project data.
NODE_COLORS = {
    "project": "#69B8FF", "hub": "#69B8FF", "center": "#9CD9FF",
    "task": "#49E6D1", "note": "#BA8CFF", "decision": "#FFBB76",
    "file": "#889FFF", "commit": "#FD85C8", "resource": "#FFBB76",
}


def tint(color: str, alpha: int) -> QtGui.QColor:
    result = QtGui.QColor(color)
    result.setAlpha(max(0, min(255, alpha)))
    return result


@dataclass
class DataNode:
    ident: str
    title: str
    group: str
    x: float
    y: float
    radius: float
    kind: str = "note"
    description: str = ""
    color: str = ""  # Custom color, otherwise use the type palette.
    metadata: dict = field(default_factory=dict)
    neighbors: list[str] = field(default_factory=list)

    @property
    def degree(self):
        return len(self.neighbors)


def node_color(node: DataNode) -> str:
    return node.color or NODE_COLORS.get(node.kind, "#889FFF")


class EdgeLine(QtWidgets.QGraphicsLineItem):
    """A sharp, vector-rendered edge; separate from the soft cached glow."""
    def __init__(self, a, b, max_degree, color=None):
        super().__init__()
        self.a, self.b = a, b
        self.max_degree = max_degree
        self.color = color
        self.highlighted = False
        self.setZValue(-3)
        self.setAcceptedMouseButtons(QtCore.Qt.MouseButton.NoButton)
        self.update_line()

    def update_line(self):
        pa, pb = self.a.pos(), self.b.pos()
        diff = pb - pa
        length = math.hypot(diff.x(), diff.y())
        if length < 1:
            return
        unit = diff / length
        start = pa + unit * self.a.data.radius
        end = pb - unit * self.b.data.radius
        self.setLine(QtCore.QLineF(start, end))
        self._update_pen(start, end)

    def _update_pen(self, start, end):
        if self.a.data.degree <= self.b.data.degree:
            low, high = start, end
            popular = self.b.data
        else:
            low, high = end, start
            popular = self.a.data
        power = (popular.degree / self.max_degree) ** .70
        color = self.color or node_color(popular)
        gradient = QtGui.QLinearGradient(low, high)
        boost = 1.0 if self.highlighted else 0.0
        gradient.setColorAt(0.0, tint(color, int(43 + boost*25)))
        gradient.setColorAt(0.48, tint(color, int(48 + power*22 + boost*35)))
        gradient.setColorAt(0.78, tint(color, int(67 + power*77 + boost*45)))
        gradient.setColorAt(1.0, tint("#E9F7FF" if power > .55 else color,
                                       int(min(255, 80 + power*154 + boost*28))))
        pen = QtGui.QPen(QtGui.QBrush(gradient), 2.1 if self.highlighted else 1.35)
        pen.setCapStyle(QtCore.Qt.PenCapStyle.RoundCap)
        self.setPen(pen)

    def set_highlighted(self, value):
        if value != self.highlighted:
            self.highlighted = value
            self.update_line()


class GraphNode(QtWidgets.QGraphicsObject):
    def __init__(self, data, scene_owner):
        super().__init__()
        self.data = data
        self.owner = scene_owner
        self.attached_edges = []
        self.active = False
        self.is_hovered = False
        r = data.radius
        self._rect = QtCore.QRectF(-r-17, -r-17, 2*(r+17), 2*(r+17))
        self.setPos(data.x, data.y)
        self.setToolTip(data.description)
        self.setZValue(5 if data.kind not in ("hub", "project", "center") else 7)
        self.setAcceptHoverEvents(True)
        self.setFlags(QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable |
                      QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges)

        # QGraphicsSimpleTextItem remains VECTOR text, sharp even at 300% zoom.
        label = QtWidgets.QGraphicsSimpleTextItem(data.title, self)
        label.setBrush(QtGui.QBrush(QtGui.QColor("#E5EFFF" if data.kind in ("hub", "project", "center") else "#A6B9D6")))
        font = QtGui.QFont("Sans Serif", 11 if data.kind in ("hub", "project", "center") else 9)
        font.setWeight(QtGui.QFont.Weight.DemiBold if data.kind in ("hub", "project", "center") else QtGui.QFont.Weight.Medium)
        label.setFont(font)
        label.setPos(-label.boundingRect().width()*.5, r + 11)
        label.setAcceptedMouseButtons(QtCore.Qt.MouseButton.NoButton)
        self.label = label

    def boundingRect(self):
        return self._rect

    def paint(self, painter, option, widget=None):
        r = self.data.radius
        color = QtGui.QColor(node_color(self.data))
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        if self.active or self.is_hovered:
            ring = QtGui.QColor("#EFFBFF") if self.active else color.lighter(170)
            ring.setAlpha(225 if self.active else 155)
            painter.setPen(QtGui.QPen(ring, 1.5))
            painter.drawEllipse(QtCore.QPointF(), r+8, r+8)
        if self.data.kind in ("hub", "project", "center"):
            painter.setPen(QtGui.QPen(tint(color.name(), 115), 1.0))
            painter.drawEllipse(QtCore.QPointF(), r+11, r+11)

        gradient = QtGui.QRadialGradient(-r*.28, -r*.35, r*1.9)
        gradient.setColorAt(0., color.lighter(185))
        gradient.setColorAt(.4, color)
        gradient.setColorAt(1., QtGui.QColor("#111D33"))
        painter.setPen(QtGui.QPen(color.lighter(145), 1.3))
        painter.setBrush(QtGui.QBrush(gradient))
        painter.drawEllipse(QtCore.QPointF(), r, r)
        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        painter.setBrush(QtGui.QColor("#F1FAFF"))
        painter.drawEllipse(QtCore.QPointF(), max(1.4, r*.18), max(1.4, r*.18))

    def itemChange(self, change, value):
        if change == QtWidgets.QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            self.data.x, self.data.y = self.pos().x(), self.pos().y()
            if hasattr(self, "_drag_started") and not self._drag_started:
                self._drag_started = True
                self.owner.drag_started()
            for edge in self.attached_edges:
                edge.update_line()
        return super().itemChange(change, value)

    def hoverEnterEvent(self, event):
        self.is_hovered = True
        self.update()
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self.is_hovered = False
        self.update()
        QtWidgets.QApplication.restoreOverrideCursor()
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event):
        self._press_scene_position = event.scenePos()
        self._drag_started = False
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        dragged = QtCore.QLineF(self._press_scene_position, event.scenePos()).length() > 5
        super().mouseReleaseEvent(event)
        if getattr(self, "_drag_started", False):
            self.owner.drag_finished()
        if not dragged:
            self.owner.node_clicked(self.data.ident)


class KnowledgeScene(QtWidgets.QGraphicsScene):
    """An initially empty scene that accepts graph records on demand."""

    def __init__(self):
        super().__init__()
        self.on_select = None
        self.on_node_click = None
        self.on_drag_start = None
        self.on_drag_end = None
        self.show_glow = True
        self.data_nodes = []
        self.data_by_id = {}
        self.links = []
        self.edge_metadata = {}
        self.max_degree = 1
        self.node_items = {}
        self.edge_items = []
        self.setSceneRect(QtCore.QRectF(-850, -550, 1700, 1100))
        self.glow_layer = QtWidgets.QGraphicsPixmapItem()
        self.glow_layer.setZValue(-10)
        self.glow_layer.setAcceptedMouseButtons(QtCore.Qt.MouseButton.NoButton)
        self.addItem(self.glow_layer)

    def clear_graph(self):
        self.clear()
        self.data_nodes = []
        self.data_by_id = {}
        self.links = []
        self.edge_metadata = {}
        self.max_degree = 1
        self.node_items = {}
        self.edge_items = []
        self.setSceneRect(QtCore.QRectF(-850, -550, 1700, 1100))
        self.glow_layer = QtWidgets.QGraphicsPixmapItem()
        self.glow_layer.setZValue(-10)
        self.glow_layer.setAcceptedMouseButtons(QtCore.Qt.MouseButton.NoButton)
        self.addItem(self.glow_layer)
        if self.on_select:
            self.on_select(None)

    def _fit_bounds(self):
        if not self.data_nodes:
            self.setSceneRect(QtCore.QRectF(-850, -550, 1700, 1100))
            return
        min_x = min(n.x - n.radius for n in self.data_nodes) - 220
        max_x = max(n.x + n.radius for n in self.data_nodes) + 220
        min_y = min(n.y - n.radius for n in self.data_nodes) - 220
        max_y = max(n.y + n.radius for n in self.data_nodes) + 220
        self.setSceneRect(QtCore.QRectF(min_x, min_y, max_x - min_x, max_y - min_y))

    def _refresh_edges(self):
        self.max_degree = max((n.degree for n in self.data_nodes), default=1)
        self.max_degree = max(1, self.max_degree)
        for edge in self.edge_items:
            edge.max_degree = self.max_degree
            edge.update_line()

    def add_node(self, record, refresh=True):
        """Add a node from e.g. {id, title, type, description, x, y}.

        If positions are omitted, place new nodes in a loose spiral.
        """
        ident = str(record["id"])
        if ident in self.data_by_id:
            raise ValueError(f"Duplicate node ID: {ident}")
        index = len(self.data_nodes)
        angle = index * 2.399963229728653  # Golden angle, for reasonable default spacing.
        dist = 92 * math.sqrt(index)
        kind = str(record.get("type", "note"))
        x = float(record.get("x", math.cos(angle) * dist))
        y = float(record.get("y", math.sin(angle) * dist))
        if not (math.isfinite(x) and math.isfinite(y)):
            raise ValueError("Node positions must be finite numbers")
        radius = float(record.get("radius", 19 if kind in ("hub", "project", "center") else 10))
        if not (math.isfinite(radius) and 1 <= radius <= 100):
            raise ValueError("Node radius must be between 1 and 100")
        custom_color = record.get("color")
        if custom_color is not None and not QtGui.QColor(str(custom_color)).isValid():
            raise ValueError(f"Invalid node color: {custom_color}")
        data = DataNode(
            ident=ident, title=str(record.get("title", record.get("name", "Untitled"))),
            group=str(record.get("group", "")), x=x, y=y, radius=radius,
            kind=kind, description=str(record.get("description", "")),
            color=str(custom_color) if custom_color is not None else "",
            metadata=dict(record.get("metadata") or {}),
        )
        item = GraphNode(data, self)
        self.data_nodes.append(data)
        self.data_by_id[ident] = data
        self.node_items[ident] = item
        self.addItem(item)
        if refresh:
            self._fit_bounds()
            self.refresh_glow()
        return data

    def add_edge(self, record, refresh=True):
        """Add a relationship from e.g. {from: node_id, to: node_id, relation: ...}."""
        a, b = str(record["from"]), str(record["to"])
        if a == b:
            raise ValueError("Self-connections aren't supported yet")
        if a not in self.data_by_id or b not in self.data_by_id:
            raise ValueError(f"Connection references missing node: {a} → {b}")
        key = tuple(sorted((a, b)))
        if key in self.edge_metadata:
            return  # An identical connection already exists.
        custom_color = record.get("color")
        if custom_color is not None and not QtGui.QColor(str(custom_color)).isValid():
            raise ValueError(f"Invalid edge color: {custom_color}")
        self.links.append(key)
        self.edge_metadata[key] = {
            "from": a, "to": b,
            "relation": str(record.get("relation", "related_to")),
            "color": str(custom_color) if custom_color is not None else None,
            "metadata": dict(record.get("metadata") or {}),
        }
        self.data_by_id[a].neighbors.append(b)
        self.data_by_id[b].neighbors.append(a)
        edge = EdgeLine(self.node_items[a], self.node_items[b], self.max_degree,
                        color=self.edge_metadata[key]["color"])
        self.addItem(edge)
        self.node_items[a].attached_edges.append(edge)
        self.node_items[b].attached_edges.append(edge)
        self.edge_items.append(edge)
        if refresh:
            self._refresh_edges()
            self.refresh_glow()

    def load_graph(self, graph):
        """Replace current graph with a project's {nodes: [], edges: []} data."""
        self.clear_graph()
        for record in graph.get("nodes", []):
            self.add_node(record, refresh=False)
        for record in graph.get("edges", []):
            self.add_edge(record, refresh=False)
        self._fit_bounds()
        self._refresh_edges()
        self.refresh_glow()

    def to_dict(self):
        """Return current graph data, including node positions after dragging."""
        return {
            "nodes": [
                {"id": n.ident, "name": n.title, "type": n.kind,
                 "group": n.group, "description": n.description,
                 "color": n.color or None, "metadata": dict(n.metadata),
                 "x": n.x, "y": n.y, "radius": n.radius}
                for n in self.data_nodes
            ],
            "edges": [dict(self.edge_metadata[key]) for key in self.links],
        }

    def refresh_glow(self):
        """One-time static bloom render. No per-frame blurry text or nodes."""
        if not self.data_nodes:
            self.glow_layer.setPixmap(QtGui.QPixmap())
            return
        rect = self.sceneRect()
        # Cap the cache resolution to prevent massive GPU/CPU memory use.
        resolution = min(1.0, 2048 / max(1.0, rect.width()),
                         2048 / max(1.0, rect.height()))
        width = max(1, math.ceil(rect.width() * resolution))
        height = max(1, math.ceil(rect.height() * resolution))
        image = QtGui.QImage(width, height, QtGui.QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(QtCore.Qt.GlobalColor.transparent)
        p = QtGui.QPainter(image)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        p.scale(resolution, resolution)
        p.translate(-rect.x(), -rect.y())
        p.setPen(QtCore.Qt.PenStyle.NoPen)

        # Several subtle translucent passes give a bloom-like effect while the
        # sharp vectors above remain crisp at every zoom level.
        for a, b in self.links:
            aa, bb = self.node_items[a], self.node_items[b]
            if aa.data.degree <= bb.data.degree:
                low, high = aa, bb
            else:
                low, high = bb, aa
            delta = high.pos() - low.pos()
            length = math.hypot(delta.x(), delta.y())
            if length < 1:
                continue
            direction = delta / length
            start = low.pos() + direction * low.data.radius
            end = high.pos() - direction * high.data.radius
            power = (high.data.degree / self.max_degree) ** .70
            col = self.edge_metadata[tuple(sorted((a, b)))].get("color") or node_color(high.data)
            for thickness, multiplier in ((22., .35), (9., .85)):
                gradient = QtGui.QLinearGradient(start, end)
                gradient.setColorAt(0., tint(col, int(2*multiplier)))
                gradient.setColorAt(.52, tint(col, int((3+power*6)*multiplier)))
                gradient.setColorAt(.8, tint(col, int((8+power*20)*multiplier)))
                gradient.setColorAt(1., tint(col, int((13+power*55)*multiplier)))
                pen = QtGui.QPen(QtGui.QBrush(gradient), thickness)
                pen.setCapStyle(QtCore.Qt.PenCapStyle.RoundCap)
                p.setPen(pen)
                p.drawLine(start, end)

        p.setPen(QtCore.Qt.PenStyle.NoPen)
        for n in self.data_nodes:
            point = self.node_items[n.ident].pos()
            power = (n.degree / self.max_degree) ** .58
            radius = 42 + 76*power if n.kind in ("hub", "project", "center") else 28 + 25*power
            color = node_color(n)
            grad = QtGui.QRadialGradient(point, radius)
            grad.setColorAt(0., tint(color, int(43 + 85*power)))
            grad.setColorAt(.2, tint(color, int(21 + 37*power)))
            grad.setColorAt(.65, tint(color, 7))
            grad.setColorAt(1., tint(color, 0))
            p.setBrush(QtGui.QBrush(grad))
            p.drawEllipse(point, radius, radius)
        p.end()
        self.glow_layer.setPixmap(QtGui.QPixmap.fromImage(image))
        self.glow_layer.setScale(1 / resolution)
        self.glow_layer.setPos(rect.topLeft())
        self.glow_layer.setVisible(self.show_glow)

    def toggle_glow(self):
        self.show_glow = not self.show_glow
        self.glow_layer.setVisible(self.show_glow)

    def drag_started(self):
        # Hide stale glow while a node is dragged; vector edges stay connected.
        self.glow_layer.setVisible(False)
        if self.on_drag_start:
            self.on_drag_start()

    def drag_finished(self):
        self._fit_bounds()
        if self.show_glow:
            self.refresh_glow()
        if self.on_drag_end:
            self.on_drag_end()

    def node_clicked(self, ident):
        if self.on_node_click:
            self.on_node_click(ident)
        else:
            self.selected_node(ident)

    def selected_node(self, ident):
        for node_id, item in self.node_items.items():
            was = item.active
            item.active = node_id == ident
            if item.active != was:
                item.update()
        for edge in self.edge_items:
            edge.set_highlighted(edge.a.data.ident == ident or edge.b.data.ident == ident)
        if self.on_select:
            self.on_select(ident)


class SmoothGraphView(QtWidgets.QGraphicsView):
    """Draws only when moving/zooming or when the scene changes."""
    def __init__(self, scene):
        super().__init__(scene)
        self.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self.setBackgroundBrush(QtGui.QBrush(QtGui.QColor("#000000")))
        self.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        self.setRenderHint(QtGui.QPainter.RenderHint.TextAntialiasing)
        self.setViewportUpdateMode(QtWidgets.QGraphicsView.ViewportUpdateMode.BoundingRectViewportUpdate)
        self.setOptimizationFlag(QtWidgets.QGraphicsView.OptimizationFlag.DontSavePainterState, True)
        self.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setTransformationAnchor(QtWidgets.QGraphicsView.ViewportAnchor.NoAnchor)
        self.setResizeAnchor(QtWidgets.QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setMouseTracking(True)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)

        self.camera = QtCore.QPointF(0, 0)
        self.target_camera = None
        self.scale_now = .84
        self.target_scale = .84
        self.anchor_scene = None
        self.anchor_pixel = None
        self.velocity = QtCore.QPointF()
        self.dragging_background = False
        self.last_mouse = QtCore.QPointF()
        self.last_drag_time = 0.0
        self.clock = time.perf_counter()
        self._timer = QtCore.QTimer(self)
        self._timer.setTimerType(QtCore.Qt.TimerType.PreciseTimer)
        self._timer.timeout.connect(self.advance_camera)
        self._timer.setInterval(16)
        self.apply_camera()
        scene.on_drag_start = self.stop_inertia

    def apply_camera(self):
        # Zoom via vector scene transform. Font glyphs and node shapes are
        # *re-rendered* at the new scale, never enlarged from a cached image.
        self.setTransform(QtGui.QTransform.fromScale(self.scale_now, self.scale_now))
        self.centerOn(self.camera)

    def start_animation(self):
        self.clock = time.perf_counter()
        if not self._timer.isActive():
            self._timer.start()

    def advance_camera(self):
        now = time.perf_counter()
        dt = max(.001, min(.04, now-self.clock))
        self.clock = now
        lerp_zoom = 1 - math.exp(-12*dt)
        lerp_focus = 1 - math.exp(-7.0*dt)
        self.scale_now += (self.target_scale - self.scale_now) * lerp_zoom
        zoom_done = abs(self.target_scale-self.scale_now) < .0003
        if zoom_done:
            self.scale_now = self.target_scale
        if self.target_camera is not None:
            self.camera += (self.target_camera - self.camera) * lerp_focus
            if QtCore.QLineF(self.camera, self.target_camera).length() < .25:
                self.camera = self.target_camera
                self.target_camera = None
        elif self.anchor_scene is not None:
            pixel = self.anchor_pixel
            center = QtCore.QPointF(self.viewport().width()*.5, self.viewport().height()*.5)
            delta = (pixel - center) / self.scale_now
            self.camera = self.anchor_scene - delta
            if zoom_done:
                self.anchor_scene = self.anchor_pixel = None
        elif not self.dragging_background:
            self.camera += self.velocity * dt
            self.velocity *= math.exp(-3.8*dt)
            if math.hypot(self.velocity.x(), self.velocity.y()) < 4:
                self.velocity = QtCore.QPointF()
        self.apply_camera()
        if (zoom_done and self.target_camera is None and self.anchor_scene is None
            and math.hypot(self.velocity.x(), self.velocity.y()) < 4):
            self._timer.stop()

    def focus(self, ident, zoom=1.25):
        if ident not in self.scene().node_items:
            return
        node = self.scene().node_items[ident]
        self.scene().selected_node(ident)
        self.target_camera = node.pos()
        self.target_scale = max(.28, min(3.8, zoom))
        self.anchor_scene = self.anchor_pixel = None
        self.velocity = QtCore.QPointF()
        self.start_animation()

    def reset_camera(self):
        self.target_camera = self.scene().sceneRect().center()
        self.target_scale = .84
        self.anchor_scene = self.anchor_pixel = None
        self.velocity = QtCore.QPointF()
        self.start_animation()

    def stop_inertia(self):
        self.velocity = QtCore.QPointF()
        self.target_camera = None
        self.anchor_scene = self.anchor_pixel = None
        self._timer.stop()

    def mousePressEvent(self, event):
        if event.button() in (QtCore.Qt.MouseButton.LeftButton, QtCore.Qt.MouseButton.MiddleButton):
            hit = self.itemAt(event.position().toPoint())
            while hit is not None and not isinstance(hit, GraphNode):
                hit = hit.parentItem()
            if event.button() == QtCore.Qt.MouseButton.MiddleButton or hit is None:
                self.dragging_background = True
                self.last_mouse = event.position()
                self.last_drag_time = time.perf_counter()
                self.stop_inertia()
                self.setCursor(QtCore.Qt.CursorShape.ClosedHandCursor)
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.dragging_background:
            point = event.position()
            delta = point-self.last_mouse
            now = time.perf_counter()
            dt = max(.008, now-self.last_drag_time)
            shift = QtCore.QPointF(-delta.x()/self.scale_now, -delta.y()/self.scale_now)
            self.camera += shift
            self.velocity = self.velocity*.55 + (shift/dt)*.45
            self.last_drag_time = now
            self.last_mouse = point
            self.apply_camera()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.dragging_background:
            self.dragging_background = False
            self.setCursor(QtCore.Qt.CursorShape.ArrowCursor)
            self.start_animation()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if not delta:
            return
        self.anchor_scene = self.mapToScene(event.position().toPoint())
        self.anchor_pixel = event.position()
        self.target_camera = None
        self.velocity = QtCore.QPointF()
        self.target_scale = max(.27, min(3.8, self.target_scale * (1.17 ** (delta/120))))
        self.start_animation()
        event.accept()

    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key.Key_R:
            self.reset_camera()
        elif event.key() == QtCore.Qt.Key.Key_G:
            self.scene().toggle_glow()
        else:
            super().keyPressEvent(event)


class AtlasGraph(QtWidgets.QWidget):
    """An embeddable, UI-free graph canvas. Starts empty.

    The widget never saves to disk. Its graph_changed signal tells your
    main application when new or moved data can be saved to project JSON.
    """

    node_selected = QtCore.Signal(str)
    graph_changed = QtCore.Signal()


    

    def __init__(self, graph_data=None, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background: #000000;")
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.scene = KnowledgeScene()
        self.view = SmoothGraphView(self.scene)
        layout.addWidget(self.view)

        self.scene.on_node_click = self._clicked_node
        self.scene.on_drag_end = self.graph_changed.emit
        self.load_graph(graph_data if graph_data is not None else {"nodes": [], "edges": []})

    def _clicked_node(self, node_id):
        self.scene.selected_node(node_id)
        self.node_selected.emit(node_id)

    def load_graph(self, graph_data):
        """Replace current data. Use project.get('graph', {'nodes': [], 'edges': []})."""
        self.scene.load_graph(graph_data or {"nodes": [], "edges": []})
        self.view.reset_camera()

    def get_graph_data(self):
        """Return everything needed for JSON, including dragged node positions."""
        return self.scene.to_dict()

    def add_node(self, record):
        """Add a node dictionary with an ID, name, color, group, etc."""
        node = self.scene.add_node(record)
        self.graph_changed.emit()
        return node.ident

    def add_edge(self, record):
        """Add an edge dictionary with 'from' and 'to' node IDs."""
        # Preserve silent duplicate behavior from the graph renderer.
        before = len(self.scene.links)
        self.scene.add_edge(record)
        if len(self.scene.links) != before:
            self.graph_changed.emit()

    def create_node(self, name, *, node_id=None, color=None, group="",
                    node_type="note", description="", connections=None,
                    x=None, y=None, radius=None, metadata=None):
        """Create a node; optionally connect it to nodes that ALREADY exist.

        connections: [other_id, {"to": other_id, "relation": "depends_on"}, ...]
        Other fields are saved for your main application; only type, color,
        name, size, and position control its appearance for now.
        """
        ident = str(node_id or uuid.uuid4())
        if ident in self.scene.data_by_id:
            raise ValueError(f"Duplicate node ID: {ident}")
        prepared_edges = []
        for connection in connections or []:
            if isinstance(connection, dict):
                target_id = str(connection["to"])
                edge = {"from": ident, "to": target_id,
                        "relation": connection.get("relation", "related_to")}
                if "color" in connection:
                    edge["color"] = connection["color"]
                if "metadata" in connection:
                    edge["metadata"] = connection["metadata"]
            else:
                target_id = str(connection)
                edge = {"from": ident, "to": target_id, "relation": "related_to"}
            if target_id not in self.scene.data_by_id:
                raise ValueError(f"Connection target doesn't exist yet: {target_id}")
            prepared_edges.append(edge)

        record = {
            "id": ident, "name": str(name), "color": color,
            "group": group, "type": node_type, "description": description,
            "metadata": metadata or {},
        }
        if x is not None:
            record["x"] = x
        if y is not None:
            record["y"] = y
        if radius is not None:
            record["radius"] = radius

        # Batch the changes to avoid regenerating expensive bloom repeatedly.
        self.scene.add_node(record, refresh=False)
        for edge in prepared_edges:
            self.scene.add_edge(edge, refresh=False)
        self.scene._fit_bounds()
        self.scene._refresh_edges()
        self.scene.refresh_glow()
        self.graph_changed.emit()
        return ident

    def connect_nodes(self, source_id, target_id, *, relation="related_to",
                      color=None, metadata=None):
        """Connect two existing nodes."""
        self.add_edge({"from": str(source_id), "to": str(target_id),
                       "relation": relation, "color": color,
                       "metadata": metadata or {}})

    def focus_node(self, node_id, zoom=1.5):
        """Smoothly pan/zoom to a node from your own main.py sidebar."""
        self.view.focus(str(node_id), zoom)


    def delete_node(self, node_id):
        data = self.get_graph_data()

        data["nodes"] = [
            node for node in data["nodes"]
            if node["id"] != node_id
        ]

        data["edges"] = [
            edge for edge in data["edges"]
            if edge["from"] != node_id and edge["to"] != node_id
        ]

        self.load_graph(data)
        self.graph_changed.emit()


# Backward-compatible import: `from graph import AtlasDemo` still works.
AtlasDemo = AtlasGraph


if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    window = AtlasGraph()  # Only a blank, interactive black canvas.
    window.resize(1200, 800)
    window.show()
    sys.exit(app.exec())
