"""
ishikawa.py — DSL declarativa para diagramas de espina de pescado (Ishikawa).

Diseño: árbol explícito de nodos con context managers anidados.
Los renderizadores (Mermaid, Graphviz) están separados del modelo.
"""

from __future__ import annotations

import itertools
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


class JupyterRenderer(BaseRenderer):
    """
    Genera HTML con Mermaid.js embebido para renderizado en Jupyter.

    Usa ES modules (mermaid@11 via CDN) para compatibilidad con
    JupyterLab, Jupyter Notebook y VS Code Notebooks.
    Requiere conexión a internet la primera vez (carga CDN).
    """

    _TEMPLATE = """\
<div style="background:white; padding:12px; border-radius:8px;">
  <pre class="mermaid" style="text-align:left;">
{diagram}
  </pre>
  <script type="module">
    import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs';
    mermaid.initialize({{ startOnLoad: true, theme: 'default' }});
  </script>
</div>"""

    def render(self, root: Ishikawa) -> str:
        diagram = MermaidRenderer().render(root)
        return self._TEMPLATE.format(diagram=diagram)
