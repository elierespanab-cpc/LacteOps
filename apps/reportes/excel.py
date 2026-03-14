import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment
from django.http import HttpResponse
from datetime import datetime


def exportar_excel(titulo, columnas, filas, filename=None):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = titulo[:31]
    hf = Font(bold=True, color="FFFFFF")
    hfill = PatternFill("solid", fgColor="1F3864")
    for ci, col in enumerate(columnas, 1):
        c = ws.cell(row=1, column=ci, value=col)
        c.font = hf
        c.fill = hfill
        c.alignment = Alignment(horizontal="center")
    for ri, fila in enumerate(filas, 2):
        for ci, val in enumerate(fila, 1):
            ws.cell(row=ri, column=ci, value=val)
    for col in ws.columns:
        ws.column_dimensions[col[0].column_letter].width = 18
    response = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    fn = filename or f"{titulo}_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
    response["Content-Disposition"] = f'attachment; filename="{fn}"'
    wb.save(response)
    return response
