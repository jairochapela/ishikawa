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

    def to_ascii(self) -> str:
        """Devuelve el diagrama como arte ASCII (espina de pescado en texto)."""
        self._validate()
        return ASCIIFishboneRenderer().render(self)

    def to_html(self) -> str:
        """Devuelve el diagrama como página HTML con listas anidadas y CSS de espina de pescado."""
        self._validate()
        return HTMLRenderer().render(self)

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

    Reglas de trazado:
    - Nivel 1 (recurso):  rama diagonal a 45°, alternando arriba/abajo.
    - Nivel 2 (causa):    rama horizontal desde la diagonal del recurso.
    - Nivel 3 (subcausa): diagonal a 45° de nuevo.
    - Sucesivos niveles alternan diagonal ↔ horizontal (hasta nivel 5).
    - Línea más fina y tipografía más pequeña a mayor profundidad.
    - Canvas calculado dinámicamente según el árbol completo.
    """

    _B     = 42                      # px por hoja (unidad de escala)
    _INTER = 52                      # separación mínima horizontal entre recursos
    _PAD   = 58                      # margen exterior del canvas
    _C45   = math.cos(math.pi / 4)
    _S45   = math.sin(math.pi / 4)

    # índice = nivel − 1  (niveles 1..5)
    _STROKES = [2.8,     2.0,     1.4,     1.0,     0.8]
    _FONTS   = [13,      11,      9,       8,       7  ]
    _BOLD    = ['bold', 'normal', 'normal', 'normal', 'normal']
    _COLORS  = ['#1a5276', '#2c3e50', '#555', '#777', '#999']

    # ── helpers ───────────────────────────────────────────────────────────

    @classmethod
    def _lv(cls, node: Node) -> int:
        """Número de hojas en el subárbol."""
        return 1 if not node.children else sum(cls._lv(c) for c in node.children)

    @classmethod
    def _h_extent(cls, node: Node, level: int) -> float:
        """
        Extensión horizontal máxima (hacia la izquierda) del subárbol.

        La proyección horizontal de una rama es n*B para ambos tipos
        (diagonal: L*cos45 = n*B/sin45*cos45 = n*B; horizontal: L = n*B),
        lo que simplifica el cálculo recursivo.
        """
        n   = cls._lv(node)
        own = float(n * cls._B)
        txt = len(node.text) * 5.8          # estimación del ancho del texto
        if not node.children:
            return own + txt
        total, cum, best = n, 0.0, own
        for child in node.children:
            cn   = cls._lv(child)
            t    = (cum + cn / 2) / total
            best = max(best, t * own + cls._h_extent(child, level + 1))
            cum += cn
        return best

    @classmethod
    def _v_max(cls, node: Node, level: int) -> float:
        """Extensión vertical máxima del subárbol desde su punto de unión."""
        n     = cls._lv(node)
        # Las ramas diagonales tienen proyección vertical n*B; las horizontales, 0
        own_v = float(n * cls._B) if level % 2 == 1 else 0.0
        fi    = min(level - 1, len(cls._FONTS) - 1)
        if not node.children:
            # La etiqueta en la punta de una rama diagonal necesita espacio extra
            return own_v + (cls._FONTS[fi] + 8 if level % 2 == 1 else 0)
        total, cum, best = n, 0.0, own_v
        for child in node.children:
            cn    = cls._lv(child)
            t     = (cum + cn / 2) / total
            att_v = t * own_v if level % 2 == 1 else 0.0
            best  = max(best, att_v + cls._v_max(child, level + 1))
            cum  += cn
        return best

    # ── render principal ──────────────────────────────────────────────────

    def render(self, root: Ishikawa) -> str:
        resources = root.children
        n = len(resources)
        above_res = [r for i, r in enumerate(resources) if i % 2 == 0]
        below_res = [r for i, r in enumerate(resources) if i % 2 == 1]

        # Posiciones x en la espina: cada recurso se sitúa a la derecha del
        # anterior dejando espacio para su propio subárbol + separación.
        h_extents = [self._h_extent(r, 1) for r in resources]
        x_pos: List[float] = []
        if n:
            x_pos.append(h_extents[0] + self._PAD)
            for i in range(1, n):
                x_pos.append(x_pos[-1] + h_extents[i] + self._INTER)

        PROB_W, PROB_H = 120, 54
        X_PROB = (x_pos[-1] if n else 0) + self._INTER + PROB_W / 2
        W      = int(X_PROB + PROB_W / 2 + self._PAD)

        # Altura del canvas: máximo alcance vertical de cada lado + márgenes
        v_above = (max(self._v_max(r, 1) for r in above_res) if above_res else 0) + self._PAD
        v_below = (max(self._v_max(r, 1) for r in below_res) if below_res else 0) + self._PAD
        H = int(v_above + v_below + 2 * self._PAD)
        Y = int(v_above + self._PAD)          # y de la espina dorsal

        x_spine_start = (x_pos[0] - 18) if n else self._PAD
        x_spine_end   = X_PROB - PROB_W / 2

        els: List[str] = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
            f'style="font-family:Arial,sans-serif;background:#fdfcfa;">',
            '  <defs>'
            '<marker id="arr" markerWidth="10" markerHeight="7" '
            'refX="9" refY="3.5" orient="auto">'
            '<polygon points="0 0,10 3.5,0 7" fill="#555"/>'
            '</marker>'
            '</defs>',
            f'  <line x1="{x_spine_start:.1f}" y1="{Y}" '
            f'x2="{x_spine_end:.1f}" y2="{Y}" '
            f'stroke="#555" stroke-width="3" marker-end="url(#arr)"/>',
        ]

        self._prob_box(els, root.text, X_PROB, float(Y), PROB_W, PROB_H)
        for i, resource in enumerate(resources):
            sign = -1 if i % 2 == 0 else 1
            self._draw(els, resource, x_pos[i], float(Y), 1, sign)

        els.append('</svg>')
        return '\n'.join(els)

    # ── dibujo recursivo ──────────────────────────────────────────────────

    def _draw(self, els: List[str], node: Node,
              ax: float, ay: float, level: int, sign: int) -> None:
        fi = min(level - 1, len(self._STROKES) - 1)
        n  = self._lv(node)

        if level % 2 == 1:          # ── rama diagonal ──────────────────
            L  = n * self._B / self._S45
            ex = ax - self._C45 * L
            ey = ay + sign * self._S45 * L
        else:                        # ── rama horizontal ────────────────
            L  = float(n * self._B)
            ex = ax - L
            ey = ay

        els.append(
            f'  <line x1="{ax:.1f}" y1="{ay:.1f}" x2="{ex:.1f}" y2="{ey:.1f}"'
            f' stroke="{self._COLORS[fi]}" stroke-width="{self._STROKES[fi]}"/>'
        )
        self._label(els, node.text, ex, ey, level, sign, fi)

        if node.children:
            total, cum = n, 0.0
            for child in node.children:
                cn = self._lv(child)
                t  = (cum + cn / 2) / total
                self._draw(els, child,
                           ax + t * (ex - ax),
                           ay + t * (ey - ay),
                           level + 1, sign)
                cum += cn

    def _label(self, els: List[str], text: str,
               x: float, y: float, level: int, sign: int, fi: int) -> None:
        fs, fw, color = self._FONTS[fi], self._BOLD[fi], self._COLORS[fi]
        tw = len(text) * fs * 0.57      # ancho estimado del texto

        if level % 2 == 1:              # punta de rama diagonal
            lx, ly, anchor = x, y + sign * (fs + 6), 'middle'
            rx = lx - tw / 2
        else:                           # extremo izquierdo de rama horizontal
            lx, ly, anchor = x - 4, y - 4, 'end'
            rx = lx - tw

        els.append(
            f'  <rect x="{rx:.1f}" y="{ly - fs:.1f}" width="{tw:.0f}" '
            f'height="{fs + 4}" fill="white" fill-opacity="0.8" rx="2"/>'
        )
        els.append(
            f'  <text x="{lx:.1f}" y="{ly:.1f}" text-anchor="{anchor}" '
            f'font-size="{fs}" font-weight="{fw}" fill="{color}">{text}</text>'
        )

    def _prob_box(self, els: List[str], text: str,
                  cx: float, cy: float, bw: float, bh: float) -> None:
        els.append(
            f'  <rect x="{cx - bw/2:.1f}" y="{cy - bh/2:.1f}" '
            f'width="{bw}" height="{bh}" rx="8" '
            f'fill="#fde8d8" stroke="#c0392b" stroke-width="2"/>'
        )
        words = text.split()
        if len(text) <= 16 or len(words) <= 2:
            els.append(
                f'  <text x="{cx:.1f}" y="{cy + 5:.1f}" text-anchor="middle" '
                f'font-size="12" font-weight="bold" fill="#c0392b">{text}</text>'
            )
        else:
            mid = len(words) // 2
            for k, line in enumerate([' '.join(words[:mid]), ' '.join(words[mid:])]):
                els.append(
                    f'  <text x="{cx:.1f}" y="{cy - 4 + k * 14:.1f}" '
                    f'text-anchor="middle" font-size="11" font-weight="bold" '
                    f'fill="#c0392b">{line}</text>'
                )


class HTMLRenderer(BaseRenderer):
    """
    Renderiza un diagrama Ishikawa como un documento HTML completo y
    autocontenido, usando listas ``<ul>/<li>`` anidadas.

    El CSS embebido transforma la jerarquía de listas en una representación
    visual que se asemeja a una espina de pescado:

    * La espina dorsal es una línea horizontal que cruza el centro del diagrama.
    * Los recursos (nivel 1) se conectan a la espina con ramas diagonales,
      alternando arriba (índice par) y abajo (índice impar).
    * Las causas y subcausas (nivel 2+) se listan en columna a lo largo de
      cada rama, con tamaño y color decrecientes según la profundidad.

    Clases CSS generadas
    --------------------
    ``.ik-diagram``   – ``<ul>`` raíz; flex row, problema a la derecha.
    ``.ik-problem``   – ``<li>`` del problema; cabeza del pez.
    ``.ik-resources`` – ``<ul>`` de recursos; contiene la línea de espina.
    ``.ik-resource``  – ``<li>`` de recurso; con rama diagonal vía ``::before``.
    ``.ik-above``     – recurso por encima de la espina (índice par).
    ``.ik-below``     – recurso por debajo de la espina (índice impar).
    ``.ik-causes``    – ``<ul>`` de causas/subcausas.
    ``.ik-cause``     – ``<li>`` de causa individual.
    ``.ik-dN``        – profundidad N (0 = problema, 1 = recurso, 2+ = causa).
    ``.ik-label``     – ``<span>`` con el texto de cada nodo.
    """

    # ── CSS embebido ──────────────────────────────────────────────────────────

    _CSS: str = """\
/* ─── Reset ───────────────────────────────────────────────────────────── */
.ik-diagram, .ik-diagram ul, .ik-diagram li {
  list-style: none;
  margin:     0;
  padding:    0;
}

/* ─── Raíz: flex row, problema a la derecha ────────────────────────────── */
.ik-diagram {
  display:        flex;
  flex-direction: row-reverse;
  align-items:    center;
  font-family:    Arial, Helvetica, sans-serif;
  background:     #fdfcfa;
  padding:        28px;
  overflow-x:     auto;
  border-radius:  8px;
}

/* ─── Problema – cabeza del pez ────────────────────────────────────────── */
.ik-problem { flex-shrink: 0; position: relative; z-index: 2; }

.ik-d0 > .ik-label {
  display:       block;
  background:    #fde8d8;
  border:        2.5px solid #c0392b;
  border-radius: 8px;
  padding:       12px 18px;
  font-weight:   bold;
  font-size:     14px;
  color:         #c0392b;
  text-align:    center;
  max-width:     200px;
  word-break:    break-word;
}

/* ─── Lista de recursos – espina horizontal ────────────────────────────── */
.ik-resources {
  display:        flex;
  flex-direction: row-reverse; /* el recurso más cercano al problema queda a la derecha */
  align-items:    center;
  position:       relative;
  padding:        96px 0;      /* espacio para las ramas arriba y abajo */
}

/* Línea de la espina */
.ik-resources::before {
  content:    '';
  position:   absolute;
  left:       0; right: 0;
  top:        50%;
  height:     3px;
  background: linear-gradient(to right, #95a5a6, #2c3e50);
  transform:  translateY(-50%);
  z-index:    0;
}

/* Flecha hacia el problema */
.ik-resources::after {
  content:    '';
  position:   absolute;
  right:      -11px;
  top:        50%;
  transform:  translateY(-50%);
  border-left:   12px solid #2c3e50;
  border-top:    7px solid transparent;
  border-bottom: 7px solid transparent;
}

/* ─── Recurso – rama principal ──────────────────────────────────────────── */
.ik-resource {
  position:   relative;
  display:    flex;
  flex-direction: column;
  align-items: center;
  padding:    0 18px;
  min-width:  90px;
  z-index:    1;
}

/* Rama diagonal conectada a la espina */
.ik-resource::before {
  content:          '';
  position:         absolute;
  width:            3px;
  height:           68px;       /* longitud visible de la rama */
  background:       #1a5276;
  left:             50%;
  transform-origin: center center;
  z-index:          0;
}

/* Arriba: rama desde la espina hacia arriba-izquierda */
.ik-above::before {
  bottom:    calc(50% - 2px);
  transform: translateX(-50%) rotate(-45deg);
}

/* Abajo: rama desde la espina hacia abajo-izquierda */
.ik-below::before {
  top:       calc(50% - 2px);
  transform: translateX(-50%) rotate(45deg);
}

/* Recursos de arriba: causas encima de la espina */
.ik-above { justify-content: flex-end; }

/* Recursos de abajo: causas debajo de la espina */
.ik-below { justify-content: flex-start; }

/* ─── Etiqueta del recurso ──────────────────────────────────────────────── */
.ik-d1 > .ik-label {
  display:       block;
  background:    #d6eaf8;
  border:        1.5px solid #1a5276;
  border-radius: 5px;
  padding:       5px 10px;
  font-weight:   bold;
  font-size:     12px;
  color:         #1a5276;
  text-align:    center;
  white-space:   nowrap;
  position:      relative;
  z-index:       2;
}

.ik-above .ik-d1 > .ik-label { margin-bottom: 10px; }
.ik-below .ik-d1 > .ik-label { margin-top:    10px; }

/* ─── Lista de causas ───────────────────────────────────────────────────── */
.ik-causes {
  display:        flex;
  flex-direction: column;
  gap:            4px;
  align-items:    flex-start;
  position:       relative;
  z-index:        2;
}

.ik-above .ik-causes { margin-bottom: 5px; }
.ik-below .ik-causes { margin-top:    5px; }

/* ─── Causa – nivel 2 ───────────────────────────────────────────────────── */
.ik-d2 > .ik-label {
  display:       inline-block;
  background:    #eaf4fb;
  border:        1px solid #5dade2;
  border-radius: 4px;
  padding:       3px 9px;
  font-size:     11px;
  color:         #2c3e50;
  white-space:   nowrap;
}

.ik-d2 > .ik-label::before { content: '▸ '; color: #5dade2; font-size: 9px; }

/* ─── Subcausa – nivel 3 ────────────────────────────────────────────────── */
.ik-d3 > .ik-label {
  display:       inline-block;
  background:    #f9f9f9;
  border:        1px solid #aab7c4;
  border-radius: 3px;
  padding:       2px 7px;
  font-size:     10px;
  color:         #555;
  white-space:   nowrap;
  margin-left:   12px;
}

.ik-d3 > .ik-label::before { content: '· '; color: #aab7c4; }

/* ─── Profundidades 4 y 5 ───────────────────────────────────────────────── */
.ik-d4 > .ik-label,
.ik-d5 > .ik-label {
  display:       inline-block;
  background:    #f5f5f5;
  border:        1px solid #ddd;
  border-radius: 3px;
  padding:       2px 5px;
  font-size:     9px;
  color:         #888;
  white-space:   nowrap;
  margin-left:   22px;
}

.ik-d4 > .ik-label::before,
.ik-d5 > .ik-label::before { content: '  · '; color: #ccc; }
"""

    # ── Renderizado ───────────────────────────────────────────────────────────

    def render(self, root: Ishikawa) -> str:
        body = self._diagram(root)
        return (
            '<!DOCTYPE html>\n'
            '<html lang="es">\n'
            '<head>\n'
            '  <meta charset="UTF-8">\n'
            '  <meta name="viewport" content="width=device-width,initial-scale=1">\n'
            f'  <title>Ishikawa – {self._e(root.text)}</title>\n'
            '  <style>\n'
            f'{self._CSS}'
            '  </style>\n'
            '</head>\n'
            '<body>\n'
            f'{body}\n'
            '</body>\n'
            '</html>\n'
        )

    def _diagram(self, root: Ishikawa) -> str:
        resources_html = self._resources(root.children) if root.children else ''
        return (
            '<ul class="ik-diagram">\n'
            '  <li class="ik-problem ik-d0">\n'
            f'    <span class="ik-label">{self._e(root.text)}</span>\n'
            f'{resources_html}'
            '  </li>\n'
            '</ul>'
        )

    def _resources(self, resources: List[Node]) -> str:
        items: List[str] = []
        for i, res in enumerate(resources):
            side = 'ik-above' if i % 2 == 0 else 'ik-below'
            causes_html = self._causes(res.children, depth=2, indent=3) if res.children else ''
            items.append(
                f'      <li class="ik-resource ik-d1 {side}">\n'
                f'        <span class="ik-label">{self._e(res.text)}</span>\n'
                f'{causes_html}'
                f'      </li>'
            )
        return (
            '    <ul class="ik-resources">\n'
            + '\n'.join(items) + '\n'
            + '    </ul>\n'
        )

    def _causes(self, nodes: List[Node], depth: int, indent: int) -> str:
        pad = '  ' * indent
        d_cls = f'ik-d{min(depth, 5)}'
        lines = [f'{pad}<ul class="ik-causes ik-depth-{depth}">']
        for node in nodes:
            lines.append(f'{pad}  <li class="ik-cause {d_cls}">')
            lines.append(f'{pad}    <span class="ik-label">{self._e(node.text)}</span>')
            if node.children:
                lines.append(self._causes(node.children, depth + 1, indent + 1))
            lines.append(f'{pad}  </li>')
        lines.append(f'{pad}</ul>')
        return '\n'.join(lines) + '\n'

    @staticmethod
    def _e(text: str) -> str:
        """Escapa caracteres especiales HTML."""
        return (
            text
            .replace('&', '&amp;')
            .replace('<', '&lt;')
            .replace('>', '&gt;')
            .replace('"', '&quot;')
        )


class JupyterRenderer(BaseRenderer):
    """Envuelve el SVG en HTML para Jupyter. Sin CDN — funciona offline."""

    def render(self, root: Ishikawa) -> str:
        svg = SVGFishboneRenderer().render(root)
        return f'<div style="overflow-x:auto; padding:4px;">{svg}</div>'


class ASCIIFishboneRenderer(BaseRenderer):
    """
    Renderiza la espina de pescado en arte ASCII de terminal.

    Estructura:
    - Espina horizontal con '►' apuntando al problema (derecha).
    - Recursos como diagonales '╲' (arriba) o '╱' (abajo).
    - Causas alineadas a la derecha junto a la diagonal, con ' ─' de conexión.
    - Subcausas indentadas bajo su causa padre para mostrar jerarquía.
    - Espacio horizontal calculado dinámicamente por el contenido de cada recurso.
    """

    _MARGIN = 4

    def render(self, root: Ishikawa) -> str:
        resources = root.children
        n = len(resources)

        def flat(node: Node):
            """Recorrido DFS: (profundidad, texto) para todos los descendientes."""
            for child in node.children:
                yield (0, child.text)
                for d, t in flat(child):
                    yield (d + 1, t)

        def diag_len(r: Node) -> int:
            """Filas de diagonal necesarias: una por entrada más 2 de margen."""
            return max(len(list(flat(r))) + 2, 4)

        def content_width(r: Node) -> int:
            """Ancho máximo de los textos de causas para este recurso."""
            entries = list(flat(r))
            if not entries:
                return len(r.text) + 4
            return max(len('  ' * d + t) + 3 for d, t in entries)

        above_res = [r for i, r in enumerate(resources) if i % 2 == 0]
        below_res = [r for i, r in enumerate(resources) if i % 2 == 1]

        rows_above = max((diag_len(r) + 2 for r in above_res), default=3)
        rows_below = max((diag_len(r) + 2 for r in below_res), default=3)
        spine_row  = rows_above
        total_rows = spine_row + 1 + rows_below

        # x de cada recurso en la espina, calculado dinámicamente.
        # El subárbol de cada recurso se extiende hacia la izquierda, ocupando
        # content_width + diag_len columnas. Los recursos de lados opuestos no
        # se solapan verticalmente, por lo que podemos usar la mitad como paso.
        x_pos: List[int] = []
        if n:
            x_pos.append(self._MARGIN + content_width(resources[0]) + diag_len(resources[0]))
            for i in range(1, n):
                step = max(content_width(resources[i]) // 2 + diag_len(resources[i]) // 2 + 4, 16)
                x_pos.append(x_pos[-1] + step)

        prob_text = root.text
        spine_end = (x_pos[-1] + 6) if n else self._MARGIN + 20
        W = spine_end + len(prob_text) + 5

        canvas: List[List[str]] = [[' '] * W for _ in range(total_rows)]

        # Espina dorsal
        for x in range(self._MARGIN, spine_end):
            canvas[spine_row][x] = '─'
        canvas[spine_row][spine_end] = '►'
        for j, ch in enumerate(f' {prob_text}'):
            if spine_end + j < W:
                canvas[spine_row][spine_end + j] = ch

        for i, resource in enumerate(resources):
            above   = (i % 2 == 0)
            sign    = -1 if above else 1
            x       = x_pos[i]
            dlen    = diag_len(resource)
            entries = list(flat(resource))
            n_ent   = len(entries)

            # Diagonal
            for k in range(1, dlen + 1):
                row = spine_row + sign * k
                col = x - k
                if 0 <= row < total_rows and 0 <= col < W:
                    canvas[row][col] = '╲' if above else '╱'

            # Etiqueta del recurso en la punta de la diagonal
            label   = f'[{resource.text}]'
            tip_row = max(0, min(spine_row + sign * (dlen + 1), total_rows - 1))
            tip_col = x - dlen - 1 - len(label) // 2
            for j, ch in enumerate(label):
                c = tip_col + j
                if 0 <= c < W:
                    canvas[tip_row][c] = ch

            # Causas y subcausas distribuidas a lo largo de la diagonal
            if n_ent:
                # Asignar posiciones k únicas, bien distribuidas
                k_vals: List[int] = []
                for idx in range(n_ent):
                    k = max(1, min(dlen - 1,
                                  round((idx + 0.5) / n_ent * (dlen - 1)) + 1))
                    if k_vals and k <= k_vals[-1]:
                        k = k_vals[-1] + 1
                    k_vals.append(min(k, dlen - 1))

                for idx, (depth, text) in enumerate(entries):
                    k   = k_vals[idx]
                    row = spine_row + sign * k
                    col = x - k                      # columna de la diagonal
                    entry = '  ' * depth + text + ' ─'
                    # Alineado a la derecha: el ' ─' final apunta a la diagonal
                    start = col - len(entry)
                    for j, ch in enumerate(entry):
                        c = start + j
                        if 0 <= c < W and 0 <= row < total_rows:
                            canvas[row][c] = ch

        return '\n'.join(''.join(row).rstrip() for row in canvas)
