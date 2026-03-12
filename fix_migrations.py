import os

d = 'apps/produccion/migrations/'

f3_old = d + '0003_remove_ordenproduccion_cantidad_producida_and_more.py'
f4_old = d + '0004_check_open_orders.py'

f3_new = d + '0003_check_open_orders.py'
f4_new = d + '0004_remove_ordenproduccion_cantidad_producida_and_more.py'

with open(f3_old, 'r', encoding='utf-8') as f:
    c3 = f.read()

with open(f4_old, 'r', encoding='utf-8') as f:
    c4 = f.read()

# Modify dependencies
c3 = c3.replace("('produccion', '0002_consumoop_default_costo_subtotal')", "('produccion', '0003_check_open_orders')")

c4 = c4.replace("('produccion', '0003_remove_ordenproduccion_cantidad_producida_and_more')", "('produccion', '0002_consumoop_default_costo_subtotal')")

# Add runpython logic to c4 (which will become f3_new)
c4 = c4.replace(
'''    operations = [
    ]''',
'''    operations = [
        migrations.RunPython(verificar_ordenes_abiertas),
    ]'''
)

c4 = c4.replace('class Migration', '''def verificar_ordenes_abiertas(apps, schema_editor):
    OrdenProduccion = apps.get_model("produccion", "OrdenProduccion")
    if OrdenProduccion.objects.filter(estado="ABIERTA").exists():
        raise ValueError("Existen Órdenes de Producción en estado ABIERTA. Debe cerrarlas o anularlas antes de ejecutar esta migración destructiva (eliminar campos). Se recomienda hacer pg_dump previo.")

class Migration''')

with open(f3_new, 'w', encoding='utf-8') as f:
    f.write(c4)

with open(f4_new, 'w', encoding='utf-8') as f:
    f.write(c3)

if os.path.exists(f3_old) and f3_old != f3_new and f3_old != f4_new:
    os.remove(f3_old)
if os.path.exists(f4_old) and f4_old != f4_new and f4_old != f3_new:
    os.remove(f4_old)
