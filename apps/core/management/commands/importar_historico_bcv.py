# -*- coding: utf-8 -*-
"""
Management command: importar_historico_bcv
Importa el historico completo de tasas BCV desde la pagina de estadisticas.
Rellena los dias sin dato con la tasa del dia anterior.
Uso: python manage.py importar_historico_bcv
"""
import re
import ssl
import urllib.request
from datetime import datetime, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand

from apps.core.models import TasaCambio


class Command(BaseCommand):
    help = 'Importa historico completo de tasas BCV desde bcv.org.ve/estadisticas'

    def handle(self, *args, **options):
        url = 'https://www.bcv.org.ve/estadisticas/indice-de-inversion'
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        req = urllib.request.Request(
            url,
            headers={'User-Agent': 'Mozilla/5.0 (compatible; LacteOps/1.0)'},
        )

        try:
            with urllib.request.urlopen(req, context=ctx, timeout=15) as f:
                html = f.read().decode('utf-8', errors='ignore')
        except Exception as exc:
            self.stderr.write(f'Error al descargar historico BCV: {exc}')
            raise SystemExit(1)

        tbody = re.search(r'<tbody>(.*?)</tbody>', html, re.S)
        if not tbody:
            self.stderr.write('Tabla historica no encontrada en el HTML del BCV.')
            return

        rows = re.findall(r'<tr.*?>(.*?)</tr>', tbody.group(1), re.S)
        extracted = []
        for row in rows:
            dm = re.search(r'views-field-field-fecha.*?>(.*?)</td>', row, re.S)
            rm = re.search(r'views-field-views-conditional.*?>(.*?)</td>', row, re.S)
            if dm and rm:
                try:
                    ds = re.sub('<[^<]+?>', '', dm.group(1)).strip()
                    rs = re.sub('<[^<]+?>', '', rm.group(1)).strip().replace(',', '.')
                    extracted.append((datetime.strptime(ds, '%d-%m-%Y'), float(rs)))
                except Exception:
                    continue

        if not extracted:
            self.stderr.write('No se extrajeron datos del historico BCV.')
            return

        extracted.sort(key=lambda x: x[0])

        # Rellenar dias sin dato con el valor del dia posterior conocido
        rates = {}
        for i, (d, r) in enumerate(extracted):
            rates[d.strftime('%Y-%m-%d')] = r
            if i > 0:
                prev = extracted[i - 1][0]
                for offset in range(1, (d - prev).days):
                    gap = prev + timedelta(days=offset)
                    rates[gap.strftime('%Y-%m-%d')] = r

        objs = [
            TasaCambio(
                fecha=fd,
                tasa=Decimal(str(fr)).quantize(Decimal('0.000001')),
                fuente='BCV_AUTO',
            )
            for fd, fr in rates.items()
        ]
        TasaCambio.objects.bulk_create(objs, ignore_conflicts=True)
        self.stdout.write(f'Importadas {len(objs)} tasas historicas desde el BCV.')
