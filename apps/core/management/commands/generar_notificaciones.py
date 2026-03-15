# -*- coding: utf-8 -*-
from django.core.management.base import BaseCommand
from datetime import date, timedelta
from apps.core.models import Notificacion


class Command(BaseCommand):
    help = 'Genera/actualiza notificaciones internas'

    def handle(self, *args, **options):
        hoy = date.today()
        limite = hoy + timedelta(days=7)
        gen = 0

        # CxC venciendo
        from apps.ventas.models import FacturaVenta
        for f in FacturaVenta.objects.filter(estado='EMITIDA', fecha_vencimiento__range=[hoy, limite]):
            _, c = Notificacion.objects.update_or_create(
                tipo='CXC_VENCIENDO', entidad='FacturaVenta', entidad_id=f.pk,
                defaults={
                    'titulo': f'Factura {f.numero} vence en {(f.fecha_vencimiento - hoy).days}d',
                    'mensaje': f'Cliente: {f.cliente}. Saldo: {f.get_saldo_pendiente()} USD',
                    'fecha_referencia': f.fecha_vencimiento,
                    'activa': True,
                })
            if c:
                gen += 1

        # Stock bajo mínimo
        from apps.almacen.models import Producto
        for p in Producto.objects.filter(activo=True).exclude(stock_minimo=None):
            if p.stock_actual < p.stock_minimo:
                _, c = Notificacion.objects.update_or_create(
                    tipo='STOCK_MINIMO', entidad='Producto', entidad_id=p.pk,
                    defaults={
                        'titulo': f'Stock bajo: {p.nombre}',
                        'mensaje': f'Actual:{p.stock_actual} Min:{p.stock_minimo}',
                        'fecha_referencia': hoy,
                        'activa': True,
                    })
                if c:
                    gen += 1
            else:
                Notificacion.objects.filter(
                    tipo='STOCK_MINIMO', entidad='Producto', entidad_id=p.pk
                ).update(activa=False)

        # Tasa BCV no cargada
        from apps.core.models import TasaCambio
        if not TasaCambio.objects.filter(fecha__gte=hoy).exists():
            Notificacion.objects.update_or_create(
                tipo='TASA_NO_CARGADA', entidad='TasaCambio', entidad_id=0,
                defaults={
                    'titulo': 'Tasa BCV no disponible',
                    'mensaje': 'Sin tasa para hoy ni días futuros. Documentos VES bloqueados.',
                    'fecha_referencia': hoy,
                    'activa': True,
                })
        else:
            Notificacion.objects.filter(tipo='TASA_NO_CARGADA').update(activa=False)

        # Préstamos venciendo
        from apps.socios.models import PrestamoPorSocio
        for p in PrestamoPorSocio.objects.filter(estado='ACTIVO', fecha_vencimiento__range=[hoy, limite]):
            _, c = Notificacion.objects.update_or_create(
                tipo='PRESTAMO_VENCIENDO', entidad='PrestamoPorSocio', entidad_id=p.pk,
                defaults={
                    'titulo': f'Préstamo {p.numero} vence pronto',
                    'mensaje': f'Socio:{p.socio} Monto:{p.monto_usd} USD Vence:{p.fecha_vencimiento}',
                    'fecha_referencia': p.fecha_vencimiento,
                    'activa': True,
                })
            if c:
                gen += 1

        self.stdout.write(f'Notificaciones generadas/actualizadas: {gen}')
