from django.db import migrations

def apply_fix(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return
    
    # SalidaOrden
    schema_editor.execute("""
        ALTER TABLE produccion_salidaorden
        DROP CONSTRAINT IF EXISTS produccion_salidaord_orden_id_0c13fd9e_fk_produccio;
    """)
    schema_editor.execute("""
        ALTER TABLE produccion_salidaorden
        DROP CONSTRAINT IF EXISTS produccion_salidaorden_orden_id_fk;
    """)
    schema_editor.execute("""
        ALTER TABLE produccion_salidaorden
        ADD CONSTRAINT produccion_salidaorden_orden_id_fk
        FOREIGN KEY (orden_id)
        REFERENCES produccion_ordenproduccion(id)
        ON DELETE CASCADE;
    """)

    # ConsumoOP
    schema_editor.execute("""
        ALTER TABLE produccion_consumoop
        DROP CONSTRAINT IF EXISTS produccion_consumoop_orden_id_5104b342_fk_produccio;
    """)
    schema_editor.execute("""
        ALTER TABLE produccion_consumoop
        DROP CONSTRAINT IF EXISTS produccion_consumoop_orden_id_fk;
    """)
    schema_editor.execute("""
        ALTER TABLE produccion_consumoop
        ADD CONSTRAINT produccion_consumoop_orden_id_fk
        FOREIGN KEY (orden_id)
        REFERENCES produccion_ordenproduccion(id)
        ON DELETE CASCADE;
    """)

class Migration(migrations.Migration):
    dependencies = [
        ('produccion', '0006_alter_salidaorden_orden'),
    ]
    operations = [
        migrations.RunPython(apply_fix, reverse_code=migrations.RunPython.noop),
    ]
