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
    var fechaInput = row.querySelector('[name*="fecha"]');
    var tasaInput  = row.querySelector('[name*="tasa_cambio"]');
    if (!fechaInput || !tasaInput) return;

    var fecha = fechaInput.value;
    if (!fecha) return;

    // DIM-05-002: URLSearchParams evita inyección de caracteres especiales en la URL
    // DIM-05-003: errores de red y HTTP son visibles al operador, no solo en consola
    fetch('/api/tasa/?' + new URLSearchParams({ fecha: fecha }))
      .then(function (response) {
        if (!response.ok) throw new Error('HTTP ' + response.status);
        return response.json();
      })
      .then(function (data) {
        // Limpiar aviso previo si la tasa llegó correctamente
        var avisoExistente = row.querySelector('.tasa-error-aviso');
        if (avisoExistente) avisoExistente.style.display = 'none';

        if (data.tasa && tasaInput.value === '') {
          tasaInput.value = data.tasa;
        }
      })
      .catch(function (err) {
        console.error('Error obteniendo tasa BCV:', err);
        // Mostrar aviso visible junto al campo tasa_cambio
        var aviso = row.querySelector('.tasa-error-aviso');
        if (!aviso) {
          aviso = document.createElement('span');
          aviso.className = 'tasa-error-aviso';
          aviso.style.cssText = 'color:#c00;font-size:0.85em;margin-left:6px;';
          tasaInput.parentNode.appendChild(aviso);
        }
        aviso.textContent = '\u26a0 Sin tasa BCV. Ingrese manualmente.';
        aviso.style.display = '';
      });
  }

  document.addEventListener('change', function (e) {
    if (e.target.name && (e.target.name.includes('fecha') || e.target.name.includes('moneda'))) {
      var row = getRow(e.target);
      if (row) buscarTasa(row);
    }
  });

  document.addEventListener('focusin', function (e) {
    if (e.target.tagName === 'INPUT' && e.target.name && e.target.name.includes('fecha')) {
      var row = getRow(e.target);
      if (row) buscarTasa(row);
    }
  });
});
