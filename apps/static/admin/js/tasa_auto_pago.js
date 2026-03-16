/**
 * tasa_auto_pago.js
 * Carga automática de tasa BCV en campos tasa_cambio de inlines de Pago/Cobro.
 *
 * FIX: Soporta tanto TabularInline (<tr>) como StackedInline (.form-row).
 * closest('.form-row') falla en TabularInline porque el contenedor de cada
 * fila es un <tr>, no un .form-row. Se usa || para intentar ambos.
 */
document.addEventListener('DOMContentLoaded', function () {
  function getRow(target) {
    // TabularInline → <tr> | StackedInline / campos sueltos → .form-row
    return target.closest('.form-row') || target.closest('tr');
  }

  function buscarTasa(row) {
    const fechaInput = row.querySelector('[name*="fecha"]');
    const tasaInput  = row.querySelector('[name*="tasa_cambio"]');
    if (!fechaInput || !tasaInput) return;

    const fecha = fechaInput.value;
    if (!fecha) return;

    fetch('/api/tasa/?fecha=' + fecha)
      .then(function (response) { return response.json(); })
      .then(function (data) {
        if (data.tasa && tasaInput.value === '') {
          tasaInput.value = data.tasa;
        }
      })
      .catch(function (err) { console.error('Error obteniendo tasa BCV:', err); });
  }

  document.addEventListener('change', function (e) {
    if (e.target.name && (e.target.name.includes('fecha') || e.target.name.includes('moneda'))) {
      const row = getRow(e.target);
      if (row) buscarTasa(row);
    }
  });

  document.addEventListener('focusin', function (e) {
    if (e.target.tagName === 'INPUT' && e.target.name && e.target.name.includes('fecha')) {
      const row = getRow(e.target);
      if (row) buscarTasa(row);
    }
  });
});
