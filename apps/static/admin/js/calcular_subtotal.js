/**
 * calcular_subtotal.js
 * Auto-calcula el subtotal de cada fila de detalle al cambiar cantidad o precio.
 *
 * Soporta:
 *  - Compras: campo editable costo_unitario (<input>)
 *  - Ventas:  campo readonly precio_unitario — porque en el modelo tiene editable=False,
 *             Django lo renderiza como <td class="field-precio_unitario"><p>X.XX</p></td>
 *             (no como <input>), por lo que se lee de la <p>.
 *
 * window.calcularSubtotalFila se exporta para que precio_auto_venta.js
 * pueda disparar el recálculo después de actualizar un precio.
 */
document.addEventListener('DOMContentLoaded', function () {

  function getPrecioUnitario(row) {
    // Compras: costo_unitario editable → <input name="...-costo_unitario">
    var inputCosto = row.querySelector('[name*="costo_unitario"]');
    if (inputCosto) return parseFloat(inputCosto.value) || 0;

    // Ventas hipotético editable → <input name="...-precio_unitario">
    var inputPrecio = row.querySelector('[name*="precio_unitario"]');
    if (inputPrecio) return parseFloat(inputPrecio.value) || 0;

    // Ventas readonly (editable=False) →
    //   <td class="field-precio_unitario"><p class="readonly">X.XX</p></td>
    var pReadonly = row.querySelector('.field-precio_unitario p');
    if (pReadonly) return parseFloat(pReadonly.textContent) || 0;

    return 0;
  }

  function calcularSubtotalFila(row) {
    var cantidadEl = row.querySelector('[name*="cantidad"]');
    if (!cantidadEl) return;

    var cantidad  = parseFloat(cantidadEl.value) || 0;
    var precio    = getPrecioUnitario(row);
    var resultado = (cantidad * precio).toFixed(2);

    var subtotalEl = row.querySelector('[name*="subtotal"], .field-subtotal p');
    if (!subtotalEl) return;

    if (subtotalEl.tagName === 'INPUT') {
      subtotalEl.value = resultado;
    } else {
      subtotalEl.textContent = resultado;
    }
  }

  // Exportar para uso externo (precio_auto_venta.js)
  window.calcularSubtotalFila = calcularSubtotalFila;

  function calcularTodos() {
    document.querySelectorAll('.form-row:not(.empty-form)').forEach(calcularSubtotalFila);
  }

  document.addEventListener('input', function (e) {
    if (
      e.target.name && (
        e.target.name.includes('cantidad') ||
        e.target.name.includes('costo_unitario') ||
        e.target.name.includes('precio_unitario')
      )
    ) {
      calcularTodos();
    }
  });

  calcularTodos();
});
