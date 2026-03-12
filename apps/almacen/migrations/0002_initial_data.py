from django.db import migrations

def cargar_unidades_medida(apps, schema_editor):
    UnidadMedida = apps.get_model('almacen', 'UnidadMedida')
    unidades = [
        UnidadMedida(id=1, nombre='Kilogramo', simbolo='kg', activo=True),
        UnidadMedida(id=2, nombre='Gramo', simbolo='g', activo=True),
        UnidadMedida(id=3, nombre='Litro', simbolo='L', activo=True),
        UnidadMedida(id=4, nombre='Mililitro', simbolo='ml', activo=True),
        UnidadMedida(id=5, nombre='Unidad', simbolo='unid', activo=True),
    ]
    UnidadMedida.objects.bulk_create(unidades, ignore_conflicts=True)

def revertir_unidades_medida(apps, schema_editor):
    UnidadMedida = apps.get_model('almacen', 'UnidadMedida')
    UnidadMedida.objects.filter(id__in=[1, 2, 3, 4, 5]).delete()

class Migration(migrations.Migration):

    dependencies = [
        ('almacen', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(cargar_unidades_medida, revertir_unidades_medida),
    ]
