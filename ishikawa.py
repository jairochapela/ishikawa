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
