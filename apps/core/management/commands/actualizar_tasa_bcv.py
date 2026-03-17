# -*- coding: utf-8 -*-
"""
Management command: actualizar_tasa_bcv
Descarga la tasa USD/VES del dia directamente del portal BCV y la registra en TasaCambio.
Uso: python manage.py actualizar_tasa_bcv
"""
import re
import ssl
import urllib.request
from datetime import date, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand

from apps.core.models import TasaCambio


class Command(BaseCommand):
    help = 'Actualiza la tasa BCV del dia desde el sitio oficial (bcv.org.ve)'

    def handle(self, *args, **options):
        try:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE

            req = urllib.request.Request(
                'https://www.bcv.org.ve/',
                headers={'User-Agent': 'Mozilla/5.0 (compatible; LacteOps/1.0)'},
            )

            with urllib.request.urlopen(req, context=ctx, timeout=10) as f:
                html = f.read().decode('utf-8', errors='ignore')

            # El portal BCV publica la tasa dentro de un bloque id="dolar"
            m = re.search(
                r'id=["\']dolar["\'].*?<strong>\s*([\d,.]+)\s*</strong>',
                html,
                re.DOTALL,
            )
            if not m:
                self.stderr.write('BCV: no se encontro la tasa en el HTML.')
                return

            tasa_str = m.group(1).strip().replace(',', '.')
            tasa = Decimal(tasa_str).quantize(Decimal('0.000001'))

            hoy = date.today()
            obj, created = TasaCambio.objects.update_or_create(
                fecha=hoy,
                defaults={'tasa': tasa, 'fuente': 'BCV_AUTO'},
            )
            accion = 'creada' if created else 'actualizada'
            self.stdout.write(f'Tasa BCV {accion}: {tasa} VES/USD ({hoy})')

            # Rellenar huecos (fines de semana, feriados) entre la última
            # tasa conocida y hoy, usando la tasa de hoy como aplicable.
            ultima = (
                TasaCambio.objects
                .filter(fecha__lt=hoy)
                .order_by('-fecha')
                .first()
            )
            if ultima:
                gap_days = (hoy - ultima.fecha).days
                if gap_days > 1:
                    rellenos = []
                    for offset in range(1, gap_days):
                        dia = ultima.fecha + timedelta(days=offset)
                        rellenos.append(TasaCambio(
                            fecha=dia, tasa=tasa, fuente='BCV_AUTO',
                        ))
                    TasaCambio.objects.bulk_create(rellenos, ignore_conflicts=True)
                    self.stdout.write(
                        f'Rellenados {len(rellenos)} días sin tasa '
                        f'({ultima.fecha + timedelta(1)} a {hoy - timedelta(1)})'
                    )

        except Exception as exc:
            self.stderr.write(f'BCV no disponible: {exc}')
            raise SystemExit(1)
