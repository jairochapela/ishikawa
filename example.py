"""Ejemplo de uso del módulo ishikawa.py"""

from ishikawa import Ishikawa

with Ishikawa("El servicio no arranca") as d:

    with d.recurso("Tecnología") as r:
        r.causa("Dependencia no instalada")

        with r.causa("Permisos incorrectos") as c:
            c.causa("Usuario incorrecto")
            c.causa("SELinux bloqueando ejecución")

    with d.recurso("Procesos") as p:
        p.causa("Checklist incompleto")

    with d.recurso("Personas") as p:
        p.causa("Falta de formación")
        with p.causa("Comunicación deficiente") as c:
            c.causa("Reuniones sin acta")
            c.causa("Canales no definidos")

print("=" * 60)
print("MERMAID")
print("=" * 60)
print(d.to_mermaid())

print()
print("=" * 60)
print("GRAPHVIZ DOT")
print("=" * 60)
print(d.to_graphviz())
