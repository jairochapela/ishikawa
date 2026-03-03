"""
ishikawa.py — DSL declarativa para diagramas de espina de pescado (Ishikawa).

Diseño: árbol explícito de nodos con context managers anidados.
Los renderizadores (Mermaid, Graphviz) están separados del modelo.
"""

from __future__ import annotations

import itertools
import math
from abc import ABC, abstractmethod
from typing import List, Optional


# ─────────────────────────────────────────────
# Contador global de IDs únicos por instancia
# ─────────────────────────────────────────────
_id_counter = itertools.count(1)


def _next_id() -> str:
    return f"N{next(_id_counter)}"


# ─────────────────────────────────────────────
# Modelo
# ─────────────────────────────────────────────

class Node(ABC):
    """Nodo base del árbol Ishikawa."""

    def __init__(self, text: str, parent: Optional["Node"] = None) -> None:
        self.id: str = _next_id()
        self.text: str = text
        self.parent: Optional[Node] = parent
        self.children: List[Node] = []

    @property
    @abstractmethod
    def kind(self) -> str:
        """Tipo semántico del nodo: 'problem' | 'recurso' | 'causa'."""

    def _add_child(self, node: "Node") -> None:
        self.children.append(node)

    def __enter__(self) -> "Node":
        return self

    def __exit__(self, *_) -> None:
        pass  # El árbol ya está construido; no se necesita limpieza.

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(id={self.id!r}, text={self.text!r}, children={len(self.children)})"


class Causa(Node):
    """Causa o subcausa dentro de un recurso."""

    kind = "causa"

    def causa(self, text: str) -> "Causa":
        """Añade una subcausa a esta causa y la devuelve (usable con o sin `with`)."""
        child = Causa(text=text, parent=self)
        self._add_child(child)
        return child


class Recurso(Node):
    """Categoría de causas (rama principal de la espina)."""

    kind = "recurso"

    def causa(self, text: str) -> "Causa":
        """Añade una causa a este recurso y la devuelve (usable con o sin `with`)."""
        child = Causa(text=text, parent=self)
        self._add_child(child)
        return child


class Ishikawa(Node):
    """
    Raíz del diagrama. Representa el problema central.

    Uso:
        with Ishikawa("Problema") as d:
            with d.recurso("Categoría") as r:
                r.causa("Causa raíz")
    """

    kind = "problem"

    def recurso(self, text: str) -> "Recurso":
        """Añade una rama (recurso/categoría) al diagrama."""
        child = Recurso(text=text, parent=self)
        self._add_child(child)
        return child

    # Bloquear creación directa de causas en la raíz
    def causa(self, text: str) -> None:  # type: ignore[override]
        raise TypeError(
            "No se pueden añadir causas directamente al diagrama. "
            "Usa primero d.recurso(...) para crear una categoría."
        )

    def _validate(self) -> None:
        if not self.children:
            raise ValueError("El diagrama está vacío: añade al menos un recurso.")

    # ── Exportadores ──────────────────────────────

    def to_mermaid(self) -> str:
        """Devuelve el diagrama como texto Mermaid (flowchart LR)."""
        self._validate()
        renderer = MermaidRenderer()
        return renderer.render(self)

    def to_graphviz(self) -> str:
        """Devuelve el diagrama como texto DOT para Graphviz."""
        self._validate()
        renderer = GraphvizRenderer()
        return renderer.render(self)

    def display(self) -> None:
        """
        Renderiza el diagrama visualmente.

        - En Jupyter/IPython: muestra el diagrama interactivo vía Mermaid.js.
        - En terminal: imprime el código Mermaid.
        """
        try:
            from IPython.display import HTML, display as ipy_display  # type: ignore
            ipy_display(HTML(JupyterRenderer().render(self)))
        except ImportError:
            print(self.to_mermaid())

    def _repr_html_(self) -> str:
        """
        Protocolo de Jupyter: al evaluar `d` en una celda, renderiza el diagrama
        automáticamente sin necesidad de llamar a display().
        """
        try:
            self._validate()
            return JupyterRenderer().render(self)
        except ValueError as e:
            return f"<em>{e}</em>"


# ─────────────────────────────────────────────
# Renderizadores (separados del modelo)
# ─────────────────────────────────────────────

class BaseRenderer(ABC):
    """Contrato para renderizadores de diagramas Ishikawa."""

    @abstractmethod
    def render(self, root: Ishikawa) -> str: ...


class MermaidRenderer(BaseRenderer):
    """Genera código Mermaid en formato flowchart LR."""

    def render(self, root: Ishikawa) -> str:
        lines: List[str] = ["flowchart LR"]
        # Nodo raíz con forma de caja redondeada para destacarlo
        lines.append(f'    {root.id}(["{root.text}"])')
        self._walk(root, lines)
        return "\n".join(lines)

    def _walk(self, node: Node, lines: List[str]) -> None:
        for child in node.children:
            label = f'["{child.text}"]'
            lines.append(f"    {child.id}{label}")
            lines.append(f"    {node.id} --> {child.id}")
            self._walk(child, lines)


class GraphvizRenderer(BaseRenderer):
    """Genera código DOT compatible con Graphviz."""

    def render(self, root: Ishikawa) -> str:
        lines: List[str] = [
            "digraph Ishikawa {",
            '    rankdir=LR;',
            '    node [shape=box, style=rounded];',
        ]
        # Nodo raíz diferenciado visualmente
        lines.append(f'    {root.id} [label="{root.text}", shape=ellipse];')
        self._walk(root, lines)
        lines.append("}")
        return "\n".join(lines)

    def _walk(self, node: Node, lines: List[str]) -> None:
        for child in node.children:
            lines.append(f'    {child.id} [label="{child.text}"];')
            lines.append(f"    {node.id} -> {child.id};")
            self._walk(child, lines)


class SVGFishboneRenderer(BaseRenderer):
    """
    Genera SVG nativo con apariencia real de espina de pescado.

    Anatomía del diagrama:
      - Eje horizontal (espina dorsal) con flecha → Problema (derecha)
      - Ramas diagonales (recursos) a 45°, alternando arriba/abajo
      - Causas como líneas horizontales desde cada rama diagonal
      - Subcausas como pequeñas líneas verticales desde cada causa
    Sin dependencias externas ni conexión a internet.
    """
    # ── Constantes de layout ────────────────────────────────────────────────
    _H       = 500    # alto total del canvas
    _Y       = 250    # y del eje horizontal (espina dorsal)
    _X0      = 40     # inicio del eje
    _FIRST   = 300    # x del primer recurso sobre el eje
    _GAP     = 240    # distancia horizontal entre recursos
    _BLEN    = 140    # longitud de la rama diagonal
    _BDEG    = 45     # ángulo de la rama (grados desde horizontal)
    _CLEN    = 80     # longitud de la línea de causa (horizontal)
    _SLEN    = 42     # longitud de la línea de subcausa (vertical)

    def render(self, root: Ishikawa) -> str:
        resources = root.children
        n = len(resources)
        xs = [self._FIRST + i * self._GAP for i in range(n)]

        spine_end = (xs[-1] if xs else self._FIRST) + 90
        prob_cx   = spine_end + 78
        W = int(prob_cx + 130)

        els: List[str] = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{self._H}" '
            f'style="font-family:Arial,sans-serif;background:#fdfcfa;">',
            # ── Marcador de flecha ───────────────────────────────────────────
            '  <defs>',
            '    <marker id="arr" markerWidth="10" markerHeight="7"'
            '            refX="9" refY="3.5" orient="auto">',
            '      <polygon points="0 0,10 3.5,0 7" fill="#555"/>',
            '    </marker>',
            '  </defs>',
            # ── Eje horizontal (espina dorsal) ───────────────────────────────
            f'  <line x1="{self._X0}" y1="{self._Y}" x2="{spine_end}" y2="{self._Y}"'
            f' stroke="#555" stroke-width="3" marker-end="url(#arr)"/>',
        ]

        self._add_problem(els, root.text, prob_cx, self._Y)

        for i, resource in enumerate(resources):
            self._add_resource(els, resource, xs[i], self._Y, above=(i % 2 == 0))

        els.append('</svg>')
        return '\n'.join(els)

    # ── Caja del problema ────────────────────────────────────────────────────

    def _add_problem(self, els: List[str], text: str, cx: float, cy: float) -> None:
        bw, bh = 110, 52
        rx, ry = cx - bw / 2, cy - bh / 2
        els.append(
            f'  <rect x="{rx:.1f}" y="{ry:.1f}" width="{bw}" height="{bh}"'
            f' rx="8" fill="#fde8d8" stroke="#c0392b" stroke-width="2"/>'
        )
        words = text.split()
        # Partir en dos líneas si el texto es largo
        if len(text) <= 15 or len(words) <= 2:
            els.append(
                f'  <text x="{cx:.1f}" y="{cy + 5:.1f}" text-anchor="middle"'
                f' font-size="12" font-weight="bold" fill="#c0392b">{text}</text>'
            )
        else:
            mid = len(words) // 2
            l1, l2 = ' '.join(words[:mid]), ' '.join(words[mid:])
            els.append(
                f'  <text x="{cx:.1f}" y="{cy - 5:.1f}" text-anchor="middle"'
                f' font-size="11" font-weight="bold" fill="#c0392b">{l1}</text>'
            )
            els.append(
                f'  <text x="{cx:.1f}" y="{cy + 9:.1f}" text-anchor="middle"'
                f' font-size="11" font-weight="bold" fill="#c0392b">{l2}</text>'
            )

    # ── Rama de recurso + causas + subcausas ─────────────────────────────────

    def _add_resource(
        self, els: List[str], resource: Node,
        x: float, y_spine: float, above: bool
    ) -> None:
        ang  = math.radians(self._BDEG)
        dx   = self._BLEN * math.cos(ang)
        dy   = self._BLEN * math.sin(ang)
        sign = -1 if above else 1   # -1 = arriba en SVG (y decrece)

        tip_x = x - dx
        tip_y = y_spine + sign * dy

        # ── Rama diagonal ────────────────────────────────────────────────────
        els.append(
            f'  <line x1="{x:.1f}" y1="{y_spine}" x2="{tip_x:.1f}" y2="{tip_y:.1f}"'
            f' stroke="#444" stroke-width="2.5"/>'
        )

        # ── Causas + subcausas ────────────────────────────────────────────────
        n_causes = len(resource.children)
        for i, cause in enumerate(resource.children):
            t  = (i + 1) / (n_causes + 1)
            px = x + t * (tip_x - x)
            py = y_spine + t * (tip_y - y_spine)

            # Línea de causa (horizontal, hacia la izquierda)
            cx_end = px - self._CLEN
            els.append(
                f'  <line x1="{px:.1f}" y1="{py:.1f}" x2="{cx_end:.1f}" y2="{py:.1f}"'
                f' stroke="#666" stroke-width="1.5"/>'
            )
            els.append(
                f'  <text x="{cx_end - 5:.1f}" y="{py + 4:.1f}"'
                f' text-anchor="end" font-size="11" fill="#2c3e50">{cause.text}</text>'
            )

            # Líneas de subcausa (verticales, hacia afuera del eje)
            n_sub = len(cause.children)
            for j, sub in enumerate(cause.children):
                s    = (j + 1) / (n_sub + 1)
                sx   = px + s * (cx_end - px)    # punto sobre la línea de causa
                sy1  = py + sign * self._SLEN     # extremo externo
                els.append(
                    f'  <line x1="{sx:.1f}" y1="{py:.1f}" x2="{sx:.1f}" y2="{sy1:.1f}"'
                    f' stroke="#aaa" stroke-width="1.2"/>'
                )
                # Etiqueta al final de la línea (text-anchor="middle" → no desborda lateralmente)
                ly = sy1 + sign * 3
                lya = ly - 4 if above else ly + 12
                els.append(
                    f'  <text x="{sx:.1f}" y="{lya:.1f}"'
                    f' text-anchor="middle" font-size="9" fill="#7f8c8d">{sub.text}</text>'
                )

        # ── Etiqueta del recurso (renderizada al final → encima de todo) ─────
        lbl_y  = tip_y + sign * 22
        bg_w   = max(60, len(resource.text) * 7.5)
        els.append(
            f'  <rect x="{tip_x - bg_w/2:.1f}" y="{lbl_y - 15:.1f}"'
            f' width="{bg_w:.0f}" height="20" fill="white" fill-opacity="0.85" rx="2"/>'
        )
        els.append(
            f'  <text x="{tip_x:.1f}" y="{lbl_y:.1f}" text-anchor="middle"'
            f' font-size="13" font-weight="bold" fill="#1a5276">{resource.text}</text>'
        )


class JupyterRenderer(BaseRenderer):
    """
    Envuelve el SVG de espina de pescado en HTML para Jupyter.
    Sin dependencias externas ni CDN — funciona offline.
    """

    def render(self, root: Ishikawa) -> str:
        svg = SVGFishboneRenderer().render(root)
        return f'<div style="overflow-x:auto; padding:4px;">{svg}</div>'
